"""Non-project flows: steps planned from the Tcl script, reports named by `report_xxx -file` commands."""
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

from conftest import FIXTURES
from vmon.paths import canon
from vmon.project import LogSource
from vmon.tclscript import plan_steps, script_commands

FIXTURE = FIXTURES / "nonproject"
SESSION_START = time.mktime(time.strptime("Tue Oct 27 14:14:00 2026", "%a %b %d %H:%M:%S %Y"))
FULL_PLAN = ["synth_design", "opt_design", "place_design", "phys_opt_design", "route_design", "write_bitstream"]
LIVE = SimpleNamespace(pids={1}, launcher=None, kind="log")


def build(tmp_path, lines=None, reports_at=SESSION_START + 60):
    """The fixture build laid out as <tmp>/nonproject.tcl and <tmp>/logs/np/{vivado.log,out/}, as it ran."""
    run = tmp_path / "logs" / "np"
    shutil.copytree(FIXTURE / "out", run / "out")
    shutil.copy(FIXTURE / "nonproject.tcl", tmp_path / "nonproject.tcl")
    text = (FIXTURE / "vivado.log").read_text().replace("@RUN@", str(run)).replace("@SCRATCH@", str(tmp_path))
    log = run / "vivado.log"
    log.write_text("\n".join(text.split("\n")[:lines]) + "\n" if lines else text)
    os.utime(log, (SESSION_START + 300, SESSION_START + 300))      # finished: not growing
    for rpt in (run / "out").glob("*.rpt"):
        os.utime(rpt, (reports_at, reports_at))
    return log


def source(log, cfg, report_cache, catalogs):
    return LogSource(str(log), cfg, report_cache, catalogs)


def stages(fw):
    return {s.id.split("/")[1]: s for s in fw.flows[0].stages}


def statuses(fw):
    return [(s.id.split("/")[1], s.status) for s in fw.flows[0].stages]


def test_planned_steps_come_from_the_script(cfg):
    commands, files, variables = script_commands(str(FIXTURE / "nonproject.tcl"), None, cfg, ["part", "out"])
    assert plan_steps(commands, cfg) == FULL_PLAN
    assert variables["out"] == "out"
    assert files == [str(FIXTURE / "nonproject.tcl")]


def test_repeated_command_takes_the_next_step(cfg, tmp_path):
    script = tmp_path / "b.tcl"
    script.write_text("place_design\nphys_opt_design\nroute_design\nphys_opt_design -directive Explore\n"
                      "# power_opt_design\nputs \"opt_design\"\n")
    commands, _, _ = script_commands(str(script), None, cfg)
    assert plan_steps(commands, cfg) == ["place_design", "phys_opt_design", "route_design",
                                         "post_route_phys_opt_design"]


def test_pending_steps_are_only_the_ones_the_script_calls(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path, lines=450)
    fw = source(log, cfg, report_cache, catalogs).snapshot(LIVE, now=time.time())
    assert statuses(fw) == [("synth_design", "done"), ("opt_design", "done"), ("place_design", "running"),
                            ("phys_opt_design", "pending"), ("route_design", "pending"),
                            ("write_bitstream", "pending")]


def test_finished_log_has_no_placeholders(cfg, report_cache, catalogs, tmp_path):
    fw = source(build(tmp_path), cfg, report_cache, catalogs).snapshot(None, now=time.time())
    assert [sid for sid, _ in statuses(fw)] == FULL_PLAN
    assert stages(fw)["synth_design"].label == "Synthesis"
    assert stages(fw)["write_bitstream"].status == "failed"


def test_unreadable_script_keeps_the_guessed_plan(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path, lines=450)
    (tmp_path / "nonproject.tcl").unlink()
    fw = source(log, cfg, report_cache, catalogs).snapshot(LIVE, now=time.time())
    ids = [sid for sid, _ in statuses(fw)]
    assert "power_opt_design" not in ids[:3] and "post_route_phys_opt_design" in ids   # guessed, as before


def test_script_that_misses_a_called_command_is_not_trusted(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path)
    (tmp_path / "nonproject.tcl").write_text("synth_design -top top\nopt_design\nplace_design\n")
    fw = source(log, cfg, report_cache, catalogs).snapshot(None, now=time.time())
    assert [sid for sid, _ in statuses(fw)] == FULL_PLAN


def test_reports_are_attached_to_the_step_that_wrote_them(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path)
    src = source(log, cfg, report_cache, catalogs)
    fw = src.snapshot(None, now=time.time())
    by_step = stages(fw)
    run = log.parent
    named = {sid: [r["name"] for r in node.reports] for sid, node in by_step.items() if node.reports}
    assert named == {"synth_design": ["post_synth_util.rpt"], "place_design": ["post_place_util.rpt"],
                     "route_design": ["post_route_timing_summary.rpt", "post_route_util.rpt"]}
    timing = next(r for r in by_step["route_design"].reports if r["kind"] == "timing_summary")
    assert timing["summary"]["wns"] is not None and not timing["stale"]
    assert canon(timing["path"]) == canon(str(run / "out" / "post_route_timing_summary.rpt"))
    assert by_step["route_design"].timing.wns == timing["summary"]["wns"]
    assert by_step["route_design"].timing.final
    assert {canon(p) for p in src.report_paths} == {canon(str(run / "out" / n)) for n in (
        "post_synth_util.rpt", "post_place_util.rpt", "post_route_timing_summary.rpt", "post_route_util.rpt")}


def test_report_older_than_the_session_is_stale(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path, reports_at=SESSION_START - 3600)
    fw = source(log, cfg, report_cache, catalogs).snapshot(None, now=time.time())
    reports = [r for node in stages(fw).values() for r in node.reports]
    assert reports and all(r["stale"] for r in reports)


def test_missing_report_file_is_skipped(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path)
    (log.parent / "out" / "post_place_util.rpt").unlink()
    fw = source(log, cfg, report_cache, catalogs).snapshot(None, now=time.time())
    assert stages(fw)["place_design"].reports == []


def test_sourced_script_and_cycle(cfg, tmp_path):
    (tmp_path / "main.tcl").write_text("read_verilog x.v\nsource steps.tcl\nsource -notrace {extra.tcl}\n"
                                       "source [file join [file dirname [info script]] more.tcl]\n")
    (tmp_path / "steps.tcl").write_text("synth_design -top t\nopt_design\nsource main.tcl\n")   # cycle
    (tmp_path / "extra.tcl").write_text("if {1} { place_design }\n")
    (tmp_path / "more.tcl").write_text("catch {route_design}\n# write_bitstream\n")
    commands, files, _ = script_commands("main.tcl", str(tmp_path), cfg)
    assert plan_steps(commands, cfg) == ["synth_design", "opt_design", "place_design", "route_design"]
    assert len(files) == 4


def test_launcher_script_and_cwd_beat_the_log_banner(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path, lines=450)
    text = "\n".join(l for l in log.read_text().split("\n")[13:]) + "\n"
    log.write_text(text)                          # no banner: script and directory come from the launcher
    launcher = {"pid": 1, "log": str(log), "script": "../../nonproject.tcl", "cwd": str(log.parent),
                "tclargs": ["xc7a35tcpg236-1", "out"]}
    group = SimpleNamespace(pids={1}, launcher=launcher, kind="log")
    fw = source(log, cfg, report_cache, catalogs).snapshot(group, now=time.time())
    assert [sid for sid, _ in statuses(fw)][-3:] == ["phys_opt_design", "route_design", "write_bitstream"]
    assert stages(fw)["synth_design"].reports[0]["name"] == "post_synth_util.rpt"


def test_appended_sessions_keep_the_newest(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path)
    log.write_text(log.read_text() + log.read_text())    # -applog: the same build run again in the same file
    fw = source(log, cfg, report_cache, catalogs).snapshot(None, now=time.time())
    assert [sid for sid, _ in statuses(fw)] == FULL_PLAN
    assert stages(fw)["synth_design"].line_start > 800
