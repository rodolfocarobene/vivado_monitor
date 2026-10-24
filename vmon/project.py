"""Builds a Firmware (flows, nodes, counts, timing, reports, alerts) from run dirs or a log.

Everything is read-only. Parsers are kept between ticks (ParsedLog) so each tick only
consumes appended bytes.
"""
import bisect
import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import alerts as alert_rules
from . import artifacts as artifacts_mod
from . import congestion as congestion_mod
from . import convergence as convergence_mod
from . import failure as failure_mod
from .attempts import AttemptStore
from .config import StepDef
from .discovery import in_scratch, pid_alive
from .resume import scan_session
from .docs import DocLinks
from . import info as info_mod
from .logparse import LogParser, SEVERITIES
from .logtail import LogTail, file_identity
from .paths import path_key
from .model import Firmware, Flow, Node, Timing, compute_met, counts_dict

PID_RE = re.compile(r'Pid="(\d+)"')
MAX_LOG_LINES = 5000
RECENT_GROWTH_S = 5.0
_REAL_NUMBER = re.compile(r"^\d+(\.\d+)*$")
_METRICS = ("wns", "tns", "whs", "ths")
_CARRIED = ("whs", "ths")      # setup values (wns/tns) from another pass would contradict the new ones


def fw_id(path):
    return hashlib.sha1(path_key(path).encode()).hexdigest()[:10]


class ParsedLog:
    def __init__(self, path, config, catalogs=None):
        self.path = str(path)
        self.cfg = config
        self.tail = LogTail(path)
        self.catalogs = catalogs
        self.parser = LogParser(config, catalogs)
        self._primed = False

    def update(self):
        lines, reset = self.tail.poll()
        if reset:
            self.parser = LogParser(self.cfg, self.catalogs)
            self._primed = False
        if lines:
            self.parser.live = self._primed
            self.parser.feed(lines)
            self._primed = True
            self.parser.live = True

    @property
    def line_count(self):
        return self.tail.line_count

    def growth_age(self, now):
        return None if self.tail.last_growth is None else max(0.0, now - self.tail.last_growth)


def assign_sections(planned, sections, cfg):
    """Map step ids to log sections; ambiguous commands (phys_opt_design) are taken in order."""
    result, last = {}, -1
    for section in sections:
        for step in cfg.steps_for_command(section.cmd):
            if step.id in result:
                continue
            if planned:
                idx = planned.index(step.id) if step.id in planned else None
            else:
                idx = cfg.step_order.index(step.id)
            if idx is not None and idx > last:
                result[step.id] = section
                last = idx
                break
    return result


def extra_sections(assigned, sections):
    """Sections no step claimed (place/phys_opt/route run again by a Tcl hook or a script) belong to the step whose
    section precedes them in the log: {step id: [section, ...]}."""
    owner = {id(section): sid for sid, section in assigned.items()}
    out, current = {}, None
    for section in sections:
        if id(section) in owner:
            current = owner[id(section)]
        elif current is not None:
            out.setdefault(current, []).append(section)
    return out


def _aggregate_status(statuses, live):
    statuses = list(statuses)
    if not statuses:
        return "pending"
    for state in ("failed", "running", "stopped"):
        if state in statuses:
            return state
    if all(s == "done" for s in statuses):
        return "done"
    if "done" in statuses:
        return "running" if live else "stopped"
    if "queued" in statuses:
        return "queued"
    return "pending"


class RunState:
    """What the marker files / dir listing say about one run directory."""

    def __init__(self, run_id, kind, flow_id=None):
        self.id = run_id
        self.kind = kind
        self.flow_id = flow_id
        self.dir = None
        self.entries = {}
        self.status = "pending"
        self.begin = None
        self.end = None
        self.alive = False
        self.log_path = None
        self.top = None
        self.markers = {}          # step -> {"begin","end","error","pid"}


class Source:
    """Common state for project and log firmwares."""
    kind = "log"

    def __init__(self, path, config, report_cache, catalog, attempt_dir=None):
        self.path = str(path)
        self.cfg = config
        self.docs = DocLinks(config.data)
        self.reports = report_cache
        self.catalog = catalog
        self.id = fw_id(self.path)
        self.store = AttemptStore(attempt_dir, self.id)
        self.logs = {}
        self.index = {}            # node id -> [(ParsedLog, line_start, line_end, running)]
        self.report_paths = set()
        self._xml_cache = {}
        self._pid_cache = {}
        self._tcl_cache = {}
        self.info_reader = info_mod.InfoReader()
        self.version = None
        self._parsers = []
        self.root_ranges = []      # whole-firmware log ranges
        self._step_nodes = {}      # node id -> step/run Node (for triage "nodes")
        self._agg_cache = None

    # ------------------------------------------------------------------ shared helpers
    def _log(self, path):
        plog = self.logs.get(path)
        if plog is None:
            plog = self.logs[path] = ParsedLog(path, self.cfg, self.catalog)
        plog.update()
        self.version = plog.parser.version or self.version
        return plog

    def _register(self, node, plog, line_start, line_end, running):
        if plog is not None and line_start is not None:
            self.index[node.id] = [(plog, line_start, line_end or plog.line_count, running)]

    def _register_group(self, node):
        ranges = []
        for child in node.children:
            ranges.extend(self.index.get(child.id, ()))
        if ranges:
            self.index[node.id] = ranges

    def _convert(self, pnode, parent_id, plog, open_status):
        node = Node(id="%s/%s" % (parent_id, pnode.key), label=self._label(pnode), kind=pnode.kind)
        node.status = open_status if pnode.status == "running" else pnode.status
        node.counts = list(pnode.own)
        node.started_at, node.ended_at = pnode.started_at, pnode.ended_at
        node.elapsed_s = pnode.elapsed_s
        node.peak_mem_mb = pnode.peak_mem
        node.log = plog.path
        node.line_start = pnode.line_start
        node.line_end = pnode.line_end or plog.line_count
        if pnode.kind == "phase" and pnode.number and _REAL_NUMBER.match(pnode.number):
            node.number = pnode.number
        node.children = [self._convert(c, node.id, plog, open_status) for c in pnode.children]
        for child in node.children:
            for i, value in enumerate(child.counts):
                node.counts[i] += value
        if node.status == "running" and node.elapsed_s is None and node.started_at:
            node.elapsed_s = max(0.0, time.time() - node.started_at)
        if node.elapsed_s is None and node.started_at and node.ended_at:
            node.elapsed_s = node.ended_at - node.started_at
        self._register(node, plog, node.line_start, node.line_end, node.status == "running")
        return node

    @staticmethod
    def _label(pnode):
        if pnode.kind == "phase" and pnode.number and pnode.number != "stage" and not pnode.number.startswith("pair:"):
            return "%s %s" % (pnode.number, pnode.label)
        return pnode.label

    def _timing_stage(self, step_id, status, label, report=False):
        """(final, stage text) for a timing value; only post-route results count as final."""
        alerts = self.cfg.alerts
        short = (self.cfg.steps[step_id].label if step_id in self.cfg.steps else step_id).replace(" Design", "")
        if report:
            final = step_id in alerts.get("timing_final_steps", ())
            return final, "%s · %s" % (short, "final report" if final else "report")
        final = (label == "Post Routing"
                 or (step_id in alerts.get("timing_final_steps", ()) and step_id != "route_design")
                 or (step_id in alerts.get("timing_error_steps", ()) and status == "done"))
        if final:
            return True, "%s · final" % short
        kind = "intermediate" if label == "Intermediate" else "estimate"
        return False, "%s · %s" % (short, kind)

    def _timing_from_history(self, section, step_id=None, status=None):
        if section is None or not section.history:
            return None
        last = section.history[-1]
        final, stage = self._timing_stage(step_id, status, last["label"])
        return Timing(wns=last["wns"], tns=last["tns"], whs=last["whs"], ths=last["ths"],
                      met=compute_met(last["wns"], last["tns"], last["whs"], last["ths"]),
                      source="log", label=last["label"], history=list(section.history),
                      final=final, stage=stage)

    def _progress(self, node):
        kids = [c for c in node.children if not c.expected]
        return {"done": sum(1 for c in kids if c.status == "done"), "total": len(kids)} if kids else None

    def _extra_node(self, node_id, section, plog, open_status):
        """A step command run again inside another step (hook/script), with its phases."""
        node = self._convert(section, node_id, plog, open_status)
        node.kind = "command"
        node.label = "%s (script)" % section.cmd
        node.description = "Run inside this step by a Tcl hook or script, after the step's own command"
        return node

    def _step_node(self, step_id, node_id, plog, section, status, open_status, alive, run_id,
                   begin=None, end=None, reports=(), now=None, failure=None, extras=()):
        stepdef = self.cfg.steps.get(step_id) or StepDef(step_id, {})
        node = Node(id=node_id, label=stepdef.label, kind="step", status=status, run=run_id)
        node.started_at, node.ended_at = begin, end
        if section is not None:
            node.children = [self._convert(c, node_id, plog, open_status) for c in section.children]
            node.counts = list(section.own)
            for child in node.children:
                for i, value in enumerate(child.counts):
                    node.counts[i] += value
            node.peak_mem_mb = section.peak_mem
            node.log = plog.path
            node.line_start = section.line_start
            node.line_end = section.line_end or plog.line_count
            node.timing = self._timing_from_history(section, step_id, status)
            node.convergence = convergence_mod.summarize(section.iters, self.cfg)
            node.congestion = congestion_mod.summarize(section.congestion, self.cfg)
            for extra in extras:
                child = self._extra_node(node_id, extra, plog, open_status)
                node.children.append(child)
                for i, value in enumerate(child.counts):
                    node.counts[i] += value
                node.line_end = child.line_end
                if extra.peak_mem and (node.peak_mem_mb is None or extra.peak_mem > node.peak_mem_mb):
                    node.peak_mem_mb = extra.peak_mem
            node.progress = self._progress(node)
            if node.started_at is None:
                node.started_at = section.started_at
            self._register(node, plog, node.line_start, node.line_end, status == "running")
        if begin is not None and status == "running":
            node.elapsed_s = max(0.0, (now or time.time()) - begin)
        elif begin is not None and end is not None:
            node.elapsed_s = max(0.0, end - begin)
        elif section is not None:
            node.elapsed_s = section.elapsed_s
        node.reports = list(reports)
        hook_timing = next((t for t in (self._timing_from_history(x, step_id, status) for x in reversed(extras)) if t), None)
        for report in node.reports:
            summary = report["summary"]
            if hook_timing is not None:
                break                 # the step's reports come before its post-hook commands: the log is newer
            if report["kind"] == "timing_summary" and not report["stale"] and summary.get("wns") is not None:
                history = node.timing.history if node.timing else []
                final, stage = self._timing_stage(step_id, status, "", report=True)
                node.timing = Timing(final=final, stage=stage, 
                    wns=summary.get("wns"), tns=summary.get("tns"), whs=summary.get("whs"),
                    ths=summary.get("ths"), tns_fail=summary.get("tns_fail"),
                    ths_fail=summary.get("ths_fail"), wpws=summary.get("wpws"),
                    met=compute_met(summary.get("wns"), summary.get("tns"), summary.get("whs"),
                                    summary.get("ths")),
                    source="report", label="Timing report", history=history,
                    clocks=summary.get("clocks", []), report=report["path"],
                    path_counts=summary.get("path_counts"), paths=summary.get("paths", []))
        if hook_timing is not None:
            hook_timing.final, hook_timing.stage = False, "%s (script)" % extras[-1].cmd
            node.timing = hook_timing
        node.children = self.catalog.merge(step_id, node, status, self.version)
        stall = plog.growth_age(now or time.time()) if plog and section is not None else None
        node.failure = failure
        node.alerts = alert_rules.node_alerts(node, step_id, self.cfg, stall, alive)
        return node

    # ------------------------------------------------------------------ failures and attempts
    def _failure_for(self, log_paths, run_dir=None, since=None, section=None, plog=None):
        """Failure dict for a failed step: crash patterns / hs_err first, else its first ERROR messages."""
        found = failure_mod.detect(log_paths, self.cfg, run_dir, since)
        if found:
            self._register_log(found["log"])
            return found
        if section is not None and plog is not None:
            return failure_mod.from_errors(plog.parser.messages, section.line_start or 1,
                                           section.line_end or plog.line_count, plog.path)
        return {"reason": "Error", "details": [], "line": None, "log": None, "hs_err": None}

    def _register_log(self, path):
        """Make a failure log (runme.log) known so its lines can be shown around the failure."""
        if path and path not in self.logs and os.path.isfile(path):
            self._log(path)

    def _attempt_summary(self, node, n, mode, checkpoint, log):
        phase = _deepest_failed(node) if node.status == "failed" else None
        text = node.status
        if node.status == "failed":
            text = "failed"
            if phase is not None:
                text += " in %s%s" % ("Phase " if phase.label[:1].isdigit() else "", phase.label)
            if node.failure:
                text += ": %s" % node.failure["reason"]
        elif node.status == "done" and node.elapsed_s:
            text = "done in %s" % fmt_duration(node.elapsed_s)
        timing = node.timing
        return {"n": n, "status": node.status, "started_at": node.started_at, "ended_at": node.ended_at,
                "elapsed_s": node.elapsed_s, "log": log or node.log, "mode": mode, "checkpoint": checkpoint,
                "failure": node.failure, "summary": text, "counts": counts_dict(node.counts),
                "timing": {"wns": timing.wns, "tns": timing.tns, "whs": timing.whs, "ths": timing.ths,
                           "met": timing.met, "final": timing.final, "stage": timing.stage} if timing else None,
                "convergence": node.convergence}

    def _deepest_running(self, nodes):
        best = None

        def walk(node, trail, depth):
            nonlocal best
            if node.status == "running" and not node.expected:
                if best is None or depth > best[0]:
                    best = (depth, node, trail)
            for child in node.children:
                walk(child, trail, depth + 1)

        for stage in nodes:
            walk(stage, stage.label, 0)
        if best is None:
            return None
        _, node, _ = best
        return node

    def _current(self, flows):
        best = None
        for flow in flows:
            for stage in flow.stages:
                node = self._deepest_running([stage])
                if node is not None:
                    best = (stage, node)
        if best is None:
            return None
        stage, node = best
        label = node.label if node is stage else "%s › %s" % (stage.label, node.label)
        return {"node_id": node.id, "label": label}

    def _carry_timing(self, flows):
        """Fill metrics a newest log line lacks (N/A, estimates) from earlier values of the same build."""
        pool = {}                      # metric -> (value, origin dict)
        seen = set()
        for flow in flows:
            for stage in flow.stages:
                for node in self._flat_steps(stage):
                    timing = node.timing
                    if timing is None or id(node) in seen:
                        continue
                    seen.add(id(node))
                    step_id = node.id.rsplit("/", 1)[-1]
                    if node.kind == "run":
                        step_id = "synth_design"
                    entries = timing.history
                    for index, entry in enumerate(entries):
                        last = index == len(entries) - 1
                        origin = {"label": self._timing_stage(step_id, node.status, entry["label"])[1],
                                  "line": entry["line"], "t": entry["t"]}
                        if last and timing.source == "log":
                            for name in _CARRIED:
                                if getattr(timing, name) is None and name in pool:
                                    value, source = pool[name]
                                    setattr(timing, name, value)
                                    timing.carried[name] = dict(source)
                            timing.met = compute_met(timing.wns, timing.tns, timing.whs, timing.ths)
                        for name in _METRICS:
                            if entry[name] is not None:
                                pool[name] = (entry[name], origin)
                    if timing.source == "report":
                        origin = {"label": timing.stage, "line": None, "t": None}
                        for name in _METRICS:
                            if getattr(timing, name) is not None:
                                pool[name] = (getattr(timing, name), origin)
                    if timing.carried:
                        node.alerts = [a for a in node.alerts if a["code"] != "timing_fail"]
                        node.alerts.extend(alert_rules.timing_alerts(node, step_id))

    def _finish(self, fw, flows, parsers, group, live, now):
        fw.flows = flows
        self._carry_timing(flows)
        fw.live = live
        fw.pids = sorted(group.pids) if group else []
        fw.launcher = group.launcher if group else None
        fw.current = self._current(flows)
        total = [0, 0, 0, 0]
        for plog in parsers:
            for i, value in enumerate(plog.parser.root.rolled_counts()):
                total[i] += value
        fw.counts = total
        for flow in reversed(flows):
            for stage in reversed(flow.stages):
                for node in reversed(self._flat_steps(stage)):
                    if node.timing is not None:
                        fw.timing = node.timing
                        break
                if fw.timing:
                    break
            if fw.timing:
                break
        seen = {}
        for flow in flows:
            for alert in alert_rules.collect(flow.stages):
                seen[(alert["node_id"], alert["code"], alert["message"])] = alert
        fw.alerts = list(seen.values())
        fw.health = alert_rules.health(fw.alerts)
        fw.progress_estimate = self.catalog.progress(flows, self.version)
        for flow in flows:
            self.docs.annotate(flow.stages)
        versions = [p.parser.version for p in parsers if p.parser.version]
        fw.vivado_version = versions[0] if versions else None
        fw.utilization = self._utilization(flows)
        fw.info = self._info(fw)
        self._parsers = list(parsers)
        self.root_ranges = [(p, 1, p.line_count, False) for p in parsers]
        self._step_nodes = {}
        for flow in flows:
            for stage in flow.stages:
                for node in self._flat_steps(stage):
                    if node.id in self.index:
                        self._step_nodes.setdefault(node.id, node)

    def _info(self, fw):
        return info_mod.collect(self.info_reader, None, None, None, self.path, Path(self.path).stem,
                                fw.vivado_version)

    def _utilization(self, flows):
        """Headline rows of the latest non-stale utilization report (routed > placed > synth)."""
        rank = {"routed": 0, "placed": 1, "synth": 2}
        best = None
        stack = [s for f in flows for s in f.stages]
        while stack:
            node = stack.pop()
            if node.id == "synth/ooc":
                continue                       # IP out-of-context runs are not the design
            stack.extend(node.children)
            for report in node.reports:
                if report["kind"] != "utilization" or report["stale"] or not _has_logic(report):
                    continue
                match = re.search(r"utilization_(routed|placed|synth)", report["name"])
                key = (rank[match.group(1)] if match else 9, -report["mtime"])
                if best is None or key < best[0]:
                    best = (key, node, report)
        if best is None:
            return None
        _, node, report = best
        rows = {r["name"]: r for r in report["summary"].get("rows", ())}
        wanted = self.cfg.data.get("ui", {}).get("headline_resources") or list(rows)
        out = [{"name": n, "label": rows[n].get("label"), "used": rows[n]["used"],
                "available": rows[n]["available"], "pct": rows[n]["pct"]} for n in wanted if n in rows]
        return {"step": node.label, "label": report["label"], "report": report["name"],
                "path": report["path"], "rows": out}

    def _flat_steps(self, node):
        out = [node] if node.kind in ("step", "run") else []
        for child in node.children:
            out.extend(self._flat_steps(child))
        return out

    # ------------------------------------------------------------------ queries
    def _ranges(self, node_id):
        return self.index.get(node_id)

    def messages(self, node_id, severities=None, limit=500, msg_id=None):
        """Message instances + per-id groups for a node (None = whole firmware), optional id filter."""
        ranges = self.root_ranges if not node_id else self._ranges(node_id)
        if ranges is None:
            return None
        wanted = {SEVERITIES.index(s) for s in (severities or SEVERITIES) if s in SEVERITIES}
        items, groups, total = [], {}, 0
        for plog, start, end, _ in ranges:
            msgs = plog.parser.messages
            lo = bisect.bisect_left(msgs, start, key=lambda m: m[0])
            hi = bisect.bisect_right(msgs, end, key=lambda m: m[0])
            for line, sev, mid, text in msgs[lo:hi]:
                if sev not in wanted:
                    continue
                key = mid or text[:60]
                if msg_id is not None and key != msg_id:
                    continue
                total += 1
                if len(items) < limit:
                    items.append({"severity": SEVERITIES[sev], "id": mid, "text": text, "line": line,
                                  "log": plog.path})
                group = groups.get(key)
                if group is None:
                    groups[key] = {"id": key, "severity": SEVERITIES[sev], "count": 1, "text": text,
                                   "first_line": line, "last_line": line,
                                   "doc_url": self.docs.message_url(mid) if mid else None}
                else:
                    group["count"] += 1
                    group["last_line"] = line
                    if sev > SEVERITIES.index(group["severity"]):
                        group["severity"] = SEVERITIES[sev]
        ordered = sorted(groups.values(),
                         key=lambda g: (-SEVERITIES.index(g["severity"]), -g["count"], g["first_line"]))
        return {"node_id": node_id or None, "groups": ordered, "items": items, "total": total,
                "truncated": total > len(items)}

    # ---- triage support
    def msg_generation(self):
        """Changes whenever any parser saw a new message (or was replaced)."""
        return tuple((id(p.parser), p.parser.msg_count) for p in self._parsers)

    def raw_groups(self, node_id=None, severities=None):
        """Per-id aggregates for the whole firmware (cached) or one node. None if the node is unknown."""
        wanted = set(severities or SEVERITIES)
        if node_id:
            result = self.messages(node_id, list(wanted), limit=0)
            if result is None:
                return None
            groups = []
            for g in result["groups"]:
                groups.append(dict(g, log=self._log_of(node_id)))
            return groups
        gen = self.msg_generation()
        if self._agg_cache is None or self._agg_cache[0] != gen:
            merged = {}
            for plog in self._parsers:
                for key, (sev, count, text, first, last) in plog.parser.agg.items():
                    cur = merged.get(key)
                    if cur is None:
                        merged[key] = {"id": key, "sev": sev, "count": count, "text": text,
                                       "first_line": first, "last_line": last, "log": plog.path}
                    else:
                        cur["sev"] = max(cur["sev"], sev)
                        cur["count"] += count
            self._agg_cache = (gen, merged)
        return [{"id": g["id"], "severity": SEVERITIES[g["sev"]], "count": g["count"], "text": g["text"],
                 "first_line": g["first_line"], "last_line": g["last_line"], "log": g["log"]}
                for g in self._agg_cache[1].values() if SEVERITIES[g["sev"]] in wanted]

    def _log_of(self, node_id):
        ranges = self._ranges(node_id)
        return ranges[0][0].path if ranges else None

    def group_nodes(self, key, node_id=None):
        """Steps/runs whose log range contains a message of this group."""
        out = []
        scope = self.index.get(node_id, ()) if node_id else ()
        for nid, node in self._step_nodes.items():
            if node_id and nid != node_id and not nid.startswith(node_id + "/") and not any(
                    p is sp and start >= ss and end <= se
                    for p, start, end, _ in self.index.get(nid, ()) for sp, ss, se, _ in scope):
                continue
            for plog, start, end, _ in self.index.get(nid, ()):
                lines = plog.parser.lines_by_key.get(key)
                if lines:
                    i = bisect.bisect_left(lines, start)
                    if i < len(lines) and lines[i] <= end:
                        out.append({"node_id": nid, "label": node.label})
                        break
        return out

    def log_excerpt(self, node_id, tail=200):
        ranges = self._ranges(node_id)
        if not ranges:
            return None
        plog, start, end, running = ranges[-1]
        end = min(end, plog.line_count)
        if running:
            start = max(start, end - tail + 1)
        truncated = end - start + 1 > MAX_LOG_LINES
        if truncated:
            end = start + MAX_LOG_LINES - 1
        return {"path": plog.path, "start_line": start, "end_line": end,
                "lines": plog.tail.read_range(start, end), "truncated": truncated}

    def log_around(self, path, line, context=30):
        """Excerpt around `line` of a known log, or None if the path is not one of this firmware's logs."""
        plog = self.logs.get(path)
        if plog is None:
            return None
        end_total = plog.line_count
        line = max(1, min(line, end_total))
        context = max(0, min(context, 500))
        start, end = max(1, line - context), min(end_total, line + context)
        return {"path": plog.path, "start_line": start, "end_line": end, "around": line,
                "lines": plog.tail.read_range(start, end), "truncated": False}

    def allowed_report(self, path):
        return path in self.report_paths

    def timing_paths(self, path, kind=None, only_failing=False):
        """Worst paths of a timing_summary report: {"path", "paths", "counts"} or None if unknown/unparsed."""
        real = os.path.realpath(path)
        known = path if path in self.report_paths else real if real in self.report_paths else None
        if known is None:
            return None
        found = self.reports.paths(known)
        if found is None:
            return None
        paths = [p for p in found["paths"]
                 if (kind is None or p["type"] == kind) and (not only_failing or p["status"] == "VIOLATED")]
        return {"path": known, "paths": paths, "counts": found["counts"]}


# ====================================================================== project mode
class ProjectSource(Source):
    kind = "project"

    def __init__(self, runs_dir, config, report_cache, catalog, attempt_dir=None):
        super().__init__(runs_dir, config, report_cache, catalog, attempt_dir)
        self.runs_dir = Path(runs_dir)
        self.name = self.runs_dir.name[:-5]
        self._impl_ctx = (None, None)
        self._extra_parsers = []     # resume logs parsed this tick
        self._attempt_info = {}      # run id -> Firmware.attempt dict

    def _info(self, fw):
        impl, synth = self._impl_ctx
        return info_mod.collect(
            self.info_reader, self.runs_dir, impl.id if impl else None, synth.id if synth else None,
            (impl or synth).log_path if (impl or synth) else None, (impl or synth).top if (impl or synth) else None,
            fw.vivado_version, self.runs_dir.parent / (self.name + ".xpr"))

    # ---- launch description
    def _launch_runs(self):
        jobs = self.runs_dir / self.cfg.jobs_dir
        try:
            launches = sorted(((path.stat().st_mtime, path) for path in jobs.glob(self.cfg.jobs_glob)), reverse=True)
        except OSError:
            launches = []
        runs, launch_time = [], launches[0][0] if launches else None
        parsed_by_key = {}
        for mtime, path in launches:
            key = (str(path), mtime)
            if key not in self._xml_cache:
                try:
                    root = ET.parse(path).getroot()
                    self._xml_cache[key] = [(r.get("Id"), r.get("FlowId"), [p.get("Id") for p in r.findall("Parent")])
                                            for r in root.findall("Run")]
                except (ET.ParseError, OSError):
                    self._xml_cache[key] = []
            parsed_by_key[key] = parsed = self._xml_cache[key]
            if not runs:
                runs = list(parsed)
            elif parsed:
                # A script that runs `launch_runs impl_1` after synthesis finished writes a launch with impl_1 only:
                # the synthesis (and its OOC runs) it builds on comes from the latest earlier launch that has one.
                seen = {rid for rid, _, _ in runs}
                runs = [r for r in parsed if r[0] not in seen] + runs
            if any(self.cfg.classify_run(rid, flow) in ("synth", "ooc") for rid, flow, _ in runs):
                break
        self._xml_cache = parsed_by_key
        if not runs:
            try:
                names = sorted(e.name for e in os.scandir(self.runs_dir) if e.is_dir())
            except OSError:
                names = []
            for name in names:
                if self.cfg.classify_run(name) in ("synth", "impl"):
                    runs.append((name, None, []))
        order = {rid: (flow, parents) for rid, flow, parents in runs}
        listed = [rid for rid, _, _ in runs]
        for rid, _, parents in list(runs):          # parents of listed runs are part of the launch
            for parent in parents:
                if parent not in order and (self.runs_dir / parent).is_dir():
                    order[parent] = (None, [])
                    listed.append(parent)
        parent_ids = {p for _, parents in order.values() for p in parents}
        states = []
        for rid in listed:
            flow_id, _ = order[rid]
            kind = self.cfg.classify_run(rid, flow_id)
            if kind in ("synth", "ooc") and rid in parent_ids and kind == "synth" and not re.search(
                    r"^synth_\d+$", rid):
                kind = "ooc"
            if kind is None:
                continue
            states.append(RunState(rid, kind, flow_id))
        return states, launch_time

    # ---- run directory inspection
    def _marker_pid(self, path, mtime):
        hit = self._pid_cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            match = PID_RE.search(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            match = None
        pid = int(match.group(1)) if match else None
        self._pid_cache[path] = (mtime, pid)
        return pid

    def _inspect(self, run, group):
        rdir = self.runs_dir / run.id
        try:
            entries = {e.name: e for e in os.scandir(rdir)}
        except OSError:
            return False
        run.dir, run.entries = rdir, entries
        for name, entry in entries.items():
            if name.startswith(".") and name.endswith(".rst"):
                parts = name[1:-4].rsplit(".", 1)
                if len(parts) == 2 and parts[1] in ("begin", "end", "error"):
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    info = run.markers.setdefault(parts[0], {})
                    info[parts[1]] = mtime
                    if parts[1] == "begin":
                        info["pid"] = self._marker_pid(entry.path, mtime)
        vivado = run.markers.get("vivado", {})
        run.begin, run.end = vivado.get("begin"), vivado.get("end")
        wanted = ".vdi" if run.kind == "impl" else ".vds"
        logs = sorted((n for n in entries if n.endswith(wanted)),
                      key=lambda n: -entries[n].stat().st_mtime)
        if logs:
            run.log_path, run.top = str(rdir / logs[0]), logs[0][:-4]
        elif "runme.log" in entries:
            run.log_path = str(rdir / "runme.log")
        marker_pids = [m.get("pid") for m in run.markers.values() if "end" not in m and "begin" in m]
        run.alive = bool(group and group.run_pids.get(run.id)) or any(pid_alive(p) for p in marker_pids)
        queued = any(self._glob_match(n) for n in entries)
        done_file = self.cfg.synth_complete_file in entries and run.kind != "impl"
        if "error" in vivado or any("error" in m for m in run.markers.values()):
            run.status = "failed"
        elif "end" in vivado or done_file:
            run.status = "done"
        elif run.begin is not None:
            run.status = "running" if run.alive else "stopped"
        elif queued:
            run.status = "queued"
        return True

    def _glob_match(self, name):
        import fnmatch
        return fnmatch.fnmatch(name, self.cfg.queue_glob)

    def _planned_steps(self, run):
        tcl = (run.dir / (run.top + ".tcl")) if run.top else None
        if tcl and tcl.is_file():
            mtime = tcl.stat().st_mtime
            hit = self._tcl_cache.get(str(tcl))
            if not hit or hit[0] != mtime:
                try:
                    hit = (mtime, self.cfg.tcl_start_step_re.findall(tcl.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    hit = (mtime, [])
                self._tcl_cache[str(tcl)] = hit
            if hit[1]:
                # a launch continuing from a later step (`launch_runs impl_1 -from_step ...`) rewrites the script
                # with only the steps it runs; the earlier steps it builds on left their markers in the run dir
                done_before = [s for s in self._marker_steps(run) if s not in hit[1]]
                return sorted(dict.fromkeys(hit[1] + done_before), key=self._step_rank)
        return self._marker_steps(run)

    def _marker_steps(self, run):
        return [s for s in self.cfg.step_order if s in run.markers and self.cfg.steps[s].flow == "impl"]

    def _step_rank(self, step_id):
        return self.cfg.step_order.index(step_id) if step_id in self.cfg.step_order else len(self.cfg.step_order)

    # ---- reports
    def _run_reports(self, run, begins=None):
        by_step = {}
        if not run.top:
            return by_step
        prefix = run.top + "_"
        for name, entry in run.entries.items():
            if not (name.endswith(".rpt") and name.startswith(prefix)):
                continue
            tail = name[len(prefix):]
            for rtype in self.cfg.report_types:
                if not rtype.regex.search(tail):
                    continue
                parsed = self.reports.parse(entry.path, rtype.parser)
                if parsed is None:
                    break
                step = rtype.step
                begin = (begins or {}).get(step) or run.markers.get(step, {}).get("begin") or run.begin
                mtime = entry.stat().st_mtime
                stale = begin is not None and mtime < begin - 1
                self.report_paths.add(entry.path)
                by_step.setdefault(step, []).append({
                    "name": name, "label": rtype.label, "kind": rtype.kind, "path": entry.path, "mtime": mtime,
                    "stale": stale, "summary": parsed[0], "alerts": [] if stale else parsed[1],
                    "doc_url": self.docs.report(rtype.kind)})
                break
        return by_step

    # ---- nodes
    def _synth_run_node(self, run, now):
        plog = self._log(run.log_path) if run.log_path else None
        node = Node(id=run.id, label=run.id, kind="run", run=run.id, status=run.status)
        node.started_at, node.ended_at = run.begin, run.end
        open_status = {"running": "running", "stopped": "stopped", "failed": "failed"}.get(run.status, "done")
        sections = []
        if plog is not None:
            sections = [c for c in plog.parser.root.children if c.kind == "step"]
            node.log = plog.path
            node.line_start, node.line_end = 1, plog.line_count
            node.counts = plog.parser.root.rolled_counts()
            self._register(node, plog, 1, plog.line_count, run.status == "running")
            if len(sections) == 1:
                node.children = [self._convert(c, run.id, plog, open_status) for c in sections[0].children]
            else:
                node.children = [self._convert(c, run.id, plog, open_status) for c in plog.parser.root.children]
            if sections:
                node.peak_mem_mb = max((s.peak_mem or 0) for s in sections) or None
                node.timing = self._timing_from_history(sections[-1], "synth_design", run.status)
        if run.begin is not None and run.status == "running":
            node.elapsed_s = max(0.0, now - run.begin)
        elif run.begin is not None and run.end is not None:
            node.elapsed_s = max(0.0, run.end - run.begin)
        node.reports = self._run_reports(run).get("synth_design", [])
        if run.status == "failed":
            section = sections[-1] if sections else None
            node.failure = self._failure_for([str(run.dir / "runme.log"), run.log_path], run.dir, run.begin,
                                             section, plog)
        quiet = run.status in ("done", "failed", "stopped") or (
            plog is not None and self.catalog.is_cached_ip("synth_design", plog.parser.messages, self.version))
        node.children = self.catalog.merge("synth_design", node, run.status, self.version, annotate_only=quiet)
        stall = plog.growth_age(now) if plog else None
        node.alerts = alert_rules.node_alerts(node, "synth_design", self.cfg, stall, run.alive)
        return node

    def _group_node(self, node_id, label, children, live, now):
        node = Node(id=node_id, label=label, kind="group")
        node.children = children
        node.status = _aggregate_status([c.status for c in children], live)
        for child in children:
            for i, value in enumerate(child.counts):
                node.counts[i] += value
        starts = [c.started_at for c in children if c.started_at]
        ends = [c.ended_at for c in children if c.ended_at]
        node.started_at = min(starts) if starts else None
        if node.status == "done" and ends:
            node.ended_at = max(ends)
        if node.started_at:
            node.elapsed_s = max(0.0, (node.ended_at or now) - node.started_at) if node.status in (
                "done", "running") else None
        node.progress = {"done": sum(1 for c in children if c.status == "done"), "total": len(children)}
        self._register_group(node)
        return node

    # ---- relaunch / resume bookkeeping
    @staticmethod
    def _check_relaunch(run, state):
        """True when the run was launched again in project mode (markers rewritten or main log replaced)."""
        sig = {"begin": run.begin, "log": run.log_path, "ino": None, "size": None}
        if run.log_path:
            try:
                st = os.stat(run.log_path)
                sig["ino"], sig["size"] = file_identity(st), st.st_size
            except OSError:
                pass
        prev, state["sig"] = state.get("sig"), sig
        if not prev:
            return False
        new_begin = run.begin and prev.get("begin") and run.begin > prev["begin"] + 1
        replaced = (prev.get("log") == sig["log"] and prev.get("ino") is not None and sig["ino"] is not None
                    and (sig["ino"] != prev["ino"] or sig["size"] < prev["size"]))
        if not (new_begin or replaced):
            return False
        if state["last"] or state["sessions"]:
            for sid, attempts in state["last"].items():
                for att in attempts:
                    if att["status"] in ("running", "queued"):
                        att["status"] = "stopped"
                        att["summary"] = "stopped"
                state["archive"].setdefault(sid, []).extend(attempts)
            state["launches"] += 1
        state["last"], state["sessions"] = {}, []
        return True

    def _sessions(self, run, state, resumes, now):
        """Resume sessions of this run (persisted + live), oldest first, with alive/resumed_from filled in."""
        rc = self.cfg.resume
        live_logs = {}
        for item in resumes:
            if item["log"]:
                live_logs[item["log"]] = item
                known = next((x for x in state["sessions"] if x["log"] == item["log"]), None)
                if known is None:
                    known = {"log": item["log"], "first_seen": now}
                    state["sessions"].append(known)
                known.update({"checkpoint": item["checkpoint"] or known.get("checkpoint"),
                              "script": item["script"], "cwd": item["cwd"]})
        # a session whose log is gone stays as long as it has a persisted summary to show; one logged in a .Xil
        # scratch dir was a helper (debug cores) that older versions took for a resume, never a real attempt
        state["sessions"] = [x for x in state["sessions"]
                             if (os.path.isfile(x["log"]) or x.get("steps")) and not in_scratch(x["log"])]
        out = []
        for sess in state["sessions"]:
            info = dict(sess)
            info["alive"] = sess["log"] in live_logs
            info["pid"] = live_logs[sess["log"]]["pid"] if info["alive"] else None
            info["log_missing"] = not os.path.isfile(sess["log"])
            scanned = scan_session(sess["log"], sess.get("cwd"), self.cfg)
            info["checkpoint"] = scanned["checkpoint"] or sess.get("checkpoint")
            info["started_at"] = scanned["started_at"] or sess.get("started_at") or sess["first_seen"]
            if not info["log_missing"]:
                sess["checkpoint"], sess["started_at"] = info["checkpoint"], info["started_at"]
            info["resumed_from"] = rc.step_for_checkpoint(info["checkpoint"]) if info["checkpoint"] else None
            out.append(info)
        return out

    def _script_steps(self, script):
        """Step ids a resume script will run, in order (read-only peek at the script)."""
        if not script:
            return []
        try:
            text = Path(script).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            word = line.strip().split(" ", 1)[0]
            if word in self.cfg.step_commands:
                out.extend(s.id for s in self.cfg.steps_for_command(word))
        return out

    def _session_nodes(self, run, sess, step_ids, now):
        """{step id: Node} for the steps this resume session ran (or is about to run)."""
        if sess.get("log_missing"):
            return self._summary_nodes(run, sess, step_ids, now)
        plog = self._log(sess["log"])
        sections = [c for c in plog.parser.root.children if c.kind == "step"]
        resumed = sess["resumed_from"]
        if resumed in step_ids:
            after = [s for s in step_ids if self.cfg.step_order.index(s) > self.cfg.step_order.index(resumed)]
        else:
            after = list(step_ids)
        assigned = assign_sections(after, sections, self.cfg)
        extras = extra_sections(assigned, sections)
        alive, started = sess["alive"], sess["started_at"]
        begins = {sid: (sec.started_at or started) for sid, sec in assigned.items()}
        reports = self._run_reports(run, {sid: started for sid in assigned})
        nodes = {}
        last_sid = max(assigned, key=lambda sid: assigned[sid].line_start) if assigned else None
        for sid, section in assigned.items():
            status = section.status
            if status == "running" and sid == last_sid and not alive:
                status = "stopped"
            elif status == "running" and sid != last_sid:
                status = "done"
            elif status == "done" and sid == last_sid and alive:
                status = "running"     # the session is still busy after it (checkpoints, reports, a script's own work)
            failure = None
            if status in ("stopped", "failed"):
                found = failure_mod.detect([sess["log"]], self.cfg)
                if found or status == "failed":
                    failure = found or self._failure_for([sess["log"]], None, None, section, plog)
                    status = "failed"
            open_status = {"running": "running", "stopped": "stopped", "failed": "failed"}.get(status, "done")
            end = None
            if status != "running" and sid == last_sid:
                end = plog.tail.last_growth
            node = self._step_node(sid, "%s/%s" % (run.id, sid), plog, section, status, open_status, alive,
                                   run.id, begins[sid], end, reports.get(sid, ()), now, failure, extras.get(sid, ()))
            nodes[sid] = node
        if alive and not assigned:
            # still loading the checkpoint: the next planned step is the one it will run
            seen = set(assigned)
            todo = [s for s in self._script_steps(sess.get("script")) if s in after and s not in seen]
            sid = todo[0] if todo else next((s for s in after if s not in seen), None)
            if sid and not assigned.get(sid):
                nodes[sid] = self._step_node(sid, "%s/%s" % (run.id, sid), plog, None, "running", "running",
                                             True, run.id, started, None, (), now)
        return nodes

    def _summary_nodes(self, run, sess, step_ids, now):
        """Nodes rebuilt from the persisted per-step summary of a session whose log no longer exists."""
        steps = {sid: att for sid, att in (sess.get("steps") or {}).items() if sid in self.cfg.steps}
        reports = self._run_reports(run, {sid: sess["started_at"] for sid in steps})
        nodes = {}
        for sid, att in steps.items():
            status = att["status"]
            if status in ("running", "queued"):
                status = "running" if sess["alive"] else "stopped"
            node = self._step_node(sid, "%s/%s" % (run.id, sid), None, None, status, status, sess["alive"],
                                   run.id, att.get("started_at"), att.get("ended_at"), reports.get(sid, ()),
                                   now, att.get("failure"))
            self._restore_summary(node, att)
            nodes[sid] = node
        return nodes

    @staticmethod
    def _restore_summary(node, att):
        """Counts, elapsed time and timing of a node that has no log to read them from."""
        node.log_missing = True
        node.log = att.get("log")
        node.elapsed_s = att.get("elapsed_s", node.elapsed_s)
        counts = att.get("counts")
        if counts:
            node.counts = [counts["info"], counts["warning"], counts["critical"], counts["error"]]
        timing = att.get("timing")
        if timing and (node.timing is None or node.timing.source != "report"):
            node.timing = Timing(wns=timing["wns"], tns=timing["tns"], whs=timing["whs"], ths=timing["ths"],
                                 met=timing["met"], source="summary", label="Saved summary",
                                 final=timing.get("final", False), stage=timing.get("stage", ""))

    def _external_nodes(self, run, nodes, current, step_ids, now):
        """Attempt inferred from run-dir files newer than the failure, when nothing else explains them.

        Returns (nodes by step, resumed_from) or None."""
        failed = [sid for sid in step_ids if nodes[sid].status == "failed"
                  and current.get(sid) and current[sid][-1]["mode"] == "project"]
        if not failed or not run.top:
            return None
        first_failed = failed[0]
        marker = run.markers.get(first_failed, {})
        fail_time = max(t for t in (marker.get("error"), run.markers.get("vivado", {}).get("error"),
                                    nodes[first_failed].ended_at, marker.get("begin")) if t is not None)
        proven, before = artifacts_mod.scan(run.entries, run.top, fail_time, self.cfg)
        start = step_ids.index(first_failed)
        candidates = [s for s in step_ids[start:] if nodes[s].status != "done"]
        proven = {s: v for s, v in proven.items() if s in candidates}
        if not proven:
            return None
        last = max(proven, key=lambda s: step_ids.index(s))
        chain = [s for s in candidates if step_ids.index(s) <= step_ids.index(last)]
        earliest = min(v["first"] for v in proven.values())
        reports = self._run_reports(run, {sid: fail_time for sid in chain})
        out, begin = {}, earliest
        for sid in chain:
            end = proven[sid]["last"] if sid in proven else begin
            end = max(end, begin)
            node = self._step_node(sid, "%s/%s" % (run.id, sid), None, None, "done", "done", False, run.id,
                                   begin, end, reports.get(sid, ()), now)
            out[sid] = node
            begin = end
        return out, before

    def _impl_steps(self, run, now, live, resumes=(), last_impl=False):
        sections = []
        plog = self._log(run.log_path) if run.log_path else None
        if plog is not None:
            sections = [c for c in plog.parser.root.children if c.kind == "step"]
        planned = self._planned_steps(run)
        assigned = assign_sections(planned, sections, self.cfg)
        extras = extra_sections(assigned, sections)
        step_ids = planned or sorted(
            set(assigned) | {s for s in run.markers if s in self.cfg.steps and s != "vivado"},
            key=self.cfg.step_order.index)
        reports = self._run_reports(run)
        state = self.store.run(run.id)
        self._check_relaunch(run, state)
        fail_logs = [str(run.dir / "runme.log"), run.log_path]
        nodes = {}
        began_after = {}
        seen_begin = False
        for sid in reversed(step_ids):
            began_after[sid] = seen_begin
            seen_begin = seen_begin or "begin" in run.markers.get(sid, {})
        for sid in step_ids:
            marker = run.markers.get(sid, {})
            failure = None
            if "error" in marker:
                status = "failed"
            elif "end" in marker:
                status = "done"
            elif "begin" in marker:
                alive = run.alive or pid_alive(marker.get("pid"))
                status = "running" if alive else ("done" if run.status == "done" else
                                                  "failed" if run.status == "failed" else "stopped")
                if status == "stopped" and failure_mod.detect(fail_logs, self.cfg, run.dir, marker["begin"]):
                    status = "failed"
            elif run.status == "done" or began_after.get(sid):
                status = "skipped"
            else:
                status = "queued" if run.status == "queued" else "pending"
            if status == "failed":
                failure = self._failure_for(fail_logs, run.dir, marker.get("begin") or run.begin,
                                            assigned.get(sid), plog)
            open_status = {"running": "running", "stopped": "stopped", "failed": "failed"}.get(status, "done")
            end = marker.get("end") or marker.get("error") or (
                run.markers.get("vivado", {}).get("error") if status == "failed" else None)
            nodes[sid] = self._step_node(
                sid, "%s/%s" % (run.id, sid), plog, assigned.get(sid), status, open_status, run.alive,
                run.id, marker.get("begin"), end, reports.get(sid, ()), now, failure, extras.get(sid, ()))

        # attempts: main launch first, then every resume session replaces the steps it ran
        main_n = 1 + state["launches"]
        current = {}
        for sid, node in nodes.items():
            if node.status not in ("pending", "queued", "skipped"):
                current[sid] = [self._attempt_summary(node, main_n, "project", None, plog.path if plog else None)]
        sessions = self._sessions(run, state, resumes, now)
        effective = []
        for sess in sessions:
            sess_nodes = self._session_nodes(run, sess, step_ids, now)
            if not sess_nodes:
                continue
            effective.append(sess)
            n = main_n + len(effective)
            rec = next(x for x in state["sessions"] if x["log"] == sess["log"])
            steps = rec.setdefault("steps", {}) if not sess["log_missing"] else rec["steps"]
            for sid, node in sess_nodes.items():
                nodes[sid] = node
                att = self._attempt_summary(node, n, "resume", sess["checkpoint"], sess["log"])
                if sess["log_missing"]:
                    att.update(log_missing=True, summary="log no longer available")
                else:
                    steps[sid] = dict(att)
                current.setdefault(sid, []).append(att)
            if not sess["log_missing"]:
                rec["alive"] = sess["alive"]
                rec["final_status"] = None if sess["alive"] else self._derive_status(
                    [n.status for n in sess_nodes.values()], False, "stopped")
            if sess["log"] in self.logs:
                self._extra_parsers.append(self.logs[sess["log"]])
        external = None
        if not any(s["alive"] for s in effective):
            external = self._external_nodes(run, nodes, current, step_ids, now)
        if external:
            ext_nodes, ext_before = external
            n = main_n + len(effective) + 1
            for sid, node in ext_nodes.items():
                nodes[sid] = node
                att = self._attempt_summary(node, n, "external", None, None)
                att.update(approx_times=True, summary="outside project flow (inferred from files)")
                current.setdefault(sid, []).append(att)
        archive = state["archive"]
        for sid, node in nodes.items():
            allatt = archive.get(sid, []) + current.get(sid, [])
            if len(allatt) >= 2 or (allatt and node.status in ("pending", "queued", "skipped")):
                node.attempts = allatt
        state["last"] = current

        run_n = main_n + len(effective) + (1 if external else 0)
        latest = effective[-1] if effective else None
        previous = None
        for sid in nodes:
            for att in archive.get(sid, []) + current.get(sid, []):
                if att["failure"] and att["n"] < run_n and (previous is None or att["n"] > previous[0]):
                    previous = (att["n"], att["failure"]["reason"])
        self._attempt_info[run.id] = {
            "n": run_n, "mode": "resume" if latest else "project",
            "resumed_from": latest["resumed_from"] if latest else None,
            "previous_failure": previous[1] if previous else None}
        if external:
            self._attempt_info[run.id].update(mode="external", resumed_from=ext_before)
            final = step_ids[-1] in external[0]
            run.status = "done" if final and all(n.status == "done" for n in nodes.values()) else "stopped"
        elif effective:
            run.status = self._derive_status([n.status for n in nodes.values()],
                                             any(s["alive"] for s in effective), run.status)
        return [nodes[sid] for sid in step_ids] + [nodes[sid] for sid in nodes if sid not in step_ids]

    @staticmethod
    def _derive_status(statuses, session_alive, fallback):
        """Run status once resume sessions took over: the latest attempt of each step decides."""
        for state in ("running", "failed", "stopped"):
            if state in statuses:
                return state
        if session_alive:
            return "running"
        return "done" if "done" in statuses else fallback

    def snapshot(self, group, now=None):
        now = now or time.time()
        self.index = {}
        self.report_paths = set()
        runs, launch_time = self._launch_runs()
        runs = [r for r in runs if self._inspect(r, group)]
        synth_runs = [r for r in runs if r.kind in ("synth", "ooc")]
        impl_runs = [r for r in runs if r.kind == "impl"]
        live = bool(group and group.pids)
        parsers = []

        synth_stage = None
        if synth_runs:
            ooc = [self._synth_run_node(r, now) for r in synth_runs if r.kind == "ooc"]
            top = [self._synth_run_node(r, now) for r in synth_runs if r.kind == "synth"]
            limit = self.cfg.layout["ooc_collapse_children_above"]
            if len(ooc) > limit:
                for node in ooc:
                    if node.status == "done" and not node.alerts:
                        node.children = []
            children = []
            if ooc:
                children.append(self._group_node("synth/ooc", self.cfg.layout["ooc_group_label"].format(n=len(ooc)),
                                                 ooc, live, now))
                children[-1].parallel = True
            children.extend(top)
            synth_stage = self._group_node("synth", self.cfg.layout["synth_stage_label"], children, live, now)
            synth_stage.alerts = []
            parsers.extend(p for r in synth_runs if r.log_path and (p := self.logs.get(r.log_path)))

        self._impl_ctx = (impl_runs[-1] if impl_runs else None,
                          next((r for r in reversed(synth_runs) if r.kind == "synth"), None))
        flows = []
        self._extra_parsers = []
        self._attempt_info = {}
        for run in impl_runs:
            stages = [synth_stage] if synth_stage else []
            own = [r for r in (group.resumes if group else ())
                   if r["run"] == run.id or (r["run"] is None and run is impl_runs[-1])]
            stages.extend(self._impl_steps(run, now, live, own))
            flows.append(Flow(id=run.id, label=run.id, stages=stages))
            if run.log_path and run.log_path in self.logs:
                parsers.append(self.logs[run.log_path])
        if not impl_runs and synth_stage:
            flows.append(Flow(id="synth", label="synthesis", stages=[synth_stage]))
        parsers.extend(p for p in self._extra_parsers if p not in parsers)

        fw = Firmware(id=self.id, name=self.name, kind="project", path=self.path)
        run_states = [r.status for r in runs] or ["pending"]
        fw.status = self._fw_status(run_states, live, runs)
        begins = [r.begin for r in runs if r.begin]
        fw.started_at = min(begins) if begins else launch_time
        activity = [p.tail.last_growth for p in parsers if p.tail.last_growth]
        activity += [r.end for r in runs if r.end] + begins
        # resumed/external attempts end after the run's own markers
        activity += [s.ended_at for f in flows for s in f.stages if s.ended_at]
        fw.updated_at = max(activity) if activity else launch_time
        if fw.started_at:
            ended = fw.updated_at if fw.status in ("done", "failed", "stopped") else now
            fw.elapsed_s = max(0.0, ended - fw.started_at)
        infos = [self._attempt_info[r.id] for r in impl_runs if r.id in self._attempt_info]
        fw.attempt = max(infos, key=lambda i: i["n"]) if infos else {
            "n": 1, "mode": "project", "resumed_from": None, "previous_failure": None}
        self._finish(fw, flows, parsers, group, live, now)
        self.store.save()
        return fw

    @staticmethod
    def _fw_status(statuses, live, runs):
        if "running" in statuses:
            return "running"
        for state in ("failed", "stopped"):
            if state in statuses:
                return state
        if all(s == "done" for s in statuses):
            return "done"
        if "done" in statuses:
            return "running" if live else "stopped"
        if "queued" in statuses:
            return "queued"
        return "running" if live and runs and any(r.begin for r in runs) else "idle"


# ====================================================================== standalone log mode
class LogSource(Source):
    kind = "log"

    def __init__(self, log_path, config, report_cache, catalog, attempt_dir=None):
        super().__init__(log_path, config, report_cache, catalog, attempt_dir)
        self.name = Path(log_path).stem

    def snapshot(self, group, now=None):
        now = now or time.time()
        self.index = {}
        self.report_paths = set()
        plog = self._log(self.path)
        live = bool(group and group.pids) or (plog.growth_age(now) or 1e9) < RECENT_GROWTH_S
        sections = [c for c in plog.parser.root.children if c.kind == "step"]
        assigned = assign_sections([], sections, self.cfg)
        extras = extra_sections(assigned, sections)
        order = [s for s in self.cfg.step_order if s in assigned]
        stages = []
        for sid in order:
            section = assigned[sid]
            status = section.status
            open_status = "running" if live else "stopped"
            failure = None
            if section.status == "running" and not live:
                status = "stopped"
                found = failure_mod.detect([self.path], self.cfg)
                if found:
                    status, open_status, failure = "failed", "failed", found
            elif status == "failed":
                open_status = "failed"
                failure = self._failure_for([self.path], None, None, section, plog)
            stages.append(self._step_node(sid, "log/" + sid, plog, section, status, open_status, live,
                                          None, None, None, (), now, failure, extras.get(sid, ())))
        if live and order:
            flow_kind = self.cfg.steps[order[-1]].flow
            last = self.cfg.step_order.index(order[-1])
            for sid in self.cfg.step_order[last + 1:]:
                if self.cfg.steps[sid].flow == flow_kind:
                    stages.append(self._step_node(sid, "log/" + sid, plog, None, "pending", "done", live,
                                                  None, None, None, (), now))
        fw = Firmware(id=self.id, name=self.name, kind="log", path=self.path)
        statuses = [s.status for s in stages if s.status != "pending"]
        if live:
            fw.status = "running"
        elif "failed" in statuses:
            fw.status = "failed"
        elif "stopped" in statuses:
            fw.status = "stopped"
        elif statuses:
            fw.status = "done"
        else:
            fw.status = "idle"
        fw.started_at = None
        fw.attempt = {"n": 1, "mode": "project", "resumed_from": None, "previous_failure": None}
        fw.updated_at = plog.tail.last_growth
        self._finish(fw, [Flow(id="log", label=Path(self.path).name, stages=stages)], [plog], group, live, now)
        return fw


def fmt_duration(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%dh%02dm" % (hours, minutes)
    return "%dm%02ds" % (minutes, secs) if minutes else "%ds" % secs


def _deepest_failed(node):
    """Deepest failed (non-expected) descendant of a step node, or None."""
    for child in node.children:
        if child.status == "failed" and not child.expected:
            return _deepest_failed(child) or child
    return None


def _has_logic(report):
    """False for a top-level synth report where every IP is an out-of-context black box (all logic 0)."""
    rows = report["summary"].get("rows", ())
    logic = [r for r in rows if r["name"] in ("LUT", "FF")]
    return not logic or any(r["used"] for r in logic)
