"""Build history: one record per finished build in ~/.cache/vmon/history/<fw_id>.json (read-only on build dirs).

Report files are overwritten by every Vivado run, so an artifact only belongs to a recorded build while its
current (mtime, size) still equal what was recorded; `current` is computed on read, never stored.
"""
import json
import os
import re
from pathlib import Path

DEFAULTS = {"max_builds": 100, "bitstream": True,
            "kinds": ["timing_summary", "utilization", "drc", "methodology", "power", "route_status"]}
FINISHED = ("done", "failed", "stopped")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
UTIL_ROWS = ("LUT", "FF", "BRAM", "URAM", "DSP", "IO")
BUILD_LIMIT_MAX = 1000


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


def build_record(fw, build, hcfg):
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
        "counts": [c[3], c[2], c[1], c[0]],            # E, CW, W, I
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
            out.append({**b, "artifacts": [{**a, "current": is_current(a)} for a in b.get("artifacts", ())]})
        return {"builds": out, "firmwares": self.firmwares()}

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
