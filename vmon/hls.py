"""Vitis HLS builds: config, path resolution, the streaming parser for vitis_hls.log and the csynth report parser.
(The Source that turns it into a flow is hls_source.py.)

Everything HLS-specific (patterns, steps, phases, report file) is in flows.toml [hls]. Verified on one Vitis HLS
2023.2 csynth_design + export_design run; csim_design, cosim_design and v++ are written from the documented
formats and are unverified. Read-only like the rest of vmon.
"""
import os
import re
import time
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from . import reports as reports_mod
from .config import DEFAULT_FLOWS, NonProjectConfig, _ordered
from .logparse import SEV_INDEX, ParseNode, slug
from .paths import canon
from .textio import decode


class HlsPhase:
    def __init__(self, phase_id, spec):
        self.id = phase_id
        self.label = spec.get("label", phase_id)
        self.start_re = re.compile(spec["start_re"]) if "start_re" in spec else None


class HlsStep:
    def __init__(self, step_id, spec):
        self.id = step_id
        self.label = spec.get("label", step_id)
        self.order = spec.get("order", 1000)
        self.commands = tuple(spec.get("commands", ()))
        self.description = spec.get("description")
        self.report_dir = spec.get("report_dir")
        self.report_files = list(spec.get("report_files", ()))
        self.child_log = spec.get("child_log")
        self.phases = [HlsPhase(n, s) for n, s in _ordered(spec.get("phases", {}))]


class HlsConfig:
    def __init__(self, data):
        spec = data["hls"]
        self.log_name = spec["log_name"]
        self.sniff_bytes = spec["sniff_bytes"]
        self.sniff_re = re.compile(spec["sniff_re"])
        self.project_files = tuple(spec["project_files"])
        proc = spec["processes"]
        self.engines, self.wrappers = list(proc["engines"]), list(proc["wrappers"])
        self.script_flags, self.log_flags = list(proc["script_flags"]), list(proc["log_flags"])
        self.child_cwd_re = re.compile(proc["child_cwd_re"])
        parse = spec["parse"]
        for key in ("banner_re", "message_re", "command_re", "finished_re", "phase_finished_re", "total_re", "exit_re",
                    "directory_re", "script_re", "project_re", "solution_re", "session_start_re", "fail_re"):
            setattr(self, key, re.compile(parse[key]))
        self.session_format = parse["session_format"]
        self.severity = data["severity"]
        self.settings = [(name, s["command"], re.compile(s["re"])) for name, s in spec["settings"].items()]
        timing = spec["timing"]
        self.timing_label, self.timing_step = timing["label"], timing["step"]
        self.violation_re, self.fmax_re, self.clock_re = (re.compile(timing[k]) for k in ("violation_re", "fmax_re", "clock_re"))
        self.steps = {n: HlsStep(n, s) for n, s in _ordered(spec["steps"])}
        self.step_order = list(self.steps)
        self.by_command = {c: s for s in self.steps.values() for c in s.commands}
        self.report_label, self.report_kind = spec["csynth_report"]["label"], spec["csynth_report"]["kind"]
        # the Tcl reader of tclscript.py, fed with the HLS commands instead of the Vivado ones
        nonproject = dict(data["nonproject"], reports={})
        self.script_cfg = SimpleNamespace(nonproject=NonProjectConfig(nonproject, set(self.by_command)))

    def step_for(self, command):
        return self.by_command.get(command)

    def process_names(self, windows):
        """{image name: kind} for the platform; 'engine' or 'wrapper'."""
        suffix = ".exe" if windows else ""
        out = {n + suffix: "engine" for n in self.engines}
        out.update({n + suffix: "wrapper" for n in self.wrappers})
        return out


def hls_config(cfg):
    """The compiled [hls] tables of a Config, built once (config.py does not import this module)."""
    found = getattr(cfg, "_hls", None)
    if found is None:
        found = cfg._hls = HlsConfig(cfg.data)
    return found


_DEFAULTS = {}


def _default_config():
    if "cfg" not in _DEFAULTS:
        with open(DEFAULT_FLOWS, "rb") as fh:
            _DEFAULTS["cfg"] = HlsConfig(tomllib.load(fh))
    return _DEFAULTS["cfg"]


def is_hls_log(path, hls=None):
    """True when the head of the file is a Vitis HLS banner or carries [HLS 200-n] messages."""
    hls = hls or _default_config()
    try:
        with open(path, "rb") as fh:
            head = decode(fh.read(hls.sniff_bytes))
    except OSError:
        return False
    return hls.sniff_re.search(head) is not None


def resolve(path, hls=None):
    """The vitis_hls.log a user path stands for: the log itself, its directory, the project dir (hls.app) or a
    solution dir (falls back to the solution's own log). None when it is not an HLS location."""
    hls = hls or _default_config()
    path = Path(path)
    if path.is_file():
        return canon(path) if path.name == hls.log_name or is_hls_log(path, hls) else None
    if not path.is_dir():
        return None

    def is_project(folder):
        return any((folder / name).exists() for name in hls.project_files)

    if is_project(path):
        beside = [path / hls.log_name, path.parent / hls.log_name]
        own = [p for p in path.glob("*/*.log") if p.stem == p.parent.name]
    elif is_project(path.parent):
        beside = [path.parent / hls.log_name, path.parent.parent / hls.log_name]
        own = [path / (path.name + ".log")]
    else:
        return canon(path / hls.log_name) if (path / hls.log_name).is_file() else None
    found = next((p for p in beside if p.is_file()), None)
    if found is None:
        found = max((p for p in own if p.is_file()), key=lambda p: p.stat().st_mtime, default=None)
    return canon(found) if found else None


def read_meta(log_path, hls, limit=262144):
    """{'directory', 'script', 'project'} from the head of a log (for discovery, before a source exists)."""
    meta = {"directory": None, "script": None, "project": None}
    try:
        with open(log_path, "rb") as fh:
            text = decode(fh.read(limit))
    except OSError:
        return meta
    for line in text.split("\n"):
        for key, regex in (("directory", hls.directory_re), ("script", hls.script_re), ("project", hls.project_re)):
            match = regex.match(line)
            if match and meta[key] is None:
                meta[key] = match.group(1)
        if all(meta.values()):
            break
    return meta


# ---------------------------------------------------------------------- parser
class HlsParser:
    """Same surface as logparse.LogParser (root, messages, agg, ...) so ParsedLog and Source can use it."""

    def __init__(self, config, catalogs=None):
        self.hls = hls_config(config)
        self.root = ParseNode("root", "log", "root")
        self.root.line_start = 1
        self.cur_step = None
        self.cur_phase = None
        self.phase_index = -1
        self.line_no = 0
        self.messages = []
        self.agg = {}
        self.lines_by_key = {}
        self.msg_count = 0
        self.max_messages = config.max_messages
        self.version = None
        self.part = None                 # the Vivado catalog's device-family lookup is not used for HLS
        self.session_starts = []
        self.live = False
        self.exited = False
        self.session_start = None        # epoch seconds of the session banner
        self.cursor = None               # estimated wall time of the current line when the log is not read live
        self.total = None                # (elapsed s, peak MB) of the final summary line
        self.meta = {"directory": None, "script": None, "project": None, "solution": None}
        self.settings = {}
        self.target_ns = None
        self._failed = set()             # ids of steps that matched fail_re
        self._timing_line = {}           # id(step) -> True once it has a timing entry

    def mark_live(self):
        self.live = True

    # ---- helpers
    def _stamp(self):
        return time.time() if self.live else self.cursor

    def _new(self, parent, kind, label, key_base):
        count = parent.key_counts.get(key_base, 0) + 1
        parent.key_counts[key_base] = count
        node = ParseNode(kind, label, key_base if count == 1 else "%s~%d" % (key_base, count))
        node.line_start = self.line_no
        node.started_at = self._stamp()
        parent.children.append(node)
        return node

    def _close_phase(self, line_end, status="done"):
        phase = self.cur_phase
        if phase is not None:
            phase.status = status
            phase.line_end = line_end
            phase.ended_at = self._stamp()
            self.cur_phase = None

    def _finish_step(self, step, line_end, status):
        self._close_phase(line_end, status)
        step.status = status
        step.line_end = line_end
        if step.started_at is not None and step.elapsed_s is not None:
            step.ended_at = step.started_at + step.elapsed_s
            if not self.live:
                self.cursor = step.ended_at
        elif self.live:
            step.ended_at = time.time()

    def _abort_open_step(self, line_end):
        step = self.cur_step
        if step is not None and step.completed_line is None:
            failed = step.own[3] > 0 or id(step) in self._failed
            self._finish_step(step, line_end, "failed" if failed or self.exited else "done")
            step.completed_line = line_end

    # ---- feeding
    def feed(self, lines):
        hls = self.hls
        for line in lines:
            self.line_no += 1
            if not line:
                continue
            first = line[0]
            if self.version is None and self.line_no < 40 and first == "*":
                match = hls.banner_re.search(line)
                if match:
                    self.version = match.group(1)
            if first in "IWCE":
                self._message(line)
                match = hls.clock_re.search(line)
                if match:
                    self.target_ns = float(match.group(1))
            elif first == "S":
                match = hls.script_re.match(line)
                if match and self.meta["script"] is None:
                    self.meta["script"] = match.group(1)
            if first == "*" and self.cur_step is not None:
                self._open_phase(line)
            if first not in "IWCE":
                continue
            if line.startswith("INFO: [HLS 200-"):
                self._info_line(line)
            else:
                self._other_line(line)

    def _message(self, line):
        match = self.hls.message_re.match(line)
        if match is None:
            return
        severity = SEV_INDEX[self.hls.severity[match.group(1)]]
        message_id, text = match.group(2), match.group(3)
        key = message_id or text[:60]
        entry = self.agg.get(key)
        if entry is None:
            self.agg[key] = [severity, 1, text, self.line_no, self.line_no]
            self.lines_by_key[key] = [self.line_no]
        else:
            entry[0] = max(entry[0], severity)
            entry[1] += 1
            entry[4] = self.line_no
            self.lines_by_key[key].append(self.line_no)
        self.msg_count += 1
        if len(self.messages) < self.max_messages:
            self.messages.append((self.line_no, severity, message_id, text))
        (self.cur_step or self.root).own[severity] += 1
        if severity == SEV_INDEX["error"] and self.cur_step is not None and self.hls.fail_re.match(line):
            self._failed.add(id(self.cur_step))

    def _info_line(self, line):
        hls = self.hls
        match = hls.command_re.match(line)
        if match:
            return self._command(match.group(1), match.group(2).strip())
        match = hls.finished_re.match(line)
        if match:
            return self._finished(match.group(1), float(match.group(2)))
        match = hls.phase_finished_re.match(line)
        if match:
            if self.cur_phase is not None:
                self.cur_phase.elapsed_s = round((self.cur_phase.elapsed_s or 0.0) + float(match.group(2)), 3)
                if not self.live and self.cursor is not None:
                    self.cursor += float(match.group(2))
            self._open_phase(line)
            return
        match = hls.total_re.match(line)
        if match:
            self.total = (float(match.group(1)), float(match.group(2)))
            return
        for key, regex in (("directory", hls.directory_re), ("project", hls.project_re), ("solution", hls.solution_re)):
            match = regex.match(line)
            if match:
                self.meta[key] = match.group(1)
                return
        match = hls.session_start_re.match(line)
        if match and self.session_start is None:
            try:
                self.session_start = time.mktime(time.strptime("%s %s" % match.groups(), hls.session_format))
            except ValueError:
                return
            self.cursor = self.session_start
            return
        self._open_phase(line)

    def _other_line(self, line):
        hls = self.hls
        if hls.exit_re.match(line):
            self.exited = True
            self._abort_open_step(self.line_no)
            return
        self._open_phase(line)

    def _command(self, name, args):
        hls = self.hls
        for key, command, regex in hls.settings:
            if command == name:
                match = regex.search(args)
                if match:
                    self.settings[key] = match.group(1)
        step_def = hls.step_for(name)
        if step_def is None:
            return
        first = self.cur_step is None
        if self.cur_step is not None:
            self._abort_open_step(self.line_no - 1)
        node = self._new(self.root, "step", step_def.label, name)
        node.cmd = name
        node.args = args
        if first:
            node.line_start = 1                  # the preamble belongs to the first step
            node.own = list(self.root.own)
            self.root.own = [0, 0, 0, 0]
        self.cur_step = node
        self.cur_phase, self.phase_index = None, -1
        if step_def.phases and step_def.phases[0].start_re is None:
            self._start_phase(0)

    def _finished(self, name, elapsed):
        step = self.cur_step
        if step is None or step.cmd != name or step.completed_line is not None:
            return
        step.elapsed_s = elapsed
        failed = id(step) in self._failed
        self._finish_step(step, self.line_no, "failed" if failed else "done")
        step.completed_line = self.line_no

    def _start_phase(self, index):
        step_def = self.hls.step_for(self.cur_step.cmd)
        self._close_phase(self.line_no - 1)
        spec = step_def.phases[index]
        node = self._new(self.cur_step, "phase", spec.label, "p-" + slug(spec.id))
        self.cur_phase, self.phase_index = node, index

    def _open_phase(self, line):
        step = self.cur_step
        if step is None or step.completed_line is not None:
            return
        phases = self.hls.step_for(step.cmd).phases
        for index in range(self.phase_index + 1, len(phases)):
            regex = phases[index].start_re
            if regex is not None and regex.search(line):
                self._start_phase(index)
                break
        self._timing(line)

    def _timing(self, line):
        hls, step = self.hls, self.cur_step
        if step.cmd != hls.timing_step:
            return
        match = hls.violation_re.search(line)
        slack = None
        if match:
            estimated, _target, _uncertainty, budget = (float(g) for g in match.groups())
            slack = round(budget - estimated, 3)
        elif not self._timing_line.get(id(step)):
            match = hls.fmax_re.search(line)
            if match and self.target_ns:
                slack = round(self.target_ns - 1000.0 / float(match.group(1)), 3)
        if slack is not None:
            self._timing_line[id(step)] = True
            step.history.append({"t": self._stamp(), "line": self.line_no, "label": hls.timing_label,
                                 "wns": slack, "tns": None, "whs": None, "ths": None})


# ---------------------------------------------------------------------- csynth report
def _num(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _int(text):
    value = _num(text)
    return None if value is None else int(value)


@reports_mod.register("hls_csynth")
def parse_csynth(text, cfg):
    """Summary of a csynth.xml (target/estimated clock, latency, interval, resources, loops) and its alerts."""
    root = ET.fromstring(text)
    user = root.find("UserAssignments")
    perf = root.find("PerformanceEstimates")
    area = root.find("AreaEstimates")
    get = lambda parent, path: (parent.findtext(path) if parent is not None else None)
    target, uncertainty = _num(get(user, "TargetClockPeriod")), _num(get(user, "ClockUncertainty"))
    estimated = _num(get(perf, "SummaryOfTimingAnalysis/EstimatedClockPeriod"))
    summary = {"top": get(user, "TopModelName"), "part": get(user, "Part"), "flow_target": get(user, "FlowTarget"),
               "target_ns": target, "uncertainty_ns": uncertainty, "estimated_ns": estimated,
               "slack_ns": None, "fmax_mhz": round(1000.0 / estimated, 2) if estimated else None,
               "latency_min": _int(get(perf, "SummaryOfOverallLatency/Best-caseLatency")),
               "latency_max": _int(get(perf, "SummaryOfOverallLatency/Worst-caseLatency")),
               "latency_time": get(perf, "SummaryOfOverallLatency/Worst-caseRealTimeLatency"),
               "interval_min": _int(get(perf, "SummaryOfOverallLatency/Interval-min")),
               "interval_max": _int(get(perf, "SummaryOfOverallLatency/Interval-max")),
               "pipeline": get(perf, "PipelineType")}
    if target is not None and estimated is not None:
        summary["slack_ns"] = round(target - (uncertainty or 0.0) - estimated, 3)
    resources, alerts = [], []
    used_node = area.find("Resources") if area is not None else None
    avail_node = area.find("AvailableResources") if area is not None else None
    if used_node is not None and avail_node is not None:
        for child in used_node:
            used, available = _int(child.text), _int(avail_node.findtext(child.tag))
            pct = round(100.0 * used / available, 1) if used is not None and available else None
            resources.append({"name": child.tag, "used": used, "available": available, "pct": pct})
            if pct is not None and pct > 100:
                alerts.append({"level": "error", "code": "hls_over_budget",
                               "message": "%s uses %.0f%% of the device (%d / %d)" % (child.tag, pct, used, available)})
    summary["resources"] = resources
    loops = []
    loop_table = perf.find("SummaryOfLoopLatency") if perf is not None else None
    for loop in (list(loop_table) if loop_table is not None else ()):
        loops.append({"name": loop.tag, "latency": _int(loop.findtext("Latency")), "trip_count": _int(loop.findtext("TripCount")),
                      "ii": _int(loop.findtext("PipelineII")), "depth": _int(loop.findtext("PipelineDepth")),
                      "slack_ns": _num(loop.findtext("Slack"))})
    summary["loops"] = loops
    return summary, alerts
