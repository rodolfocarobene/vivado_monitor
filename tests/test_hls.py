"""Vitis HLS: discovery of vitis_hls and its Vivado child, the flow parsed from vitis_hls.log (one real 2023.2
csynth_design + export_design run), failures, planned steps from the Tcl script, and the csynth report."""
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import FIXTURES
from vmon import procinfo
from vmon.discovery import Discovery
from vmon.hls import hls_config, resolve
from vmon.hls_source import HlsSource
from vmon.monitor import resolve_path
from vmon.paths import canon
from vmon.procinfo_linux import LinuxBackend
from vmon.procinfo_windows import WindowsBackend

FIXTURE = FIXTURES / "hls"
SESSION_START = time.mktime(time.strptime("Tue Oct 27 14:24:00 2026", "%a %b %d %H:%M:%S %Y"))
CSYNTH_PHASES = ["C/C++ compile and analysis", "Code transformations", "Scheduling", "Binding", "RTL generation",
                 "VHDL / Verilog output"]


def build(tmp_path, edit=None, reports=True):
    """The fixture laid out as <tmp>/hls/run.tcl and <tmp>/logs/hls_dot/{vitis_hls.log,dot_prj/}, as it ran."""
    run = tmp_path / "logs" / "hls_dot"
    (tmp_path / "hls").mkdir()
    shutil.copy(FIXTURE / "run.tcl", tmp_path / "hls" / "run.tcl")
    (run / "dot_prj").mkdir(parents=True)
    if reports:
        shutil.copytree(FIXTURE / "dot_prj" / "sol1", run / "dot_prj" / "sol1")
    text = (FIXTURE / "vitis_hls.log").read_text().replace("@RUN@", str(run))
    if edit:
        text = edit(text)
    log = run / "vitis_hls.log"
    log.write_text(text)
    for path in [log, *run.rglob("*.xml"), *run.rglob("vivado.log")]:
        os.utime(path, (SESSION_START + 30, SESSION_START + 30))      # finished: not growing
    return log


def lines_until(marker, extra=""):
    def edit(text):
        head = text.split(marker)[0]
        return head + (extra if extra else "")
    return edit


def snapshot(log, cfg, report_cache, catalogs, group=None, now=None):
    return HlsSource(str(log), cfg, report_cache, catalogs).snapshot(group, now)


def stages(fw):
    return {s.id.split("/")[1]: s for s in fw.flows[0].stages}


# ---------------------------------------------------------------- the parsed flow
def test_flow_steps_phases_and_counts(cfg, report_cache, catalogs, tmp_path):
    fw = snapshot(build(tmp_path), cfg, report_cache, catalogs)
    assert fw.kind == "hls" and fw.name == "dot_prj/sol1" and fw.status == "done" and not fw.live
    assert fw.vivado_version == "2023.2" and fw.started_at == SESSION_START
    assert fw.elapsed_s == pytest.approx(27.06)
    steps = stages(fw)
    assert list(steps) == ["csynth_design", "export_design"]
    synth, export = steps["csynth_design"], steps["export_design"]
    assert (synth.label, synth.status, export.status) == ("C Synthesis", "done", "done")
    assert synth.elapsed_s == pytest.approx(7.71) and export.elapsed_s == pytest.approx(18.24)
    phases = [c for c in synth.children if c.kind == "phase"]
    assert [p.label for p in phases] == CSYNTH_PHASES and all(p.status == "done" for p in phases)
    assert phases[0].elapsed_s == pytest.approx(7.31) and phases[2].elapsed_s == pytest.approx(0.05)
    assert [c.label for c in export.children] == ["Package IP (Vivado)", "vivado.log"]
    assert synth.counts[1] == 2 and fw.counts[3] == 0                  # [info, warning, critical, error]
    assert fw.counts[1] == 2 and fw.counts[0] > 50 and fw.health == "warning"
    assert fw.info["top"] == "dot" and fw.info["part"] == "xc7a35tcpg236-1"


def test_messages_and_log_ranges_work_through_the_source(cfg, report_cache, catalogs, tmp_path):
    source = HlsSource(str(build(tmp_path)), cfg, report_cache, catalogs)
    source.snapshot(None)
    found = source.messages("hls/csynth_design", ["warning"])
    assert {g["id"] for g in found["groups"]} == {"HLS 200-871", "HLS 200-1016"}
    assert source.log_excerpt("hls/csynth_design/p-schedule")["lines"][0].startswith("INFO: [SCHED 204-11]")
    vlog = source.log_excerpt("hls/export_design/vivado-log")
    assert vlog["path"].endswith("vivado.log") and any("Exiting Vivado" in line for line in vlog["lines"])


def test_estimated_timing_from_the_report(cfg, report_cache, catalogs, tmp_path):
    node = stages(snapshot(build(tmp_path), cfg, report_cache, catalogs))["csynth_design"]
    assert node.timing.wns == pytest.approx(-1.601) and node.timing.met is False
    assert node.timing.source == "report" and node.timing.final is False and "estimated" in node.timing.stage
    assert any(a["code"] == "timing_fail" and "estimated" in a["message"] for a in node.alerts)


def test_estimated_timing_from_the_log_alone(cfg, report_cache, catalogs, tmp_path):
    fw = snapshot(build(tmp_path, reports=False), cfg, report_cache, catalogs)
    node = stages(fw)["csynth_design"]
    assert node.timing.source == "log" and node.timing.wns == pytest.approx(-1.601)      # effective budget - estimate
    assert node.reports == [] and fw.timing is not None

    def no_warning(text):                  # tool met timing: only the Fmax line is left (clock 5 ns, 190.46 MHz)
        return "\n".join(l for l in text.split("\n") if "HLS 200-871" not in l)
    (tmp_path / "b").mkdir()
    node = stages(snapshot(build(tmp_path / "b", no_warning, reports=False), cfg, report_cache, catalogs))["csynth_design"]
    assert node.timing.wns == pytest.approx(round(5.0 - 1000 / 190.46, 3), abs=1e-3)


def test_csynth_report_summary(cfg, report_cache, catalogs, tmp_path):
    node = stages(snapshot(build(tmp_path), cfg, report_cache, catalogs))["csynth_design"]
    (report,) = node.reports
    assert report["kind"] == "hls_csynth" and report["name"] == "csynth.xml" and not report["stale"]
    assert report["path"] == canon(tmp_path / "logs" / "hls_dot" / "dot_prj" / "sol1" / "syn" / "report" / "csynth.xml")
    summary = report["summary"]
    assert (summary["target_ns"], summary["uncertainty_ns"], summary["estimated_ns"]) == (5.0, 1.35, 5.251)
    assert summary["slack_ns"] == pytest.approx(-1.601) and summary["fmax_mhz"] == pytest.approx(190.44, abs=0.05)
    assert (summary["latency_min"], summary["latency_max"], summary["interval_min"]) == (72, 72, 73)
    resources = {r["name"]: r for r in summary["resources"]}
    assert (resources["DSP"]["used"], resources["DSP"]["available"]) == (3, 90)
    assert resources["LUT"]["used"] == 160 and resources["URAM"]["pct"] is None
    assert summary["loops"] == [{"name": "VITIS_LOOP_4_1", "latency": 70, "trip_count": 64, "ii": 1, "depth": 8,
                                 "slack_ns": 3.65}]
    source = HlsSource(str(tmp_path / "logs" / "hls_dot" / "vitis_hls.log"), cfg, report_cache, catalogs)
    source.snapshot(None)
    assert source.allowed_report(report["path"])


def test_csynth_resources_fill_the_utilization_card(cfg, report_cache, catalogs, tmp_path):
    util = snapshot(build(tmp_path), cfg, report_cache, catalogs).utilization
    assert util["report"] == "csynth.xml" and util["label"] == "Resource estimate"
    assert {r["name"]: r["used"] for r in util["rows"]}["DSP"] == 3
    (tmp_path / "b").mkdir()
    assert snapshot(build(tmp_path / "b", reports=False), cfg, report_cache, catalogs).utilization is None


def test_report_older_than_the_session_is_stale(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path)
    xml = tmp_path / "logs" / "hls_dot" / "dot_prj" / "sol1" / "syn" / "report" / "csynth.xml"
    os.utime(xml, (SESSION_START - 3600, SESSION_START - 3600))
    node = stages(snapshot(log, cfg, report_cache, catalogs))["csynth_design"]
    assert node.reports[0]["stale"] and node.timing.source == "log"


# ---------------------------------------------------------------- failures
def test_failed_csynth_from_an_edited_log(cfg, report_cache, catalogs, tmp_path):
    error = ("ERROR: [HLS 200-70] Compilation errors found: Pass Failed for 'Transform: code'\n"
             "ERROR: [HLS 200-1715] Encountered problem during source synthesis\n"
             "INFO: [Common 17-206] Exiting vitis_hls at Tue Oct 27 14:24:10 2026...\n")
    log = build(tmp_path, lines_until("INFO: [SCHED 204-11]", error), reports=False)
    fw = snapshot(log, cfg, report_cache, catalogs)
    steps = stages(fw)
    assert list(steps) == ["csynth_design"] and fw.status == "failed" and fw.health == "error"
    synth = steps["csynth_design"]
    assert synth.status == "failed" and synth.counts[3] == 2
    assert synth.failure["reason"] == "Error" and "Pass Failed" in synth.failure["details"][0]
    phases = [c for c in synth.children if c.kind == "phase"]
    assert [(p.label, p.status) for p in phases] == [("C/C++ compile and analysis", "done"),
                                                     ("Code transformations", "failed")]
    assert any(a["code"] == "step_failed" for a in fw.alerts)


def test_a_log_that_stops_with_no_process_is_stopped(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path, lines_until("INFO: [SCHED 204-11]"), reports=False)
    fw = snapshot(log, cfg, report_cache, catalogs)
    assert fw.status == "stopped" and stages(fw)["csynth_design"].status == "stopped"


def test_running_step_with_a_live_process(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path, lines_until("INFO: [SCHED 204-11]"), reports=False)
    live = SimpleNamespace(pids={1}, launcher=None, kind="hls")
    started = snapshot(log, cfg, report_cache, catalogs, live).started_at   # log local time: pin "now" to it (CI is UTC)
    fw = snapshot(log, cfg, report_cache, catalogs, live, now=started + 60)
    assert fw.status == "running" and fw.live and fw.current["label"].endswith("Code transformations")
    synth = stages(fw)["csynth_design"]
    assert synth.status == "running" and synth.elapsed_s > 0


# ---------------------------------------------------------------- planned steps from the script
def test_planned_steps_come_from_the_tcl_script(cfg, report_cache, catalogs, tmp_path):
    log = build(tmp_path, lines_until("INFO: [HLS 200-1510] Running: export_design"), reports=False)
    source = HlsSource(str(log), cfg, report_cache, catalogs)
    live = SimpleNamespace(pids={1}, launcher={"script": "../../hls/run.tcl", "cwd": str(log.parent)}, kind="hls")
    fw = source.snapshot(live)
    assert [(k, s.status) for k, s in stages(fw).items()] == [("csynth_design", "done"), ("export_design", "pending")]
    assert source._planned(None, source.logs[source.path].parser.meta) == ["csynth_design", "export_design"]
    assert source.snapshot(None).status == "done"                        # nothing pending once the process is gone
    assert [s.id for s in source.snapshot(None).flows[0].stages] == ["hls/csynth_design"]


def test_script_commands_use_the_hls_vocabulary(cfg):
    from vmon.tclscript import script_commands
    commands, _files, _vars = script_commands(str(FIXTURE / "run.tcl"), None, hls_config(cfg).script_cfg)
    assert commands == ["csynth_design", "export_design"]


# ---------------------------------------------------------------- adding a path by hand
def test_manual_paths_open_as_hls(tmp_path):
    log = build(tmp_path)
    run = log.parent
    expected = ("hls", canon(log))
    assert resolve_path(str(log)) == expected                             # the log
    assert resolve_path(str(run)) == expected                             # the directory holding it
    (run / "dot_prj" / "hls.app").write_text("<project/>")
    assert resolve_path(str(run / "dot_prj")) == expected                 # the project dir
    assert resolve_path(str(run / "dot_prj" / "sol1")) == expected        # a solution dir
    assert resolve(tmp_path / "hls") is None


def test_project_dir_without_a_main_log_uses_the_solution_log(tmp_path):
    sol = tmp_path / "p_prj" / "s1"
    sol.mkdir(parents=True)
    (tmp_path / "p_prj" / "hls.app").write_text("")
    (sol / "s1.log").write_text("INFO: [HLS 200-1510] Running: csynth_design\n")
    assert resolve_path(str(tmp_path / "p_prj")) == ("hls", canon(sol / "s1.log"))


def test_other_logs_stay_logs(tmp_path):
    vivado = tmp_path / "vivado.log"
    vivado.write_text("****** Vivado v2023.2 (64-bit)\nINFO: [Common 17-206] Exiting Vivado\n")
    assert resolve_path(str(vivado)) == ("log", canon(vivado))
    odd = tmp_path / "x.log"
    odd.write_text("hello\n")
    assert resolve_path(str(odd)) == ("log", canon(odd))


# ---------------------------------------------------------------- discovery with fake process lists
def discover_with(cfg, vivados, hls, parent_of):
    class Backend(procinfo.NullBackend):
        name = "windows" if sys.platform == "win32" else "linux"      # picks the HLS image names of this platform

        def vivado_processes(self):
            return vivados

        def hls_processes(self, names):
            return [p for p in hls if p["name"] in names]

        def process_table(self):
            return parent_of
    procinfo.set_backend(Backend())
    try:
        return Discovery(cfg).discover()
    finally:
        procinfo.set_backend(None)


def hls_proc(pid, ppid, cwd, args=None, name=None):
    name = name or ("vitis_hls.exe" if sys.platform == "win32" else "vitis_hls")
    return {"pid": pid, "ppid": ppid, "args": args or ["vitis_hls", "-f", "run.tcl"], "cwd": str(cwd), "name": name}


def image(name):
    return name + (".exe" if sys.platform == "win32" else "")


def vivado_proc(pid, cwd):
    return {"pid": pid, "args": ["vivado", "-notrace", "-mode", "batch", "-source", "run_ippack.tcl"], "cwd": str(cwd)}


def test_vitis_hls_with_its_packaging_vivado_is_one_firmware(cfg, tmp_path):
    log = build(tmp_path)
    ip = log.parent / "dot_prj" / "sol1" / "impl" / "ip"
    (ip / "vivado.log").write_text("# Vivado\n")                          # would be a firmware of its own otherwise
    groups = discover_with(cfg, [vivado_proc(101, ip)], [hls_proc(100, 1, log.parent, ["vitis_hls", "-f", "../../hls/run.tcl"])],
                           {100: 1, 101: 100})
    assert [(g.kind, g.path) for g in groups] == [("hls", canon(log))]
    group = groups[0]
    assert group.pids == {100, 101}
    assert group.launcher["script"] == "../../hls/run.tcl" and group.launcher["cwd"] == str(log.parent)


def test_orphan_packaging_vivado_joins_by_its_directory(cfg, tmp_path):
    log = build(tmp_path)
    ip = log.parent / "dot_prj" / "sol1" / "impl" / "ip"
    (ip / "vivado.log").write_text("# Vivado\n")
    groups = discover_with(cfg, [vivado_proc(101, ip)], [hls_proc(100, 1, log.parent)], {100: 1, 101: 1})
    assert [g.kind for g in groups] == ["hls"] and groups[0].pids == {100, 101}


def test_a_vivado_elsewhere_is_not_taken(cfg, tmp_path):
    log = build(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "vivado.log").write_text("# Vivado\n")
    groups = discover_with(cfg, [vivado_proc(101, other)], [hls_proc(100, 1, log.parent)], {100: 1, 101: 1})
    assert sorted(g.kind for g in groups) == ["hls", "log"]


def test_log_flag_and_missing_log(cfg, tmp_path):
    log = build(tmp_path)
    custom = log.parent / "mine.log"
    shutil.copy(log, custom)
    args = ["vitis_hls", "-l", "mine.log", "-f", "run.tcl", "-tclargs", "a", "b"]
    groups = discover_with(cfg, [], [hls_proc(100, 1, log.parent, args)], {100: 1})
    assert [(g.kind, g.path) for g in groups] == [("hls", canon(custom))]
    assert groups[0].launcher["tclargs"] == ["a", "b"]
    custom.unlink()
    log.unlink()
    assert discover_with(cfg, [], [hls_proc(100, 1, log.parent, args)], {100: 1}) == []     # no log yet: no firmware


def test_vitis_run_is_an_hls_engine_and_vpp_joins_the_build_it_starts(cfg, tmp_path):
    log = build(tmp_path)
    procs = [hls_proc(50, 1, tmp_path, ["v++", "-c"], image("v++")),
             hls_proc(100, 50, log.parent, ["vitis-run", "--mode", "hls", "--tcl", "run.tcl"], image("vitis-run"))]
    groups = discover_with(cfg, [], procs, {50: 1, 100: 50})
    assert [(g.kind, g.path) for g in groups] == [("hls", canon(log))]
    assert groups[0].pids == {50, 100} and groups[0].launcher["script"] == "run.tcl"


def test_vpp_joins_the_vivado_project_it_runs(cfg, tmp_path):
    prj = tmp_path / "_x" / "link" / "vivado" / "vpl" / "prj" / "prj.runs" / "impl_1"
    prj.mkdir(parents=True)
    vivado = {"pid": 200, "args": ["vivado", "-log", "runme.log", "-mode", "batch"], "cwd": str(prj)}
    groups = discover_with(cfg, [vivado], [hls_proc(50, 1, tmp_path, ["v++", "-l"], image("v++"))], {50: 1, 100: 50, 200: 100})
    assert [g.kind for g in groups] == ["project"] and groups[0].pids == {200, 50}


# ---------------------------------------------------------------- platform backends
class FakeWindowsApi:
    def process_entries(self):
        return [(4, 0, "System"), (100, 4, "cmd.exe"), (200, 100, "Vitis_HLS.exe"), (300, 200, "vivado.exe"),
                (400, 100, "v++.exe")]

    def command_line_and_cwd(self, pid):
        return {200: ('"C:\\X\\vitis_hls.exe" -f run.tcl -l my.log', "C:\\w\\hls_dot"), 400: (None, None)}.get(pid, (None, None))


def test_windows_backend_lists_hls_images(cfg):
    names = hls_config(cfg).process_names(windows=True)
    assert names == {"vitis_hls.exe": "engine", "vitis-run.exe": "engine", "v++.exe": "wrapper"}
    found = WindowsBackend(FakeWindowsApi()).hls_processes(list(names))
    assert [(p["pid"], p["ppid"], p["name"]) for p in found] == [(200, 100, "vitis_hls.exe"), (400, 100, "v++.exe")]
    assert found[0]["args"] == ["C:\\X\\vitis_hls.exe", "-f", "run.tcl", "-l", "my.log"] and found[0]["cwd"] == "C:\\w\\hls_dot"
    assert found[1]["args"] == [] and found[1]["cwd"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="needs symlinks into a fake /proc")
def test_linux_backend_finds_the_unwrapped_binary_but_not_wrappers(tmp_path):
    def fake(pid, comm, exe, args, cwd, ppid=1):
        folder = tmp_path / str(pid)
        folder.mkdir()
        (folder / "comm").write_text(comm + "\n")
        (folder / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
        (folder / "stat").write_text("%d (%s) S %d 1 1 0 0 0 0 0 0 0 5 6 0 0\n" % (pid, comm, ppid))
        os.symlink(exe, folder / "exe")
        os.symlink(cwd, folder / "cwd")
    fake(10, "vitis_hls", "/opt/X/bin/unwrapped/lnx64.o/vitis_hls", ["/opt/X/bin/unwrapped/lnx64.o/vitis_hls", "-f", "a.tcl"],
         "/w")
    fake(11, "vitis_hls", "/usr/bin/bash", ["/bin/bash", "/opt/X/bin/vitis_hls", "-f", "a.tcl"], "/w")        # the wrapper script
    fake(12, "v++", "/opt/V/bin/unwrapped/lnx64.o/v++", ["v++", "-l"], "/w", ppid=10)
    fake(13, "vivado", "/opt/V/bin/unwrapped/lnx64.o/vivado", ["vivado"], "/w")
    backend = LinuxBackend(str(tmp_path))
    found = backend.hls_processes(["vitis_hls", "vitis-run", "v++"])
    assert sorted((p["pid"], p["name"], p["ppid"], p["cwd"]) for p in found) == [(10, "vitis_hls", 1, "/w"), (12, "v++", 10, "/w")]
    assert [p["pid"] for p in backend.vivado_processes()] == [13] and "name" not in backend.vivado_processes()[0]
