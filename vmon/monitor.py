"""Background monitor thread: discover, update parsers, publish a JSON snapshot."""
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from . import clocks as clocks_mod
from . import history as history_mod
from .docs import DocLinks
from .notify import Notifier
from .eta import DurationStore, estimate, phase_durations, settings as eta_settings, step_durations
from .expected import CatalogSet
from .discovery import Discovery
from .project import LogSource, ProjectSource
from .reports import ReportCache
from .sysstats import Sampler
from .triage import BaselineStore, TriageConfig, UserRules, score_groups

RECENT_FILE = Path.home() / ".cache" / "vmon" / "recent.json"
RECENT_MAX = 20
STATUS_RANK = {"running": 0, "queued": 1, "stopped": 2, "failed": 3}
INTERVAL_MIN, INTERVAL_MAX = 0.5, 60.0
EVENTS_MAX = 100
TOP_MESSAGES = 5
TRIAGE_SEVERITIES = ("error", "critical", "warning")
_DIGITS = re.compile(r"-?\d+(\.\d+)?")


def resolve_path(text):
    """Map a user path to ('project', runs_dir) | ('log', file) | None."""
    path = Path(text).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return None
    if path.is_dir():
        if path.name.endswith(".runs"):
            return "project", str(path)
        if path.parent.name.endswith(".runs"):
            return "project", str(path.parent)
        runs = sorted(p for p in path.glob("*.runs") if p.is_dir())
        if runs:
            return "project", str(runs[0])
        return None
    if path.is_file():
        if path.suffix == ".xpr":
            return "project", str(path.parent / (path.stem + ".runs"))
        if path.parent.parent.name.endswith(".runs"):
            return "project", str(path.parent.parent)
        return "log", str(path)
    return None


class Monitor:
    def __init__(self, config, interval=1.0, recent_file=RECENT_FILE, rules_file=None):
        self.cfg = config
        self.interval = interval
        self.recent_file = Path(recent_file)
        self.tcfg = TriageConfig(config.data)
        self.user_rules = UserRules(rules_file)
        self.baselines = BaselineStore(self.recent_file.parent / "msgs")
        self.eta_cfg = eta_settings(config)
        self.durations = DurationStore(self.recent_file.parent / "durations", self.eta_cfg["history_builds"])
        self.clock_store = clocks_mod.ClockStore(self.recent_file.parent / "timing")
        self.history_cfg = history_mod.settings(config)
        self.history = history_mod.HistoryStore(self.recent_file.parent / "history", self.history_cfg["max_builds"])
        self._history_seen = {}        # (fw_id, build) -> (status, updated_at) already stored
        self.docs = DocLinks(config.data)
        self.notifier = Notifier(config.data.get("notify"))
        self.sampler = Sampler()
        self._recorded = set()         # (fw_id, build) already stored as a baseline this session
        self._top_cache = {}
        self._seen = {}                # fw_id -> {"status", "nodes", "alerts"} from the previous tick
        self._events = {}              # fw_id -> [event]
        self._system = {}
        self._tick = 0
        self.discovery = Discovery(config)
        self.reports = ReportCache(config)
        self.catalog = CatalogSet()
        self.catalog.apply_to_config(config)
        self.lock = threading.RLock()
        self.cond = threading.Condition()
        self.sources = {}              # id -> Source
        self.watched = {}              # id -> (kind, path)
        self.firmwares = {}            # id -> Firmware
        self.ignored = set()
        self._body = "[]"
        self._sys_json = "{}"
        self.version = 0
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._load_recent()

    # ------------------------------------------------------------------ paths
    def _make_source(self, kind, path):
        cls = ProjectSource if kind == "project" else LogSource
        return cls(path, self.cfg, self.reports, self.catalog, self.recent_file.parent / "attempts")

    def add_path(self, text):
        resolved = resolve_path(text)
        if resolved is None:
            return None
        with self.lock:
            return self._watch(*resolved)

    def _watch(self, kind, path):
        source = self._make_source(kind, path)
        self.ignored.discard(source.id)
        if source.id not in self.sources:
            self.sources[source.id] = source
        self.watched[source.id] = (kind, path)
        self._save_recent()
        return source.id

    def forget(self, fw_id):
        with self.lock:
            source = self.sources.get(fw_id)
            fw = self.firmwares.get(fw_id)
            if source is None or (fw is not None and fw.live):
                return False
            self.sources.pop(fw_id)
            self.firmwares.pop(fw_id, None)
            self.watched.pop(fw_id, None)
            self.ignored.add(fw_id)
            self._save_recent()
            return True

    def _load_recent(self):
        try:
            entries = json.loads(self.recent_file.read_text())
        except (OSError, ValueError):
            return
        for entry in entries[-RECENT_MAX:]:
            try:
                kind, path = entry["kind"], entry["path"]
            except (KeyError, TypeError):
                continue
            if os.path.exists(path):
                self._watch_quiet(kind, path)

    def _watch_quiet(self, kind, path):
        source = self._make_source(kind, path)
        self.sources.setdefault(source.id, source)
        self.watched[source.id] = (kind, path)

    def _save_recent(self):
        entries = [{"kind": k, "path": p} for k, p in self.watched.values()][-RECENT_MAX:]
        try:
            self.recent_file.parent.mkdir(parents=True, exist_ok=True)
            self.recent_file.write_text(json.dumps(entries))
        except OSError:
            pass

    # ------------------------------------------------------------------ tick
    def tick(self):
        with self.lock:
            try:
                groups = self.discovery.discover()
            except Exception as exc:
                print("vmon: discovery failed: %s" % exc, file=sys.stderr)
                groups = []
            by_id = {}
            for group in groups:
                source = self._make_source(group.kind, group.path)
                if source.id in self.ignored and not group.pids:
                    continue
                if source.id not in self.sources:
                    self._watch(group.kind, group.path)
                by_id[source.id] = group
            now = time.time()
            for fw_id, source in list(self.sources.items()):
                try:
                    self.firmwares[fw_id] = source.snapshot(by_id.get(fw_id), now)
                except Exception as exc:     # keep the last good state for this firmware
                    print("vmon: %s failed: %r" % (source.path, exc), file=sys.stderr)
            self._system = self.sampler.system()
            resources = self.sampler.resources({fid: fw.pids for fid, fw in self.firmwares.items()})
            for fw_id in [f for f in self._seen if f not in self.firmwares]:
                self._seen.pop(fw_id)
                self._events.pop(fw_id, None)
            for fw_id, fw in self.firmwares.items():
                fw.resources = resources.get(fw_id)
                self._observe(fw, now)
                self._record_baseline(fw_id, fw)
                self._record_durations(fw_id, fw)
                self._record_clocks(fw_id, fw)
                self._record_history(fw_id, fw)
                fw.eta = estimate(fw, self.durations.load(fw_id) if fw.status == "running" else None, now, self.eta_cfg)
                fw.events = list(self._events.get(fw_id, ()))
                fw.top_messages = self._top_messages(fw_id, fw)
            ordered = sorted(self.firmwares.values(), key=lambda f: (
                STATUS_RANK.get(f.status, 9), -(f.updated_at or 0)))
            body = json.dumps([f.to_dict() for f in ordered], separators=(",", ":"))
            self._tick += 1
            sys_json = json.dumps(self._system, separators=(",", ":"))
        if body != self._body or sys_json != self._sys_json:
            with self.cond:
                self._body, self._sys_json = body, sys_json
                self.version += 1
                self.cond.notify_all()

    # ------------------------------------------------------------------ events
    @staticmethod
    def _step_statuses(fw):
        """{node_id: (label, status)} for steps and top-level synth runs (not OOC IP runs)."""
        out = {}

        def walk(node):
            if node.kind in ("step", "run"):
                out[node.id] = (node.label, node.status, node.failure["reason"] if node.failure else None)
            elif node.kind == "group" and not node.id.endswith("/ooc"):
                for child in node.children:
                    walk(child)

        for flow in fw.flows:
            for stage in flow.stages:
                walk(stage)
        return out

    def _observe(self, fw, now):
        steps = self._step_statuses(fw)
        alerts = {(a["node_id"], a["code"], _DIGITS.sub("#", a["message"])): a for a in fw.alerts}
        prev = self._seen.get(fw.id)
        attempt = (fw.attempt or {}).get("n", 1)
        self._seen[fw.id] = {"status": fw.status, "nodes": steps, "alerts": set(alerts), "attempt": attempt}
        if prev is None:
            return                      # first observation: only live transitions produce events
        found = []
        if attempt > prev.get("attempt", 1):
            how = fw.attempt.get("mode", "project")
            origin = fw.attempt.get("resumed_from")
            found.append(("attempt_started", "info", None, None,
                          "Attempt %d started (%s%s)" % (attempt, how, " after " + origin if origin else ""),
                          "previous failure: %s" % fw.attempt["previous_failure"]
                          if fw.attempt.get("previous_failure") else ""))
        for node_id, (label, status, reason) in steps.items():
            before = prev["nodes"].get(node_id, (label, "pending"))[1]
            if status == before:
                continue
            if status == "running":
                found.append(("step_started", "info", None, node_id, "%s started" % label, ""))
            elif status == "done":
                found.append(("step_done", "info", None, node_id, "%s done" % label, ""))
            elif status == "failed":
                found.append(("step_failed", "error", "step_failed", node_id, "%s failed" % label, reason or ""))
        if fw.status != prev["status"]:
            if fw.status == "done":
                found.append(("run_done", "info", None, None, "Build finished", ""))
            elif fw.status == "failed":
                found.append(("run_failed", "error", "step_failed", None, "Build failed", ""))
            elif fw.status == "stopped":
                found.append(("run_failed", "error", "process_gone", None, "Vivado process gone", ""))
        for key, alert in alerts.items():
            if key not in prev["alerts"] and alert["code"] not in ("step_failed", "process_gone"):
                found.append(("alert", alert["level"], alert["code"], alert["node_id"],
                              "Alert: %s" % alert["code"].replace("_", " "), alert["message"]))
        if found:
            log = self._events.setdefault(fw.id, [])
            for kind, level, code, node_id, title, message in found:
                log.append({"t": now, "kind": kind, "level": level, "code": code, "node_id": node_id,
                            "title": "%s: %s" % (fw.name, title), "message": message or title})
                self.notifier.submit(fw, log[-1])      # only live transitions reach here (see the first-observation return)
            del log[:-EVENTS_MAX]

    # ------------------------------------------------------------------ triage
    @staticmethod
    def _build_key(fw):
        return str(int(fw.started_at or fw.updated_at or 0))

    def _record_baseline(self, fw_id, fw):
        """Store the message counts of a finished build as the baseline for the next one."""
        if fw.status not in ("done", "failed"):
            return
        build = self._build_key(fw)
        if (fw_id, build) in self._recorded:
            return
        source = self.sources.get(fw_id)
        raw = source.raw_groups(None, None) if source else None
        if raw is None:
            return
        self._recorded.add((fw_id, build))
        self.baselines.record(fw_id, build, {g["id"]: g["count"] for g in raw})

    def _record_durations(self, fw_id, fw):
        """Per-step and per-phase durations of a finished build, for later builds' ETA."""
        if fw.status == "done" and fw.flows:
            self.durations.record(fw_id, self._build_key(fw), step_durations(fw), fw.elapsed_s, phase_durations(fw))

    def _record_history(self, fw_id, fw):
        """Store a finished build in the history (also catches up on builds finished before startup)."""
        if fw.status not in history_mod.FINISHED or fw.started_at is None:
            return
        key, sig = (fw_id, self._build_key(fw)), (fw.status, fw.updated_at)
        if self._history_seen.get(key) == sig:
            return
        self._history_seen[key] = sig
        source = self.sources.get(fw_id)
        groups = source.raw_groups(None, None) if source else None
        final = clocks_mod.final_stage(fw, clocks_mod.stages_of(fw, self.cfg), self.cfg)
        self.history.record(history_mod.build_record(fw, key[1], self.history_cfg, groups, final and final["per_clock"]))

    def _record_clocks(self, fw_id, fw):
        """Final per-clock timing of a finished build (also catches up on builds not stored yet)."""
        stages = clocks_mod.stages_of(fw, self.cfg)
        final = clocks_mod.final_stage(fw, stages, self.cfg)
        if final is not None:
            self.clock_store.record(fw_id, fw.started_at, final["per_clock"])
        fw.clock_history = clocks_mod.history(fw, self.clock_store, self.cfg)

    def triage(self, fw_id, node_id=None, severities=None, query=None, include_muted=False, limit=500):
        source = self.sources.get(fw_id)
        fw = self.firmwares.get(fw_id)
        if source is None or fw is None:
            return None
        sevs = severities or list(TRIAGE_SEVERITIES)
        raw = source.raw_groups(node_id or None, sevs)
        if raw is None:
            return None
        baseline = self.baselines.baseline(fw_id, self._build_key(fw))
        groups = score_groups(raw, self.tcfg, self.user_rules.rules, baseline, self.docs)
        if query:
            needle = query.lower()
            groups = [g for g in groups if needle in g["id"].lower() or needle in g["text"].lower()]
        if not include_muted:
            groups = [g for g in groups if not g["muted"]]
        groups = groups[:limit]
        for g in groups:
            g["nodes"] = source.group_nodes(g["id"], node_id or None)
        return {"baseline": baseline is not None, "groups": groups}

    def _top_messages(self, fw_id, fw):
        source = self.sources.get(fw_id)
        if source is None:
            return []
        key = (source.msg_generation(), self.user_rules.version, self.baselines.version,
               self._build_key(fw))
        hit = self._top_cache.get(fw_id)
        if hit and hit[0] == key:
            return hit[1]
        result = self.triage(fw_id, None, None, None, False, TOP_MESSAGES)
        top = result["groups"] if result else []
        for g in top:
            g.pop("muted", None)
        self._top_cache[fw_id] = (key, top)
        return top

    def set_msgrule(self, msg_id, priority):
        self.user_rules.set(msg_id, priority)      # ValueError on bad input
        with self.lock:
            self._top_cache.clear()
        self.tick()

    # ------------------------------------------------------------------ settings
    def set_interval(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (
                INTERVAL_MIN <= value <= INTERVAL_MAX):
            raise ValueError("interval must be a number between %g and %g" % (INTERVAL_MIN, INTERVAL_MAX))
        self.interval = float(value)
        self._wake.set()               # re-arm the loop with the new period right away
        with self.cond:
            self.version += 1
            self.cond.notify_all()

    def state_json(self):
        return ('{"generated_at":%f,"version":1,"tick":%d,"system":%s,"settings":{"interval":%g},'
                '"firmwares":%s}' % (time.time(), self._tick, self._sys_json, self.interval, self._body))

    def wait_for_change(self, last_version, timeout):
        with self.cond:
            if self.version == last_version:
                self.cond.wait(timeout)
            return self.version

    def source_for(self, fw_id):
        return self.sources.get(fw_id)

    # ------------------------------------------------------------------ thread
    def start(self):
        self.tick()
        self._thread = threading.Thread(target=self._loop, name="vmon-monitor", daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            self._wake.wait(self.interval)
            if self._stop.is_set():
                break
            self._wake.clear()
            try:
                self.tick()
            except Exception as exc:
                print("vmon: tick failed: %r" % exc, file=sys.stderr)

    def stop(self):
        self._stop.set()
        self.notifier.stop()
        self._wake.set()
        with self.cond:
            self.cond.notify_all()
