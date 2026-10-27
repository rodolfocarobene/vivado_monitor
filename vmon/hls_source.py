"""Vitis HLS firmware: HlsSource builds the flow (steps, phases, counts, estimated timing, csynth report) from
vitis_hls.log, planned steps from its Tcl script. Patterns and steps are in flows.toml [hls]; see hls.py."""
import os
import time
from pathlib import Path

from . import alerts as alert_rules
from . import failure as failure_mod
from . import info as info_mod
from .hls import HlsParser, hls_config
from .model import Firmware, Flow, Node, Timing, compute_met
from .paths import canon, join
from .project import RECENT_GROWTH_S, ParsedLog, Source
from .tclscript import script_commands


class HlsLog(ParsedLog):
    parser_cls = HlsParser


# ---------------------------------------------------------------------- source
class HlsSource(Source):
    kind = "hls"

    def __init__(self, log_path, config, report_cache, catalog, attempt_dir=None):
        super().__init__(log_path, config, report_cache, catalog, attempt_dir)
        self.hls = hls_config(config)
        self.name = Path(log_path).parent.name
        self._plan_cache = {}

    def _log(self, path):
        if path == self.path and path not in self.logs:
            self.logs[path] = HlsLog(path, self.cfg, self.catalog)
        return super()._log(path)

    # ---- locations
    def _solution_dir(self, meta):
        return meta["solution"] and canon(meta["solution"])

    def _launch_dir(self, group, meta):
        launcher = (group.launcher if group else None) or {}
        return launcher.get("cwd") or meta["directory"] or os.path.dirname(os.path.abspath(self.path))

    def _planned(self, group, meta):
        """Step ids the Tcl script (-f, or `Sourcing Tcl script` in the log) runs, in order; None when unreadable."""
        launcher = (group.launcher if group else None) or {}
        script = launcher.get("script") or meta["script"]
        if not script:
            return None
        cwd = self._launch_dir(group, meta)
        commands, _files, _vars = script_commands(script, cwd, self.hls.script_cfg, launcher.get("tclargs") or ())
        if commands is None:
            return None
        planned = []
        for command in commands:
            step = self.hls.step_for(command)
            if step and step.id not in planned:
                planned.append(step.id)
        return sorted(planned, key=self.hls.step_order.index)

    # ---- reports
    def _csynth_reports(self, step_def, solution, begin):
        out = []
        if not solution or not step_def.report_dir:
            return out
        for name in step_def.report_files:
            path = canon(join(join(solution, step_def.report_dir), name))
            parsed = self.reports.parse(path, "hls_csynth")
            if parsed is None or "parse_error" in parsed[0]:
                continue
            mtime = os.stat(path).st_mtime
            stale = begin is not None and mtime < begin - 1
            self.report_paths.add(path)
            out.append({"name": name, "label": self.hls.report_label, "kind": self.hls.report_kind, "path": path,
                        "mtime": mtime, "stale": stale, "summary": parsed[0], "alerts": [] if stale else parsed[1],
                        "doc_url": None})
        return out

    def _estimated_timing(self, node, report):
        """The report's slack (target - uncertainty - estimated clock) replaces the log's estimate."""
        summary = report["summary"]
        slack = summary.get("slack_ns")
        if slack is None or report["stale"]:
            return
        history = node.timing.history if node.timing else []
        node.timing = Timing(wns=slack, met=compute_met(slack, None, None), source="report", label=self.hls.timing_label,
                             history=history, final=False, stage="%s · estimated" % node.label, report=report["path"])

    def _child_log(self, step_def, solution, node):
        """export_design's own Vivado log as a child node (shown, not counted again: it is echoed in the HLS log)."""
        if not solution or not step_def.child_log:
            return None
        path = canon(join(solution, step_def.child_log))
        if not os.path.exists(path):
            return None
        vlog = self._log(path)
        child = Node(id="%s/vivado-log" % node.id, label=os.path.basename(path), kind="task", status=node.status)
        child.log, child.line_start, child.line_end = path, 1, vlog.line_count
        child.description = "Log of the Vivado that packages the IP (its output is also echoed in the HLS log)"
        self._register(child, vlog, 1, vlog.line_count, child.status == "running")
        return child

    # ---- timeline
    @staticmethod
    def _begins(sections, session_start, order):
        """{step id: (begin, end)}: a section's own stamps, else chained from the previous step's end."""
        out, previous = {}, session_start
        for sid in order:
            section = sections[sid]
            begin = section.started_at if section.started_at is not None else previous
            end = section.ended_at
            if end is None and begin is not None and section.elapsed_s is not None and section.status != "running":
                end = begin + section.elapsed_s
            out[sid] = (begin, end)
            previous = end or begin
        return out

    def _info(self, fw):
        info = info_mod.empty_info()
        meta, settings = self._parser_state()
        info.update(part=settings.get("part"), top=settings.get("top"), vivado_version=fw.vivado_version,
                    project=meta["project"])
        return info

    def _parser_state(self):
        plog = self.logs.get(self.path)
        return (plog.parser.meta, plog.parser.settings) if plog else ({}, {})

    def snapshot(self, group, now=None):
        now = now or time.time()
        self.index = {}
        self.report_paths = set()
        plog = self._log(self.path)
        parser = plog.parser
        meta = parser.meta
        live = bool(group and group.pids) or (plog.growth_age(now) or 1e9) < RECENT_GROWTH_S
        sections = {}
        for section in plog.step_sections():
            sections[self.hls.step_for(section.cmd).id] = section        # a command run twice: the newest wins
        order = [sid for sid in self.hls.step_order if sid in sections]
        planned = self._planned(group, meta)
        solution = self._solution_dir(meta)
        times = self._begins(sections, parser.session_start, order)
        stages = []
        for sid in order:
            section, step_def = sections[sid], self.hls.steps[sid]
            status, open_status, failure = section.status, "running" if live else "stopped", None
            if section.status == "running" and not live:
                status = "stopped"
                found = failure_mod.detect([self.path], self.cfg)
                if found:
                    status, open_status, failure = "failed", "failed", found
            elif status == "failed":
                open_status = "failed"
                failure = self._failure_for([self.path], None, None, section, plog)
            begin, end = times[sid]
            reports = self._csynth_reports(step_def, solution, begin) if step_def.report_files else []
            node = self._step_node(sid, "hls/" + sid, plog, section, status, open_status, live, None,
                                   begin, end, reports, now, failure)
            node.description = step_def.description
            node.label = step_def.label
            for report in reports:
                self._estimated_timing(node, report)
            if node.timing is not None and node.timing.source == "log":
                node.timing.stage = "%s · estimated" % node.label
            child = self._child_log(step_def, solution, node)
            if child is not None:
                node.children.append(child)
            node.alerts = alert_rules.node_alerts(node, sid, self.cfg, plog.growth_age(now), live)    # with the HLS label
            stages.append(node)
        if live:
            last = planned.index(order[-1]) if planned and order and order[-1] in planned else -1
            pending = [s for s in (planned or [])[last + 1:] if s not in sections] if planned else []
        else:
            pending = []
        for sid in pending:
            node = self._step_node(sid, "hls/" + sid, plog, None, "pending", "done", live, None, None, None, (), now)
            node.label, node.description = self.hls.steps[sid].label, self.hls.steps[sid].description
            stages.append(node)
        project = Path(meta["project"]).name if meta["project"] else None
        solution_name = Path(meta["solution"]).name if meta["solution"] else None
        fw = Firmware(id=self.id, name="/".join(p for p in (project, solution_name) if p) or self.name,
                      kind="hls", path=self.path)
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
        fw.started_at = parser.session_start
        fw.attempt = {"n": 1, "mode": "project", "resumed_from": None, "previous_failure": None}
        fw.updated_at = plog.tail.last_growth
        if fw.started_at:
            fw.elapsed_s = (max(0.0, now - fw.started_at) if fw.status == "running"
                            else parser.total[0] if parser.total else max(0.0, fw.updated_at - fw.started_at))
        self._finish(fw, [Flow(id="hls", label=Path(self.path).name, stages=stages)], [plog], group, live, now)
        fw.utilization = fw.utilization or self._csynth_utilization(stages)
        return fw

    @staticmethod
    def _csynth_utilization(stages):
        """The csynth resource estimate in the Utilization card (an HLS run has no placement report)."""
        for node in stages:
            for report in node.reports:
                rows = report["summary"].get("resources") if report["kind"] == "hls_csynth" else None
                if rows and not report["stale"]:
                    return {"step": node.label, "label": "Resource estimate", "report": report["name"],
                            "path": report["path"], "rows": rows}
        return None
