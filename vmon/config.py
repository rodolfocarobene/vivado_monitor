"""Loads flows.toml (+ user override) and compiles everything the engine needs."""
import re
import tomllib
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
DEFAULT_FLOWS = PACKAGE_DIR / "flows.toml"
USER_FLOWS = Path.home() / ".config" / "vmon" / "flows.toml"


def deep_merge(base, override):
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _ordered(table):
    """Sub-tables of `table` that are dicts, sorted by their `order` key."""
    items = [(k, v) for k, v in table.items() if isinstance(v, dict)]
    return sorted(items, key=lambda kv: (kv[1].get("order", 1000), kv[0]))


class Rule:
    __slots__ = ("name", "action", "regex", "contains", "stop", "prefixes", "first", "order")

    def __init__(self, name, spec):
        self.name = name
        self.action = spec["action"]
        self.regex = re.compile(spec["re"]) if "re" in spec else None
        self.contains = spec.get("contains")
        self.stop = spec.get("stop", True)
        self.prefixes = tuple(spec.get("prefix", ()))
        self.first = spec.get("first", "")
        self.order = spec.get("order", 1000)

    def matches_prefix(self, line):
        if self.prefixes:
            return line.startswith(self.prefixes)
        if self.first:
            return line[0] in self.first
        return True


class TimingPattern:
    def __init__(self, name, spec):
        self.name = name
        self.label = spec.get("label", name)
        self.contains = spec.get("contains")
        self.regex = re.compile(spec["re"])
        self.fields = spec["fields"]


class StepDef:
    def __init__(self, step_id, spec):
        self.id = step_id
        self.label = spec.get("label", step_id)
        self.flow = spec.get("flow", "impl")
        self.order = spec.get("order", 1000)
        self.commands = tuple(spec.get("commands", ()))


class ReportType:
    def __init__(self, name, spec):
        self.name = name
        self.regex = re.compile(spec["pattern"])
        self.kind = spec.get("kind", name)
        self.parser = spec.get("parser", "generic")
        self.step = spec.get("step")
        self.label = spec.get("label", self.kind.replace("_", " ").capitalize())


class FailurePattern:
    def __init__(self, name, spec):
        self.name = name
        self.regex = re.compile(spec["re"])
        self.reason = spec.get("reason", name.replace("_", " ").capitalize())
        self.signal = spec.get("signal", False)


class FailureConfig:
    def __init__(self, spec):
        self.tail_bytes = spec.get("tail_bytes", 131072)
        self.max_details = spec.get("max_details", 6)
        self.max_line_chars = spec.get("max_line_chars", 240)
        self.hs_err_glob = spec.get("hs_err_glob", "hs_err_pid*.log")
        path_re = spec.get("hs_err_path_re")
        self.hs_err_path_re = re.compile(path_re) if path_re else None
        self.hs_err_head_lines = spec.get("hs_err_head_lines", 40)
        title_re = spec.get("hs_err_title_re")
        self.hs_err_title_re = re.compile(title_re) if title_re else None
        skip = spec.get("hs_err_skip_frames")
        self.hs_err_skip_frames = re.compile(skip) if skip else None
        self.signals = spec.get("signals", {})
        self.patterns = [FailurePattern(n, s) for n, s in _ordered(spec.get("patterns", {}))]


class ResumeConfig:
    def __init__(self, spec):
        self.checkpoint_re = re.compile(spec["checkpoint_re"]) if "checkpoint_re" in spec else None
        self.cd_re = re.compile(spec["cd_re"]) if "cd_re" in spec else None
        self.session_start_re = re.compile(spec["session_start_re"]) if "session_start_re" in spec else None
        self.scan_bytes = spec.get("scan_bytes", 262144)
        # longest suffix first so "_postroute_physopt" wins over "_physopt"
        self.checkpoints = sorted(spec.get("checkpoints", {}).items(), key=lambda kv: -len(kv[0]))

    def step_for_checkpoint(self, path):
        """Step a checkpoint file was written after (by its name suffix), or None."""
        stem = re.sub(r"\.dcp$", "", str(path).rsplit("/", 1)[-1])
        for suffix, step in self.checkpoints:
            if stem.endswith(suffix):
                return step
        return None

    @staticmethod
    def first_group(match):
        return next((g for g in match.groups() if g), None)


class Config:
    def __init__(self, data):
        self.data = data
        self.severity = data["severity"]
        parse = data["parse"]
        self.time_re = re.compile(parse["time_re"])
        self.wallclock_format = parse["wallclock_format"]
        self.tcl_start_step_re = re.compile(parse["tcl_start_step_re"], re.M)
        self.open_project_re = re.compile(parse["open_project_re"])
        self.version_re = re.compile(parse["version_re"])
        self.max_messages = parse.get("max_messages", 300000)

        self.rules = [Rule(n, s) for n, s in _ordered(data["rules"])]
        self.timing_patterns = [TimingPattern(n, s) for n, s in _ordered(data["timing"]["patterns"])]
        self.steps = {n: StepDef(n, s) for n, s in _ordered(data["steps"])}
        self.step_order = list(self.steps)
        self.step_commands = {c for s in self.steps.values() for c in s.commands}

        runs = data["runs"]
        self.run_classes = [(re.compile(s["pattern"]), s["kind"]) for _, s in _ordered(runs["classes"])]
        self.run_flow_ids = runs["flow_ids"]
        self.queue_glob = runs["queue_markers_glob"]
        self.synth_complete_file = runs["synth_complete_file"]
        self.jobs_dir = runs["jobs_dir"]
        self.jobs_glob = runs["jobs_glob"]
        self.layout = data["layout"]

        reports = data["reports"]
        self.report_types = [ReportType(n, s) for n, s in _ordered(reports["types"])]
        self.utilization_map = [(k, re.compile(v)) for k, v in reports["utilization"].items()]
        self.timing_columns = reports["timing_columns"]
        self.alerts = data["alerts"]
        self.failure = FailureConfig(data.get("failure", {}))
        self.resume = ResumeConfig(data.get("resume", {}))
        self._rules_by_char = {}

    def rules_for(self, first_char):
        rules = self._rules_by_char.get(first_char)
        if rules is None:
            rules = [r for r in self.rules
                     if (not r.prefixes and not r.first) or any(p[:1] == first_char for p in r.prefixes)
                     or (r.first and first_char in r.first)]
            self._rules_by_char[first_char] = rules
        return rules

    def classify_run(self, run_id, flow_id=None):
        for regex, kind in self.run_classes:
            if regex.search(run_id):
                return kind
        return self.run_flow_ids.get(flow_id)

    def steps_for_command(self, command):
        return [s for s in self.steps.values() if command in s.commands]


def load_config(extra_path=None):
    with open(DEFAULT_FLOWS, "rb") as fh:
        data = tomllib.load(fh)
    for path in (USER_FLOWS, Path(extra_path) if extra_path else None):
        if path and path.is_file():
            with open(path, "rb") as fh:
                data = deep_merge(data, tomllib.load(fh))
    return Config(data)
