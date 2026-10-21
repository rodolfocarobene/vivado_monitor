"""Build history: one record per finished build in ~/.cache/vmon/history/<fw_id>.json (read-only on build dirs).

Report files are overwritten by every Vivado run, so an artifact only belongs to a recorded build while its
current (mtime, size) still equal what was recorded; `current` is computed on read, never stored.
"""
import json
import os
import re
from pathlib import Path

from .eta import phase_durations, step_durations

DEFAULTS = {"max_builds": 100, "bitstream": True, "max_messages": 500,
            "kinds": ["timing_summary", "utilization", "drc", "methodology", "power", "route_status"]}
FINISHED = ("done", "failed", "stopped")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
UTIL_ROWS = ("LUT", "FF", "BRAM", "URAM", "DSP", "IO")
BUILD_LIMIT_MAX = 1000
HEAVY = ("messages", "phases", "timing_clocks")     # kept out of the list payload; GET /api/history/build has them
MESSAGE_SEVERITIES = ("error", "critical", "warning")          # worst first; info is never recorded
SEVERITY_RANK = {s: len(MESSAGE_SEVERITIES) - i for i, s in enumerate(MESSAGE_SEVERITIES)}
TEXT_MAX = 160
COMPARE_LIST_MAX = 200


def settings(cfg):
    return {**DEFAULTS, **(cfg.data.get("history") or {})}


def classify(status, timing):
    """'met' | 'timing_not_met' | 'failed' | 'stopped' | 'done' (finished without a final timing result)."""
    if status in ("failed", "stopped"):
        return status
    if timing and timing.final and timing.met is not None:
        return "met" if timing.met else "timing_not_met"
    return "done"


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def failure_of(fw):
    """{"step", "reason"} of the first failed step/run in the last flow, or a note for a vanished process."""
    for node in _walk(fw.flows[-1].stages if fw.flows else ()):
        if node.kind in ("step", "run") and node.failure:
            return {"step": node.label, "reason": node.failure.get("reason")}
    if fw.status == "failed":
        return {"step": None, "reason": "Build failed"}
    return {"step": None, "reason": "Vivado process gone"} if fw.status == "stopped" else None


def _stat(path):
    try:
        st = os.stat(path)
        return st.st_mtime, st.st_size
    except OSError:
        return None


def _artifact(kind, label, path, step=None):
    stat = _stat(path)
    if stat is None:
        return None
    return {"kind": kind, "label": label, "step": step, "path": str(path), "mtime": stat[0], "size": stat[1]}


def artifacts_of(fw, hcfg):
    """Reports of the last flow (non-stale, wanted kinds) plus the bitstream written by this build."""
    out, seen = [], set()
    kinds = set(hcfg["kinds"] or ())
    for node in _walk(fw.flows[-1].stages if fw.flows else ()):
        if node.id == "synth/ooc":
            continue
        for report in node.reports:
            if report["stale"] or report["path"] in seen or (kinds and report["kind"] not in kinds):
                continue
            seen.add(report["path"])
            art = _artifact(report["kind"], report["label"], report["path"], node.label)
            if art:
                out.append(art)
    top = (fw.info or {}).get("top")
    if hcfg["bitstream"] and fw.kind == "project" and top and fw.flows:
        bit = _artifact("bitstream", "Bitstream", Path(fw.path) / fw.flows[-1].id / (top + ".bit"))
        if bit and bit["mtime"] >= (fw.started_at or 0) - 1:     # an older .bit is not this build's
            out.append(bit)
    return out


def attempts_of(fw):
    """One row per attempt number when the last flow ran more than once (resume/restart), else None."""
    by_n = {}
    for node in _walk(fw.flows[-1].stages if fw.flows else ()):
        for att in node.attempts:
            row = by_n.setdefault(att["n"], {"n": att["n"], "mode": att.get("mode"), "statuses": set(), "detail": None})
            row["statuses"].add(att.get("status"))
            if att.get("status") == "failed" and row["detail"] is None:
                row["detail"] = "%s: %s" % (node.label, att.get("summary") or "failed")
    if len(by_n) < 2:
        return None
    rank = ("failed", "stopped", "running")
    return [{"n": r["n"], "mode": r["mode"], "result": next((s for s in rank if s in r["statuses"]), "done"),
             "detail": r["detail"]} for _, r in sorted(by_n.items())]


def messages_of(groups, cap):
    """{msg_id: {count, severity, text}} of warnings and worse, worst and most frequent first, at most `cap` ids."""
    kept = [g for g in groups or () if g["severity"] in SEVERITY_RANK]
    kept.sort(key=lambda g: (-SEVERITY_RANK[g["severity"]], -g["count"], g["id"]))
    return {g["id"]: {"count": g["count"], "severity": g["severity"], "text": (g.get("text") or "")[:TEXT_MAX]}
            for g in kept[:max(0, int(cap))]}


def build_record(fw, build, hcfg, groups=None, clocks=None):
    """`groups` = raw message groups of the whole firmware, `clocks` = final per-clock timing (clocks.per_clock)."""
    timing = fw.timing
    info = fw.info or {}
    util = {r["name"]: {"used": r["used"], "available": r["available"], "pct": r["pct"]}
            for r in (fw.utilization or {}).get("rows", ()) if r["name"] in UTIL_ROWS}
    c = fw.counts
    return {
        "build": build, "fw_id": fw.id, "firmware": fw.name, "project": fw.path,
        "started_at": fw.started_at, "ended_at": fw.updated_at, "duration_s": fw.elapsed_s,
        "result": classify(fw.status, timing), "failure": failure_of(fw) if fw.status != "done" else None,
        "timing": {k: getattr(timing, k) for k in ("wns", "tns", "whs", "ths", "final")} if timing else None,
        "utilization": util or None,
        "part": info.get("part"), "board": info.get("board"), "vivado_version": fw.vivado_version or info.get("vivado_version"),
        "strategy_synth": info.get("strategy_synth"), "strategy_impl": info.get("strategy_impl"),
        "host": info.get("host"), "directives": info.get("directives") or None, "attempts": attempts_of(fw),
        "counts": [c[3], c[2], c[1], c[0]],            # E, CW, W, I
        "steps": step_durations(fw), "phases": phase_durations(fw),
        "messages": messages_of(groups, hcfg["max_messages"]) if groups is not None else None,
        "timing_clocks": {n: {"wns": v["wns"], "whs": v["whs"]} for n, v in clocks.items()} if clocks else None,
        "artifacts": artifacts_of(fw, hcfg),
    }


def is_current(artifact):
    return _stat(artifact["path"]) == (artifact["mtime"], artifact["size"])


class HistoryStore:
    """{"firmware": {"id", "name"}, "builds": [record]}, oldest first, capped; one record per build key."""

    def __init__(self, directory, cap=DEFAULTS["max_builds"]):
        self.dir = Path(directory)
        self.cap = max(1, int(cap))
        self.version = 0

    def _read(self, fw_id):
        if not ID_RE.match(fw_id or ""):
            return None
        try:
            data = json.loads((self.dir / (fw_id + ".json")).read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get("builds"), list) else None

    def load(self, fw_id):
        data = self._read(fw_id)
        return [b for b in data["builds"] if isinstance(b, dict) and "build" in b] if data else []

    def firmwares(self):
        out = []
        for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else ():
            data = self._read(path.stem)
            fw = (data or {}).get("firmware")
            if data and data["builds"] and isinstance(fw, dict):
                out.append({"id": path.stem, "name": fw.get("name") or path.stem})
        return out

    def record(self, record):
        """Store a build; an existing record with the same key is replaced only when its result changed."""
        fw_id, build = record["fw_id"], record["build"]
        builds = self.load(fw_id)
        same = next((i for i, b in enumerate(builds) if b["build"] == build), None)
        if same is not None and builds[same].get("result") == record["result"]:
            return False
        if same is None:
            builds.append(record)
            builds.sort(key=lambda b: b.get("started_at") or 0)
        else:
            builds[same] = record
        path = self.dir / (fw_id + ".json")
        tmp = path.with_name(path.name + ".tmp")
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"firmware": {"id": fw_id, "name": record["firmware"]},
                                       "builds": builds[-self.cap:]}))
            os.replace(tmp, path)
        except OSError:
            return False
        self.version += 1
        return True

    def listing(self, fw_id=None, limit=100):
        """API payload: builds newest first (artifacts get `current`), plus every firmware with history."""
        ids = [fw_id] if fw_id else [f["id"] for f in self.firmwares()]
        builds = [b for i in ids for b in self.load(i)]
        builds.sort(key=lambda b: b.get("started_at") or 0, reverse=True)
        out = []
        for b in builds[:max(1, min(limit, BUILD_LIMIT_MAX))]:
            light = {k: v for k, v in b.items() if k not in HEAVY}
            out.append({**light, "artifacts": [{**a, "current": is_current(a)} for a in b.get("artifacts", ())]})
        return {"builds": out, "firmwares": self.firmwares()}

    def build(self, fw_id, build):
        """The full record of one build (artifacts get `current`), or None."""
        record = next((b for b in self.load(fw_id) if b["build"] == build), None)
        if record is None:
            return None
        return {**record, "artifacts": [{**a, "current": is_current(a)} for a in record.get("artifacts", ())]}

    def compare(self, fw_id, a, b):
        """(diff, None) of two builds of one firmware, else (None, (status, why))."""
        if a == b:
            return None, (400, "pick two different builds")
        old, new = self.build(fw_id, a), self.build(fw_id, b)
        if old is None or new is None:
            return None, (404, "no such build in the history")
        return compare_records(old, new), None

    def artifact(self, fw_id, build, path):
        """(artifact, None) when `path` is a recorded artifact of that build and still current, else (None, (status, why))."""
        record = next((b for b in self.load(fw_id) if b["build"] == build), None)
        if record is None:
            return None, (404, "no such build in the history")
        art = next((a for a in record.get("artifacts", ()) if a["path"] == path), None)
        if art is None:
            return None, (404, "not an artifact of this build")
        if not is_current(art):
            return None, (410, "replaced by a later build (the file changed since this build finished)")
        return art, None


def _pair(a, b, digits=3):
    delta = round(b - a, digits) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
    return {"a": a, "b": b, "delta": delta}


def _header(r):
    keys = ("build", "started_at", "ended_at", "duration_s", "result", "part", "strategy_impl", "vivado_version", "counts")
    return {k: r.get(k) for k in keys}


def _timing_diff(a, b):
    ta, tb = a.get("timing") or {}, b.get("timing") or {}
    metrics = {k: _pair(ta.get(k), tb.get(k)) for k in ("wns", "tns", "whs", "ths")}
    ca, cb = a.get("timing_clocks"), b.get("timing_clocks")
    clocks = None
    if ca and cb:
        clocks = [{"name": n, **{k: _pair((ca.get(n) or {}).get(k), (cb.get(n) or {}).get(k)) for k in ("wns", "whs")}}
                  for n in {**ca, **cb}]
        clocks.sort(key=lambda c: (c["wns"]["b"] is None, c["wns"]["b"] if c["wns"]["b"] is not None else 0, c["name"]))
    return {"final": {"a": bool(ta.get("final")), "b": bool(tb.get("final"))}, "metrics": metrics, "clocks": clocks}


def _util_diff(a, b):
    ua, ub = a.get("utilization") or {}, b.get("utilization") or {}
    return {k: {"pct": _pair((ua.get(k) or {}).get("pct"), (ub.get(k) or {}).get("pct"), 1),
                "used": _pair((ua.get(k) or {}).get("used"), (ub.get(k) or {}).get("used"), 0),
                "available": (ub.get(k) or ua.get(k) or {}).get("available")}
            for k in UTIL_ROWS if k in ua or k in ub}


def _steps_diff(a, b):
    sa, sb = a.get("steps") or {}, b.get("steps") or {}
    return [{"step": s, **_pair(sa.get(s), sb.get(s), 1)} for s in [*sa, *(s for s in sb if s not in sa)]]


def _messages_diff(a, b):
    ma, mb = a.get("messages"), b.get("messages")
    ca, cb = a.get("counts") or [None] * 4, b.get("counts") or [None] * 4
    totals = {sev: _pair(ca[i], cb[i], 0) for i, sev in enumerate(("error", "critical", "warning", "info"))}
    out = {"totals": totals, "available": {"a": ma is not None, "b": mb is not None},
           "new": [], "removed": [], "changed": [], "counts": {"new": 0, "removed": 0, "changed": 0}}
    if ma is None or mb is None:
        return out

    def entry(i, ra, rb):
        src = rb or ra
        return {"id": i, "severity": src["severity"], "text": src.get("text") or "", **_pair(
            ra["count"] if ra else None, rb["count"] if rb else None, 0)}
    rows = {"new": [entry(i, None, r) for i, r in mb.items() if i not in ma],
            "removed": [entry(i, r, None) for i, r in ma.items() if i not in mb],
            "changed": [entry(i, ma[i], r) for i, r in mb.items() if i in ma and ma[i]["count"] != r["count"]]}
    for kind, items in rows.items():
        if kind == "changed":
            items.sort(key=lambda e: (-abs(e["delta"]), e["id"]))
        else:
            items.sort(key=lambda e: (-SEVERITY_RANK.get(e["severity"], 0), -(e["b"] if kind == "new" else e["a"]), e["id"]))
        out["counts"][kind] = len(items)
        out[kind] = items[:COMPARE_LIST_MAX]
    return out


def compare_records(a, b):
    """Structured diff of two records of one firmware; `a` is the base (older), `b` the newer build."""
    return {"fw_id": b.get("fw_id"), "firmware": b.get("firmware"), "a": _header(a), "b": _header(b),
            "duration": _pair(a.get("duration_s"), b.get("duration_s"), 1),
            "timing": _timing_diff(a, b), "utilization": _util_diff(a, b), "steps": _steps_diff(a, b),
            "messages": _messages_diff(a, b)}
