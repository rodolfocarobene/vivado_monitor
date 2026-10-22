"""Per-clock timing history: per report stage within a build, and across builds.

Per-clock numbers come only from timing_summary reports (Intra Clock Table). Finished builds
are stored in <cache dir>/timing/<fw_id>.json (last KEEP builds, keyed by build start time).
"""
import json
import re
import time
from pathlib import Path

from .paths import write_atomic

KEEP = 20
MAX_CLOCKS = 30
_STAGE = re.compile(r"timing_summary_(\w+?)\.rpt$")


def per_clock(clocks):
    """Report summary clocks -> {name: {wns, tns, whs, ths, failing}} (worst WNS first, capped)."""
    out = {}
    for clock in clocks or ():
        if clock.get("wns") is None:
            continue
        failing = (clock.get("tns_fail") or 0) + (clock.get("ths_fail") or 0)
        out[clock["name"]] = {"wns": clock.get("wns"), "tns": clock.get("tns"), "whs": clock.get("whs"),
                              "ths": clock.get("ths"), "failing": failing}
        if len(out) >= MAX_CLOCKS:
            break
    return out


def stages_of(fw, cfg):
    """[{step, label, per_clock}] for each fresh timing_summary report of the last flow, in flow order."""
    if not fw.flows:
        return []
    out = []

    def walk(node):
        if node.kind in ("step", "run"):
            reports = [r for r in node.reports if r["kind"] == "timing_summary" and not r["stale"]
                       and r["summary"].get("clocks")]
            for report in sorted(reports, key=lambda r: r["mtime"]):
                match = _STAGE.search(report["name"])
                step = cfg.steps.get(node.id.rsplit("/", 1)[-1])
                label = (step.label if step else node.label).replace(" Design", "")
                if match:
                    label = "%s · %s" % (label, match.group(1).replace("_", " "))
                clocks = per_clock(report["summary"]["clocks"])
                if clocks:
                    out.append({"step": node.id, "label": label, "per_clock": clocks})
        for child in node.children:
            walk(child)

    for stage in fw.flows[-1].stages:
        walk(stage)
    return out


class ClockStore:
    """<cache dir>/timing/<fw_id>.json = {"builds": [{"started_at", "label", "per_clock"}]} (oldest first)."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.version = 0

    def load(self, fw_id):
        try:
            data = json.loads((self.dir / (fw_id + ".json")).read_text())
        except (OSError, ValueError):
            return []
        builds = data.get("builds") if isinstance(data, dict) else None
        return [b for b in builds if isinstance(b, dict) and "per_clock" in b] if isinstance(builds, list) else []

    def record(self, fw_id, started_at, clocks):
        """Store (or refresh) the final per-clock values of the build that started at `started_at`."""
        if not clocks or started_at is None:
            return False
        key = int(started_at)
        builds = self.load(fw_id)
        entry = {"started_at": key, "label": time.strftime("%Y-%m-%d %H:%M", time.localtime(key)),
                 "per_clock": clocks}
        for index, old in enumerate(builds):
            if old.get("started_at") == key:
                if old.get("per_clock") == clocks:
                    return False
                builds[index] = entry
                break
        else:
            builds.append(entry)
            builds.sort(key=lambda b: b.get("started_at") or 0)
        try:
            write_atomic(self.dir / (fw_id + ".json"), json.dumps({"builds": builds[-KEEP:]}))
        except OSError:
            return False
        self.version += 1
        return True


def final_stage(fw, stages, cfg):
    """The stage that counts as the build's final per-clock result, or None (build not finished)."""
    if not stages:
        return None
    last = stages[-1]
    if fw.status == "done":
        return last
    final_steps = cfg.alerts.get("timing_final_steps", ())
    if fw.status in ("failed", "stopped") and last["step"].rsplit("/", 1)[-1] in final_steps:
        return last
    return None


def history(fw, store, cfg):
    """Firmware.clock_history (see SPEC v6) or None when there is nothing to show."""
    stages = stages_of(fw, cfg)
    builds = store.load(fw.id)
    key = int(fw.started_at) if fw.started_at else None
    stored = {b.get("started_at") for b in builds}
    if stages and key is not None and key not in stored:
        builds.append({"started_at": key, "label": time.strftime("%Y-%m-%d %H:%M", time.localtime(key)),
                       "per_clock": stages[-1]["per_clock"], "current": True, "stage": stages[-1]["label"]})
    if not builds and not stages:
        return None
    latest = (stages[-1]["per_clock"] if stages else builds[-1]["per_clock"])
    names = []
    for source in [latest] + [b["per_clock"] for b in reversed(builds)]:
        for name in source:
            if name not in names:
                names.append(name)
    names.sort(key=lambda n: ((latest.get(n) or {}).get("wns") is None, (latest.get(n) or {}).get("wns") or 0))
    return {"clocks": names[:MAX_CLOCKS], "builds": builds[-KEEP:], "stages": stages}
