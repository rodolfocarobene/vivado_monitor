"""Build-time estimate learned from past completed builds, with a confidence band; else catalog weights."""
import json
import statistics
from pathlib import Path

from .expected import normalize
from .paths import write_atomic

DEFAULTS = {"history_builds": 20, "low_quantile": 0.10, "high_quantile": 0.90,
            "small_sample_margin": 0.15, "current_floor": 0.10, "quantile_min_builds": 3, "high_confidence_builds": 5}
LEVELS = ("low", "medium", "high")


def settings(cfg):
    return {**DEFAULTS, **(cfg.data.get("eta") or {})}


def _step_id(stage):
    return "synth_design" if stage.kind == "group" else stage.id.rsplit("/", 1)[-1]


def _phases(node):
    """Descendant phase nodes of a step (any depth)."""
    for child in node.children:
        if child.kind == "phase":
            yield child
        yield from _phases(child)


def step_durations(fw):
    """{step_id: seconds} of finished steps in the last flow (synth under 'synth_design')."""
    out = {}
    if not fw.flows:
        return out
    for stage in fw.flows[-1].stages:
        if stage.status == "done" and stage.elapsed_s:
            out[_step_id(stage)] = round(stage.elapsed_s, 1)
    return out


def phase_durations(fw):
    """{step_id: {phase name without number: seconds}} of finished phases in the last flow."""
    out = {}
    if not fw.flows:
        return out
    for stage in fw.flows[-1].stages:
        found = {}
        for phase in _phases(stage):
            if phase.status == "done" and phase.elapsed_s and not phase.expected:
                key = normalize(phase.label)
                found[key] = round(found.get(key, 0.0) + phase.elapsed_s, 1)
        if found:
            out[_step_id(stage)] = found
    return out


class DurationStore:
    """<cache dir>/durations/<fw_id>.json = {"builds": [{"build", "total_s", "steps", "phases"}]}, oldest first.

    The older single-build file {"build", "total_s", "steps"} is read as one build and upgraded on the next write."""

    def __init__(self, directory, limit=DEFAULTS["history_builds"]):
        self.dir = Path(directory)
        self.limit = limit
        self.version = 0

    def load(self, fw_id):
        try:
            data = json.loads((self.dir / (fw_id + ".json")).read_text())
        except (OSError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        builds = data["builds"] if isinstance(data.get("builds"), list) else [data]
        return [b for b in builds if isinstance(b, dict) and b.get("steps")]

    def record(self, fw_id, build, steps, total_s, phases=None):
        entry = {"build": build, "total_s": total_s, "steps": steps, "phases": phases or {}}
        builds = self.load(fw_id)
        same = next((i for i, b in enumerate(builds) if b.get("build") == build), None)
        if not steps or (same is not None and builds[same] == entry):
            return False
        if same is None:
            builds.append(entry)
        else:
            builds[same] = entry
        path = self.dir / (fw_id + ".json")
        try:
            write_atomic(path, json.dumps({"builds": builds[-self.limit:]}))
        except OSError:
            return False
        self.version += 1
        return True


def quantile(values, q):
    values = sorted(values)
    pos = q * (len(values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def _running_phase(elapsed, typical, floor):
    return max(typical - elapsed, floor * typical)


class _Work:
    """What is left of the running build: pending steps, the running step and its phase state."""

    def __init__(self, stages, floor):
        self.floor = floor
        self.pending, self.current = [], None
        self.done_phases, self.running_phases = set(), {}
        self.weights = {}          # catalog weights of placeholder steps, to size steps with no history
        for stage in stages:
            step_id = _step_id(stage)
            if stage.estimate and stage.estimate.get("weight"):
                self.weights[step_id] = stage.estimate["weight"]
            if stage.status == "running":
                self.current = (step_id, stage.elapsed_s or 0.0)
                for phase in _phases(stage):
                    key = normalize(phase.label)
                    if phase.expected or phase.status in ("pending", "queued"):
                        continue
                    if phase.status == "running":
                        self.running_phases[key] = phase.elapsed_s or 0.0
                    else:
                        self.done_phases.add(key)
            elif stage.status in ("pending", "queued"):
                self.pending.append(step_id)

    def remaining(self, builds, pick):
        """Remaining seconds given builds' durations, `pick` reducing a list of samples (median or one build's value)."""
        total = 0.0
        step_id, elapsed = self.current or (None, 0.0)
        unknown, per_weight = [], []
        for pending in self.pending:
            samples = [b["steps"][pending] for b in builds if pending in b["steps"]]
            if samples:
                total += pick(samples)
                if self.weights.get(pending):
                    per_weight.append(pick(samples) / self.weights[pending])
            else:
                unknown.append(pending)
        # A step this firmware never ran is sized by its catalog weight at the seconds-per-weight of the known ones,
        # rather than counted as zero (which would make the ETA optimistic).
        if per_weight:
            rate = statistics.median(per_weight)
            total += sum(self.weights.get(u, 0.0) * rate for u in unknown)
        if step_id is not None:
            total += self._current(builds, pick, step_id, elapsed)
        return total

    def _current(self, builds, pick, step_id, elapsed):
        names = {n for b in builds for n in (b.get("phases") or {}).get(step_id, {})}
        if not names:
            typical = pick([b["steps"][step_id] for b in builds if step_id in b["steps"]] or [0.0])
            return _running_phase(elapsed, typical, self.floor)
        total = 0.0
        for name in names:
            if name in self.done_phases:
                continue
            samples = [b["phases"][step_id][name] for b in builds if name in (b.get("phases") or {}).get(step_id, {})]
            typical = pick(samples)
            total += _running_phase(self.running_phases[name], typical, self.floor) if name in self.running_phases else typical
        return total

    def known(self, builds):
        wanted = self.pending + ([self.current[0]] if self.current else [])
        return all(any(s in b["steps"] for b in builds) for s in wanted)


def _median_by_key(builds, step_id, name):
    samples = [b["phases"][step_id][name] for b in builds if name in (b.get("phases") or {}).get(step_id, {})]
    return statistics.median(samples) if samples else None


def _open_node(node):
    return node.status in ("pending", "queued", "running")


def _weighted_targets(children):
    """Children carrying a catalog weight at the first level that has any (steps often hide phases under a task)."""
    direct = [c for c in children if c.estimate and c.estimate.get("weight")]
    if direct:
        return direct
    for child in children:
        found = _weighted_targets(child.children)
        if found:
            return found
    return []


def _fill_children(node, total, builds, step_id):
    """Node.expected_s of the unfinished descendants: the history median of the phase, else its catalog weight
    as a share of `total` (the parent's expected duration)."""
    for child in node.children:
        if _open_node(child) and child.kind == "phase":
            child.expected_s = _median_by_key(builds, step_id, normalize(child.label))
    if total:
        targets = _weighted_targets(node.children)
        weight_sum = sum(t.estimate["weight"] for t in targets)
        for target in targets:
            if _open_node(target) and target.expected_s is None and weight_sum:
                target.expected_s = total * target.estimate["weight"] / weight_sum
    for child in node.children:
        sub = child.expected_s
        if sub is None and child.kind == "task" and not (child.estimate or {}).get("weight"):
            sub = total      # a task wrapper passes its parent's duration down to the phases inside it
        _fill_children(child, sub, builds, step_id)


def annotate_expected(fw, history):
    """Set Node.expected_s on the pending and running nodes of the last flow, from build history first, else catalog
    weights (a step with no history gets its weight at the seconds-per-weight of the steps that have it).
    Left None when unknown."""
    if not fw.flows:
        return
    builds = list(history or [])
    stages = fw.flows[-1].stages
    per_weight = []
    for stage in stages:
        weight = (stage.estimate or {}).get("weight")
        samples = [b["steps"][_step_id(stage)] for b in builds if _step_id(stage) in b["steps"]]
        if samples and weight:
            per_weight.append(statistics.median(samples) / weight)
    rate = statistics.median(per_weight) if per_weight else None
    for stage in stages:
        step_id = _step_id(stage)
        samples = [b["steps"][step_id] for b in builds if step_id in b["steps"]]
        weight = (stage.estimate or {}).get("weight")
        if _open_node(stage):
            stage.expected_s = statistics.median(samples) if samples else weight * rate if weight and rate else None
        if stage.kind == "group":
            continue      # synthesis runs (OOC and top) are not phases of the history store
        _fill_children(stage, stage.expected_s, builds, step_id)


def _band(per_build, remaining, cfg):
    if len(per_build) >= cfg["quantile_min_builds"]:
        low, high = quantile(per_build, cfg["low_quantile"]), quantile(per_build, cfg["high_quantile"])
    else:
        low, high = min(per_build) * (1 - cfg["small_sample_margin"]), max(per_build) * (1 + cfg["small_sample_margin"])
    return min(low, remaining), max(high, remaining)


def _confidence(count, complete, cfg):
    level = 2 if count >= cfg["high_confidence_builds"] else 1 if count >= 2 else 0
    return LEVELS[level if complete else max(level - 1, 0)]


def _result(now, remaining, low, high, method, builds, confidence):
    def end(value):
        return None if value is None else now + value
    return {"expected_end": end(remaining), "remaining_s": None if remaining is None else round(remaining, 1),
            "low_end": end(low), "high_end": end(high),
            "remaining_low_s": None if low is None else round(low, 1),
            "remaining_high_s": None if high is None else round(high, 1),
            "method": method, "builds": builds, "confidence": confidence}


def estimate(fw, history, now, cfg=None):
    """Firmware.eta for a running build, else None."""
    if fw.status != "running" or not fw.flows:
        return None
    cfg = {**DEFAULTS, **(cfg or {})}
    builds = list(history or [])
    work = _Work(fw.flows[-1].stages, cfg["current_floor"])
    current_known = work.current is None or any(work.current[0] in b["steps"] for b in builds)
    if builds and current_known:
        remaining = work.remaining(builds, statistics.median)
        per_build = [work.remaining([b], lambda s: s[0]) for b in builds]
        low, high = _band(per_build, remaining, cfg)
        return _result(now, remaining, low, high, "history", len(builds),
                       _confidence(len(builds), work.known(builds), cfg))
    progress, elapsed = fw.progress_estimate, fw.elapsed_s
    if progress and progress > 0.02 and elapsed:
        remaining = max(0.0, elapsed / progress - elapsed)
        margin = 2 * cfg["small_sample_margin"]
        return _result(now, remaining, remaining * (1 - margin), remaining * (1 + margin), "catalog weights", 0, "low")
    return _result(now, None, None, None, None, 0, "low")
