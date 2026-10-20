"""Build-time estimate: previous completed build's per-step durations, else catalog weights."""
import json
from pathlib import Path

CURRENT_FLOOR = 0.10          # at least this fraction of the previous duration is assumed to remain


def step_durations(fw):
    """{step_id: seconds} of finished steps in the last flow (synth under 'synth_design')."""
    out = {}
    if not fw.flows:
        return out
    for stage in fw.flows[-1].stages:
        step_id = "synth_design" if stage.kind == "group" else stage.id.rsplit("/", 1)[-1]
        if stage.status == "done" and stage.elapsed_s:
            out[step_id] = round(stage.elapsed_s, 1)
    return out


class DurationStore:
    """~/.cache/vmon/durations/<fw_id>.json = {"build", "total_s", "steps": {step: seconds}} of the last completed build."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.version = 0

    def load(self, fw_id):
        try:
            data = json.loads((self.dir / (fw_id + ".json")).read_text())
            return data if isinstance(data, dict) and data.get("steps") else None
        except (OSError, ValueError):
            return None

    def record(self, fw_id, build, steps, total_s):
        current = self.load(fw_id)
        if not steps or (current and current.get("build") == build and current.get("steps") == steps):
            return False
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / (fw_id + ".json")).write_text(json.dumps(
                {"build": build, "total_s": total_s, "steps": steps}))
        except OSError:
            return False
        self.version += 1
        return True


def estimate(fw, previous, now):
    """Firmware.eta for a running build, else None."""
    if fw.status != "running" or not fw.flows:
        return None
    stages = fw.flows[-1].stages
    pending, current = [], None
    for stage in stages:
        step_id = "synth_design" if stage.kind == "group" else stage.id.rsplit("/", 1)[-1]
        if stage.status == "running":
            current = (step_id, stage)
        elif stage.status in ("pending", "queued"):
            pending.append(step_id)
    steps = (previous or {}).get("steps") or {}
    if steps and (current is None or current[0] in steps):
        remaining, missing = 0.0, False
        for step_id in pending:
            if step_id in steps:
                remaining += steps[step_id]
            else:
                missing = True
        if current:
            prev = steps[current[0]]
            elapsed = current[1].elapsed_s or 0.0
            remaining += max(prev - elapsed, CURRENT_FLOOR * prev)
        return {"expected_end": now + remaining, "remaining_s": round(remaining, 1),
                "method": "previous build", "confidence": "low" if missing else "medium"}
    progress, elapsed = fw.progress_estimate, fw.elapsed_s
    if progress and progress > 0.02 and elapsed:
        remaining = max(0.0, elapsed / progress - elapsed)
        return {"expected_end": now + remaining, "remaining_s": round(remaining, 1),
                "method": "catalog weights", "confidence": "low"}
    return {"expected_end": None, "remaining_s": None, "method": None, "confidence": "low"}
