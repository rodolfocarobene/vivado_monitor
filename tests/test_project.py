import json
import os
import shutil

from conftest import FIXTURES, build_runs, marker, touch
from vmon.discovery import Group, runs_location
from vmon.monitor import resolve_path
from vmon.project import LogSource, ProjectSource, assign_sections


def lockin(tmp_path, **kw):
    f = FIXTURES / "lockin"
    return build_runs(tmp_path, "lockin", "main_wrapper", f / "main_wrapper.vdi", f / "main_wrapper.tcl",
                      f / "main_wrapper.vds",
                      [("init_design", "begin"), ("init_design", "end"), ("opt_design", "begin"),
                       ("opt_design", "end"), ("place_design", "begin")], **kw)


def qick(tmp_path):
    f = FIXTURES / "qick"
    steps = ["init_design", "opt_design", "place_design", "phys_opt_design", "route_design", "write_bitstream"]
    markers = [(s, k) for s in steps for k in ("begin", "end")]
    runs = build_runs(tmp_path, "top", "d_1_wrapper", f / "d_1_wrapper.vdi", f / "d_1_wrapper.tcl",
                      f / "main_wrapper.vds" if False else FIXTURES / "lockin" / "main_wrapper.vds",
                      markers, vivado_end=True)
    for rpt in f.glob("*.rpt"):
        shutil.copy(rpt, runs / "impl_1" / rpt.name)
        os.utime(runs / "impl_1" / rpt.name, (1_003_000.0, 1_003_000.0))
    return runs


def make(cls, path, cfg, report_cache, catalogs):
    return cls(path, cfg, report_cache, catalogs)


def stage_map(fw):
    return {s.id: s for s in fw.flows[0].stages}


def test_live_lockin_flow(tmp_path, cfg, report_cache, catalogs):
    runs = lockin(tmp_path, impl_pid=os.getpid())
    source = make(ProjectSource, runs, cfg, report_cache, catalogs)
    fw = source.snapshot(Group("project", str(runs), "lockin", {os.getpid()}), now=1_001_000.0)
    stages = stage_map(fw)
    assert fw.name == "lockin" and fw.status == "running" and fw.live
    assert [k for k in stages] == ["synth", "impl_1/init_design", "impl_1/opt_design", "impl_1/place_design",
                                   "impl_1/phys_opt_design", "impl_1/route_design", "impl_1/write_bitstream"]
    assert {k: v.status for k, v in stages.items()} == {
        "synth": "done", "impl_1/init_design": "done", "impl_1/opt_design": "done",
        "impl_1/place_design": "running", "impl_1/phys_opt_design": "pending",
        "impl_1/route_design": "pending", "impl_1/write_bitstream": "pending"}
    assert fw.current["node_id"].startswith("impl_1/place_design/")
    synth = stages["synth"]
    assert synth.children[0].kind == "group" and synth.children[0].label == "IP out-of-context (1)"
    assert synth.children[1].id == "synth_1" and synth.children[1].kind == "run"
    assert fw.counts[1] > 0 and fw.progress_estimate is not None and 0 < fw.progress_estimate < 1
    json.dumps(fw.to_dict())
    # pending step shows expected children from the catalog
    pending = stages["impl_1/route_design"]
    assert pending.children and all(c.expected and c.status == "pending" for c in pending.children)


def test_process_gone_marks_stopped(tmp_path, cfg, report_cache, catalogs):
    runs = lockin(tmp_path)                      # marker pid is dead, no process group
    fw = make(ProjectSource, runs, cfg, report_cache, catalogs).snapshot(None, now=1_001_000.0)
    stages = stage_map(fw)
    assert fw.status == "stopped" and not fw.live
    assert stages["impl_1/place_design"].status == "stopped"
    codes = {a["code"] for a in fw.alerts}
    assert "process_gone" in codes and fw.health == "error"
    running_kids = [n for n in _walk(stages["impl_1/place_design"]) if n.status == "running"]
    assert not running_kids


def _walk(node):
    yield node
    for c in node.children:
        yield from _walk(c)


def test_finished_qick_with_timing_report(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    source = make(ProjectSource, runs, cfg, report_cache, catalogs)
    fw = source.snapshot(None, now=1_010_000.0)
    stages = stage_map(fw)
    assert fw.status == "done" and fw.health in ("ok", "warning")
    route = stages["impl_1/route_design"]
    assert route.status == "done" and route.timing.source == "report"
    assert (route.timing.wns, route.timing.whs, route.timing.met) == (0.006, 0.01, True)
    assert fw.timing.source == "report"
    labels = [h["label"] for h in route.timing.history]
    assert "Intermediate" in labels and labels[-1] == "Post Routing"
    kinds = {r["kind"] for r in route.reports}
    assert {"timing_summary", "drc", "route_status", "power"} <= kinds
    assert all(not r["stale"] for r in route.reports)
    util = [r for r in stages["impl_1/place_design"].reports if r["kind"] == "utilization"]
    assert util and util[0]["summary"]["rows"][0]["name"] == "LUT"
    place = stages["impl_1/place_design"]
    assert place.timing.history[0]["label"] == "Estimated"


def test_stale_report_never_alerts(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    rpt = runs / "impl_1" / "d_1_wrapper_utilization_placed.rpt"
    os.utime(rpt, (900_000.0, 900_000.0))               # older than the place_design begin marker
    cfg.alerts["utilization_pct"] = 1
    fw = make(ProjectSource, runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    place = stage_map(fw)["impl_1/place_design"]
    util = [r for r in place.reports if r["kind"] == "utilization"][0]
    assert util["stale"] is True and util["alerts"] == []
    assert not [a for a in fw.alerts if a["code"] == "utilization"]
    os.utime(rpt, (1_003_000.0, 1_003_000.0))
    fw = make(ProjectSource, runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    assert [a for a in fw.alerts if a["code"] == "utilization"]


def test_failed_step_marker_and_error_alert(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    os.remove(runs / "impl_1" / ".write_bitstream.end.rst")
    os.remove(runs / "impl_1" / ".vivado.end.rst")
    touch(runs / "impl_1" / ".write_bitstream.error.rst", 1_009_000.0)
    fw = make(ProjectSource, runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    assert stage_map(fw)["impl_1/write_bitstream"].status == "failed"
    assert fw.status == "failed" and any(a["code"] == "step_failed" for a in fw.alerts)


def test_timing_alert_levels(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    os.remove(runs / "impl_1" / "d_1_wrapper_timing_summary_routed.rpt")
    fw = make(ProjectSource, runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    place_alerts = [a for a in fw.alerts if a["node_id"].endswith("place_design") and a["code"] == "timing_fail"]
    assert not place_alerts or place_alerts[0]["level"] == "warning"   # estimates before route: warning


def test_messages_and_log_endpoints(tmp_path, cfg, report_cache, catalogs):
    runs = lockin(tmp_path, impl_pid=os.getpid())
    source = make(ProjectSource, runs, cfg, report_cache, catalogs)
    fw = source.snapshot(Group("project", str(runs), "lockin", {os.getpid()}), now=1_001_000.0)
    opt = stage_map(fw)["impl_1/opt_design"]
    result = source.messages(opt.id, None, 10)
    assert result["total"] == sum(opt.counts)
    assert sum(g["count"] for g in result["groups"]) == result["total"]
    assert len(result["items"]) <= 10 and result["groups"][0]["severity"] == "warning"
    only_info = source.messages(opt.id, ["info"], 1000)
    assert only_info["total"] == opt.counts[0]
    child = opt.children[2]                                # a task: its range is a subset
    assert source.messages(child.id, None, 1000)["total"] == sum(child.counts)
    excerpt = source.log_excerpt(opt.id, 50)
    assert excerpt["lines"][0].startswith("Command: opt_design") and excerpt["start_line"] == opt.line_start
    live = source.log_excerpt(stage_map(fw)["impl_1/place_design"].id, 20)
    assert len(live["lines"]) == 20 and live["end_line"] == source.logs[live["path"]].line_count
    assert source.messages("nope", None, 5) is None


def test_report_whitelist(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    source = make(ProjectSource, runs, cfg, report_cache, catalogs)
    source.snapshot(None, now=1_010_000.0)
    good = str(runs / "impl_1" / "d_1_wrapper_route_status.rpt")
    assert source.allowed_report(good) and not source.allowed_report("/etc/passwd")


def test_assign_sections_disambiguates_phys_opt(cfg):
    class S:
        def __init__(self, cmd):
            self.cmd = cmd
    sections = [S("phys_opt_design"), S("route_design"), S("phys_opt_design")]
    got = assign_sections([], sections, cfg)
    assert list(got) == ["phys_opt_design", "route_design", "post_route_phys_opt_design"]
    planned = ["place_design", "route_design", "post_route_phys_opt_design"]
    got = assign_sections(planned, [S("place_design"), S("route_design"), S("phys_opt_design")], cfg)
    assert list(got) == planned


def test_log_mode_standalone(tmp_path, cfg, report_cache, catalogs):
    log = tmp_path / "vivado.log"
    shutil.copy(FIXTURES / "qick" / "d_1_wrapper.vdi", log)
    fw = make(LogSource, log, cfg, report_cache, catalogs).snapshot(None, now=1.0)
    ids = [s.id for s in fw.flows[0].stages]
    assert ids[:3] == ["log/init_design", "log/opt_design", "log/place_design"]
    assert fw.kind == "log" and fw.status == "done"


def test_path_resolution(tmp_path):
    runs = tmp_path / "p.runs"
    (runs / "impl_1").mkdir(parents=True)
    (tmp_path / "p.xpr").write_text("")
    log = tmp_path / "x.log"
    log.write_text("")
    assert resolve_path(str(runs)) == ("project", str(runs))
    assert resolve_path(str(runs / "impl_1")) == ("project", str(runs))
    assert resolve_path(str(tmp_path / "p.xpr")) == ("project", str(runs))
    assert resolve_path(str(log)) == ("log", str(log))
    assert resolve_path(str(tmp_path / "missing")) is None
    assert runs_location("/a/lockin.runs/impl_1/x") == ("/a/lockin.runs", "impl_1")
    assert runs_location("/a/b") is None


def test_impl_only_relaunch_keeps_the_synthesis_it_builds_on(tmp_path, cfg, report_cache, catalogs):
    """A script that runs `launch_runs impl_1` after synthesis writes a new launch listing impl_1 alone."""
    runs = lockin(tmp_path)
    later = runs / ".jobs" / "vrs_config_2.xml"
    later.write_text('<?xml version="1.0"?>\n<Runs><Run Id="impl_1" FlowId="Vivado_Implementation"/></Runs>\n')
    os.utime(runs / ".jobs" / "vrs_config_1.xml", (1_000_000, 1_000_000))
    os.utime(later, (2_000_000, 2_000_000))
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=2_000_100)
    synth = fw.flows[0].stages[0]
    assert synth.id == "synth" and [c.id for c in synth.children] == ["synth/ooc", "synth_1"]


def test_launch_from_a_later_step_keeps_the_steps_it_builds_on(tmp_path, cfg, report_cache, catalogs):
    """`launch_runs impl_1 -from_step write_bitstream` rewrites the run script with that step alone."""
    runs = qick(tmp_path)
    (runs / "impl_1" / "d_1_wrapper.tcl").write_text("start_step write_bitstream\nwrite_bitstream x.bit\nend_step write_bitstream\n")
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000)
    impl = [s for s in fw.flows[0].stages if s.id.startswith("impl_1/")]
    assert [s.id.split("/")[1] for s in impl] == ["init_design", "opt_design", "place_design", "phys_opt_design",
                                                  "route_design", "write_bitstream"]
    assert {s.status for s in impl} == {"done"}


def test_relaunch_from_link_design_drops_the_sections_of_the_earlier_session(tmp_path, cfg, report_cache, catalogs):
    """-applog appends a relaunch to the same .vdi: steps the new session has not reached must not show the old one."""
    runs = qick(tmp_path)
    vdi = runs / "impl_1" / "d_1_wrapper.vdi"
    with vdi.open("a") as fh:
        fh.write("#-----------------------------------------------------------\n# Vivado v2023.2 (64-bit)\n"
                 "# Start of session at: Sat Oct 24 16:03:55 2026\n#-----------------------------------------------------------\n"
                 "Command: link_design -top d_1_wrapper -part xczu48dr-ffvg1517-2-e\n"
                 "WARNING: [Project 1-1] only in the second session\n"
                 "Command: opt_design\n")
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000)
    stages = stage_map(fw)
    for sid in ("place_design", "phys_opt_design", "route_design", "write_bitstream"):
        node = stages["impl_1/" + sid]
        assert node.counts == [0, 0, 0, 0] and (node.timing is None or node.timing.source == "report")
        assert not [c for c in node.children if not c.expected]
    assert stages["impl_1/init_design"].counts[1] == 1
    assert not [c for s in stages.values() for c in s.children if c.label.endswith("(script)")]
    source = ProjectSource(runs, cfg, report_cache, catalogs)
    source.snapshot(None, now=1_010_000)
    assert [g["count"] for g in source.raw_groups()
            if g["severity"] == "warning" and g["log"] == str(vdi)] == [1]


def test_commands_run_by_a_hook_stay_inside_their_step(tmp_path, cfg, report_cache, catalogs):
    """A post-hook re-running place/phys_opt/route (timing-closure loops) used to vanish from the flow."""
    runs = qick(tmp_path)
    vdi = runs / "impl_1" / "d_1_wrapper.vdi"
    with vdi.open("a") as fh:
        fh.write("ECO: window 0.10: route_design\nCommand: route_design -directive Explore\nStarting Routing Task\n"
                 "INFO: [Route 35-416] Intermediate Timing Summary | WNS=-3.884 | TNS=-985.414| WHS=-0.499 | THS=-151.653|\n"
                 "Ending Routing Task | Checksum: 1\nroute_design completed successfully\n"
                 "Command: phys_opt_design -directive Explore\n")
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000)
    bit = stage_map(fw)["impl_1/write_bitstream"]
    extra = [c for c in bit.children if c.kind == "command" and c.label.endswith("(script)")]
    assert [c.label for c in extra] == ["route_design (script)", "phys_opt_design (script)"]
    assert bit.line_end == extra[-1].line_end and extra[0].line_start > stage_map(fw)["impl_1/route_design"].line_end
    assert bit.timing.wns == -3.884 and not bit.timing.final       # newer than the step's own reports
