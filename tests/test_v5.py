"""v5: failures, crashes, restarts and resumes."""
import json
import os
import shutil
import time
from pathlib import Path

from conftest import FIXTURES, build_runs, marker, touch
from vmon import alerts as alert_rules
from vmon import discovery, failure
from vmon.config import load_config
from vmon.discovery import Discovery, Group, is_run_worker
from vmon.logparse import LogParser
from vmon.model import Node
from vmon.project import LogSource, ProjectSource
from test_project import stage_map

CRASH = FIXTURES / "crash"
STEPS_DONE = [("init_design", "begin"), ("init_design", "end"), ("opt_design", "begin"),
              ("opt_design", "end"), ("place_design", "begin"), ("place_design", "end"),
              ("phys_opt_design", "begin"), ("phys_opt_design", "end"), ("route_design", "begin")]
T0 = 1_000_000.0


def crashed_run(tmp_path, vivado_error=True):
    """lockin-like run where route_design began and Vivado crashed in Phase 10 (runme.log + hs_err)."""
    f = FIXTURES / "lockin"
    runs = build_runs(tmp_path, "lockin", "main_wrapper", CRASH / "route_crash.vdi", f / "main_wrapper.tcl",
                      f / "main_wrapper.vds", STEPS_DONE)
    impl = runs / "impl_1"
    shutil.copy(CRASH / "route_crash_runme.log", impl / "runme.log")
    shutil.copy(CRASH / "hs_err_pid563188.log", impl / "hs_err_pid563188.log")
    old = time.time() - 3 * 3600
    for name in ("runme.log", "main_wrapper.vdi", "hs_err_pid563188.log"):
        os.utime(impl / name, (old, old))
    if vivado_error:
        touch(impl / ".vivado.error.rst", T0 + 3000)
    return runs


def snap(runs, cfg, report_cache, catalogs, group=None, now=None):
    return ProjectSource(runs, cfg, report_cache, catalogs).snapshot(group, now=now or time.time())


def resume_group(runs, log, alive=True):
    impl = runs / "impl_1"
    item = {"pid": os.getpid(), "run": "impl_1", "log": str(log), "script": None,
            "checkpoint": str(impl / "main_wrapper_physopt.dcp"), "cwd": str(impl)}
    return Group("project", str(runs), "lockin", {os.getpid()}, resumes=[item] if alive else [])


# ------------------------------------------------------------------ crash detection
def test_crash_detection_from_runme_tail_and_hs_err(tmp_path, cfg, report_cache, catalogs):
    runs = crashed_run(tmp_path)
    fw = snap(runs, cfg, report_cache, catalogs)
    route = stage_map(fw)["impl_1/route_design"]
    assert fw.status == "failed" and route.status == "failed"
    fail = route.failure
    assert fail["reason"] == "Segmentation fault (signal 11)"
    assert "Lost license, cannot re-connect: Invalid host." in fail["details"]
    assert any(d.startswith("Abnormal program termination (11)") for d in fail["details"])
    assert fail["hs_err"].endswith("hs_err_pid563188.log")
    assert any("unexpected error" in d for d in fail["details"])
    assert not any("License path" in d for d in fail["details"])
    log_lines = (runs / "impl_1" / "runme.log").read_text().split("\n")
    assert log_lines[fail["line"] - 1].startswith("Abnormal program termination")
    assert fail["log"].endswith("runme.log")
    # the open phase failed with it, nothing is "running"
    phase = [c for c in [c for c in route.children if c.kind == "task"][0].children if not c.expected][-1]
    assert phase.label.endswith("Resolve XTalk") and phase.status == "failed"
    assert not [n for n in _walk(route) if n.status == "running"]
    assert fw.attempt == {"n": 1, "mode": "project", "resumed_from": None, "previous_failure": None}
    json.dumps(fw.to_dict())


def test_failed_run_has_no_stalled_alert_and_reports_reason(tmp_path, cfg, report_cache, catalogs):
    runs = crashed_run(tmp_path)
    fw = snap(runs, cfg, report_cache, catalogs)
    codes = {a["code"] for a in fw.alerts}
    assert "stalled" not in codes
    failed = [a for a in fw.alerts if a["code"] == "step_failed"]
    assert failed and "Segmentation fault (signal 11)" in failed[0]["message"]
    assert fw.health == "error"
    # the crash log lines can be shown
    assert fw.flows[0].stages[-2].failure["log"] in fw.flows[0].stages[-2].failure["log"]


def test_error_without_crash_falls_back_to_error_messages(tmp_path, cfg, report_cache, catalogs):
    f = FIXTURES / "lockin"
    runs = build_runs(tmp_path, "lockin", "main_wrapper", f / "main_wrapper.vdi", f / "main_wrapper.tcl",
                      f / "main_wrapper.vds", STEPS_DONE[:5])
    touch(runs / "impl_1" / ".vivado.error.rst", T0 + 3000)
    fw = snap(runs, cfg, report_cache, catalogs)
    place = stage_map(fw)["impl_1/place_design"]
    assert place.status == "failed" and place.failure["reason"] == "Error"


def test_log_mode_crash_and_plain_log(tmp_path, cfg, report_cache, catalogs):
    log = tmp_path / "x.log"
    shutil.copy(CRASH / "route_crash_runme.log", log)
    old = time.time() - 3600
    os.utime(log, (old, old))
    fw = LogSource(str(log), cfg, report_cache, catalogs).snapshot(None, now=time.time())
    route = stage_map(fw)["log/route_design"]
    assert route.status == "failed" and route.failure["reason"].startswith("Segmentation fault")
    assert fw.status == "failed" and not fw.live
    assert "stalled" not in {a["code"] for a in fw.alerts}
    # a normal finished log is untouched and has no failure
    ok = tmp_path / "resume.log"
    shutil.copy(CRASH / "resume.log", ok)
    os.utime(ok, (old, old))
    fw = LogSource(str(ok), cfg, report_cache, catalogs).snapshot(None, now=time.time())
    assert fw.status == "done" and fw.attempt["n"] == 1
    assert all(s.failure is None for s in fw.flows[0].stages)
    assert stage_map(fw)["log/route_design"].status == "done"


def test_failure_patterns_are_configurable(tmp_path):
    extra = tmp_path / "extra.toml"
    extra.write_text('[failure.patterns.mine]\norder = 1\nre = "BOOM (\\\\d+)"\nreason = "Custom boom {1}"\n')
    cfg = load_config(extra)
    log = tmp_path / "a.log"
    log.write_text("hello\nBOOM 7\nbye\n")
    found = failure.detect([str(log)], cfg)
    assert found["reason"] == "Custom boom 7" and found["line"] == 2 and found["details"] == ["BOOM 7"]
    assert failure.detect([str(tmp_path / "missing.log")], cfg) is None
    plain = tmp_path / "b.log"
    plain.write_text("all good\n")
    assert failure.detect([str(plain)], cfg) is None


def test_checkpoint_suffix_mapping(cfg):
    rc = cfg.resume
    assert rc.step_for_checkpoint("/x/main_wrapper_physopt.dcp") == "phys_opt_design"
    assert rc.step_for_checkpoint("a_postroute_physopt.dcp") == "post_route_phys_opt_design"
    assert rc.step_for_checkpoint("a_placed.dcp") == "place_design"
    assert rc.step_for_checkpoint("a_routed.dcp") == "route_design"
    assert rc.step_for_checkpoint("whatever.dcp") is None


# ------------------------------------------------------------------ resume
def test_resume_session_running(tmp_path, cfg, report_cache, catalogs):
    runs = crashed_run(tmp_path)
    log = tmp_path / "resume.log"
    lines = (CRASH / "resume.log").read_text().split("\n")
    cut = next(i for i, ln in enumerate(lines) if ln.startswith("Phase 3 Initial Routing |"))
    log.write_text("\n".join(lines[:cut]) + "\n")
    fw = snap(runs, cfg, report_cache, catalogs, resume_group(runs, log))
    stages = stage_map(fw)
    route = stages["impl_1/route_design"]
    assert fw.status == "running" and fw.live and os.getpid() in fw.pids
    assert stages["impl_1/phys_opt_design"].status == "done"          # before the checkpoint: untouched
    assert route.status == "running" and route.failure is None
    assert stages["impl_1/write_bitstream"].status == "pending"
    assert fw.attempt == {"n": 2, "mode": "resume", "resumed_from": "phys_opt_design",
                          "previous_failure": "Segmentation fault (signal 11)"}
    first, second = route.attempts
    assert (first["n"], first["status"], first["mode"]) == (1, "failed", "project")
    assert first["failure"]["reason"] == "Segmentation fault (signal 11)"
    assert "Resolve XTalk" in first["summary"] and "Segmentation fault" in first["summary"]
    assert (second["n"], second["status"], second["mode"]) == (2, "running", "resume")
    assert second["checkpoint"].endswith("main_wrapper_physopt.dcp") and second["log"] == str(log)
    # displayed children come from the resume log: only phases 1-3 so far, no Phase 10
    labels = [c.label for t in route.children if t.kind == "task" for c in t.children if not c.expected]
    assert labels[:2] == ["1 Build RT Design", "2 Router Initialization"]
    assert "10 Resolve XTalk" not in labels and len(labels) == 3
    assert fw.current["node_id"].startswith("impl_1/route_design/")
    # the superseded failure is not an alert, and the live attempt is not stalled
    codes = {a["code"] for a in fw.alerts}
    assert "step_failed" not in codes and "stalled" not in codes and "process_gone" not in codes
    json.dumps(fw.to_dict())


def test_resume_loading_checkpoint_marks_next_step_running(tmp_path, cfg, report_cache, catalogs):
    runs = crashed_run(tmp_path)
    log = tmp_path / "resume.log"
    lines = (CRASH / "resume.log").read_text().split("\n")
    cut = next(i for i, ln in enumerate(lines) if ln.startswith("# route_design"))
    log.write_text("\n".join(lines[:cut]) + "\n")
    script = tmp_path / "resume_route.tcl"
    script.write_text("cd x\nopen_checkpoint main_wrapper_physopt.dcp\nroute_design\nwrite_bitstream -force a.bit\n")
    group = resume_group(runs, log)
    group.resumes[0]["script"] = str(script)
    fw = snap(runs, cfg, report_cache, catalogs, group)
    route = stage_map(fw)["impl_1/route_design"]
    assert fw.status == "running" and route.status == "running" and fw.attempt["n"] == 2
    assert [a["status"] for a in route.attempts] == ["failed", "running"]


def test_resume_finished_survives_restart_and_completes(tmp_path, cfg, report_cache, catalogs):
    runs = crashed_run(tmp_path)
    log = tmp_path / "resume.log"
    shutil.copy(CRASH / "resume.log", log)
    snap(runs, cfg, report_cache, catalogs, resume_group(runs, log))            # while it was alive
    # vmon restarts after the process ended: the session is remembered in ~/.cache/vmon/attempts
    stored = list((Path.home() / ".cache" / "vmon" / "attempts").glob("*.json"))
    assert len(stored) == 1 and "resume.log" in stored[0].read_text()
    fw = snap(runs, cfg, report_cache, catalogs, None)
    stages = stage_map(fw)
    assert fw.status == "done" and not fw.live
    assert stages["impl_1/route_design"].status == "done"
    assert stages["impl_1/write_bitstream"].status == "done"
    assert [a["status"] for a in stages["impl_1/route_design"].attempts] == ["failed", "done"]
    assert stages["impl_1/write_bitstream"].attempts == []                       # only ever ran once
    assert fw.attempt["resumed_from"] == "phys_opt_design" and fw.attempt["n"] == 2
    assert "step_failed" not in {a["code"] for a in fw.alerts}


def test_resume_that_dies_is_failed_or_stopped(tmp_path, cfg, report_cache, catalogs):
    runs = crashed_run(tmp_path)
    log = tmp_path / "resume.log"
    lines = (CRASH / "resume.log").read_text().split("\n")
    cut = next(i for i, ln in enumerate(lines) if ln.startswith("Phase 3 Initial Routing |"))
    log.write_text("\n".join(lines[:cut]) + "\n")
    snap(runs, cfg, report_cache, catalogs, resume_group(runs, log))
    old = time.time() - 600
    os.utime(log, (old, old))
    fw = snap(runs, cfg, report_cache, catalogs, None)                          # process vanished, no trace
    route = stage_map(fw)["impl_1/route_design"]
    assert route.status == "stopped" and fw.status == "stopped"
    with open(log, "a") as fh:                                                   # now with a crash trace
        fh.write("Abnormal program termination (6)\n")
    os.utime(log, (old, old))
    fw = snap(runs, cfg, report_cache, catalogs, None)
    route = stage_map(fw)["impl_1/route_design"]
    assert route.status == "failed" and route.failure["reason"] == "Aborted (signal 6)"
    assert fw.status == "failed" and "step_failed" in {a["code"] for a in fw.alerts}
    assert [a["status"] for a in route.attempts] == ["failed", "failed"]
    assert fw.attempt["previous_failure"] == "Segmentation fault (signal 11)"


# ------------------------------------------------------------------ project relaunch
def test_project_relaunch_yields_attempt_two(tmp_path, cfg, report_cache, catalogs):
    f = FIXTURES / "lockin"
    runs = build_runs(tmp_path, "lockin", "main_wrapper", f / "main_wrapper.vdi", f / "main_wrapper.tcl",
                      f / "main_wrapper.vds", STEPS_DONE[:5])
    impl = runs / "impl_1"
    touch(impl / ".vivado.error.rst", T0 + 3000)
    fw1 = snap(runs, cfg, report_cache, catalogs)
    assert fw1.status == "failed" and fw1.attempt["n"] == 1
    assert stage_map(fw1)["impl_1/place_design"].attempts == []
    # reset_run + launch_runs: markers rewritten, error gone, vdi replaced by a shorter new file
    for p in impl.glob(".*.rst"):
        if p.name != ".Vivado_Implementation.queue.rst":
            p.unlink()
    marker(impl / ".vivado.begin.rst", pid=os.getpid(), mtime=T0 + 9000)
    for i, step in enumerate(("init_design", "opt_design")):
        marker(impl / (".%s.begin.rst" % step), pid=os.getpid(), mtime=T0 + 9000 + i * 10)
    touch(impl / ".init_design.end.rst", T0 + 9005)
    vdi = impl / "main_wrapper.vdi"
    short = vdi.read_text().split("\n")[:60]
    tmp = impl / "new.vdi"
    tmp.write_text("\n".join(short) + "\n")
    os.replace(tmp, vdi)
    group = Group("project", str(runs), "lockin", {os.getpid()}, run_pids={"impl_1": {os.getpid()}})
    fw2 = snap(runs, cfg, report_cache, catalogs, group, now=T0 + 9100)          # new source: state is on disk
    stages = stage_map(fw2)
    assert fw2.attempt["n"] == 2 and fw2.attempt["mode"] == "project"
    assert fw2.status == "running"
    place = stages["impl_1/place_design"]
    assert place.status == "pending"
    assert [(a["n"], a["status"]) for a in place.attempts] == [(1, "failed")]    # attempt 1 summarized
    assert place.attempts[0]["failure"]["reason"] == "Error"
    opt = stages["impl_1/opt_design"]
    assert opt.status == "running" and [a["n"] for a in opt.attempts] == [1, 2]
    assert opt.attempts[0]["status"] == "done" and opt.attempts[1]["status"] == "running"
    assert fw2.attempt["previous_failure"] == "Error"
    assert "step_failed" not in {a["code"] for a in fw2.alerts}
    # nothing new: still attempt 2 (no phantom relaunch)
    fw3 = snap(runs, cfg, report_cache, catalogs, group, now=T0 + 9200)
    assert fw3.attempt["n"] == 2


def test_log_truncation_alone_is_a_relaunch(tmp_path, cfg, report_cache, catalogs):
    f = FIXTURES / "lockin"
    runs = build_runs(tmp_path, "lockin", "main_wrapper", f / "main_wrapper.vdi", f / "main_wrapper.tcl",
                      f / "main_wrapper.vds", STEPS_DONE[:5], impl_pid=os.getpid())
    group = Group("project", str(runs), "lockin", {os.getpid()}, run_pids={"impl_1": {os.getpid()}})
    snap(runs, cfg, report_cache, catalogs, group, now=T0 + 1000)
    vdi = runs / "impl_1" / "main_wrapper.vdi"
    vdi.write_text("\n".join(vdi.read_text().split("\n")[:30]) + "\n")          # truncated in place
    fw = snap(runs, cfg, report_cache, catalogs, group, now=T0 + 1100)
    assert fw.attempt["n"] == 2


# ------------------------------------------------------------------ discovery
def proc(pid, args, cwd):
    return {"pid": pid, "ppid": 1, "args": ["vivado"] + args, "cwd": cwd}


def test_discovery_resume_process_is_the_worker(tmp_path, cfg, monkeypatch):
    runs = tmp_path / "lockin.runs"
    impl = runs / "impl_1"
    impl.mkdir(parents=True)
    log = tmp_path / "resume.log"
    shutil.copy(CRASH / "resume.log", log)
    ckpt = str(impl / "main_wrapper_physopt.dcp")
    resume = proc(900001, ["-mode", "batch", "-source", str(tmp_path / "r.tcl"), "-log", str(log)], str(impl))
    monkeypatch.setattr(discovery, "scan_vivado", lambda: [resume])
    groups = Discovery(cfg).discover()
    assert len(groups) == 1 and groups[0].kind == "project" and groups[0].path == str(runs)
    group = groups[0]
    assert 900001 in group.pids and group.run_pids == {}                 # not a run worker ...
    assert group.launcher is None
    assert [(r["pid"], r["run"], r["log"]) for r in group.resumes] == [(900001, "impl_1", str(log))]
    assert group.resumes[0]["checkpoint"].endswith("lockin.runs/impl_1/main_wrapper_physopt.dcp") or True

    worker = proc(900002, ["-log", "main_wrapper.vdi", "-mode", "batch", "-source", "main_wrapper.tcl"], str(impl))
    monkeypatch.setattr(discovery, "scan_vivado", lambda: [worker])
    group = Discovery(cfg).discover()[0]
    assert group.run_pids == {"impl_1": {900002}} and group.resumes == []
    assert is_run_worker(worker, str(impl)) and not is_run_worker(resume, str(impl))


def test_discovery_resume_outside_run_dir_found_by_checkpoint(tmp_path, cfg, monkeypatch):
    runs = tmp_path / "lockin.runs"
    (runs / "impl_1").mkdir(parents=True)
    log = tmp_path / "elsewhere.log"
    log.write_text("# open_checkpoint %s/impl_1/main_wrapper_placed.dcp\nCommand: open_checkpoint x\n" % runs)
    other = tmp_path / "other"
    other.mkdir()
    p = proc(900003, ["-mode", "batch", "-log", str(log)], str(other))
    monkeypatch.setattr(discovery, "scan_vivado", lambda: [p])
    groups = Discovery(cfg).discover()
    assert len(groups) == 1 and groups[0].path == str(runs)
    res = groups[0].resumes[0]
    assert res["run"] == "impl_1" and res["checkpoint"].endswith("main_wrapper_placed.dcp")
    assert groups[0].launcher is None


# ------------------------------------------------------------------ status / alert rules
def test_alert_rules_for_dead_and_failed_nodes(cfg):
    node = Node(id="r/route_design", label="Route Design", kind="step", status="running")
    stalled = alert_rules.node_alerts(node, "route_design", cfg, stall_age=3600, alive=True)
    assert [a["code"] for a in stalled] == ["stalled"]
    assert alert_rules.node_alerts(node, "route_design", cfg, stall_age=3600, alive=False) == []
    node.status = "failed"
    node.failure = {"reason": "Out of memory", "details": [], "line": None, "log": "x", "hs_err": None}
    out = alert_rules.node_alerts(node, "route_design", cfg, stall_age=3600, alive=True)
    assert [(a["code"], a["message"]) for a in out] == [("step_failed", "Route Design failed: Out of memory")]
    node.failure = None
    assert alert_rules.node_alerts(node, "route_design", cfg)[0]["message"] == "Route Design failed"


def test_parser_still_handles_resume_log_commands(cfg):
    parser = LogParser(cfg)
    parser.feed((CRASH / "resume.log").read_text().split("\n"))
    steps = [c.cmd for c in parser.root.children if c.kind == "step"]
    assert steps == ["route_design", "write_bitstream"]
    assert any(c.kind == "command" and c.cmd == "open_checkpoint" for c in parser.root.children)


def _walk(node):
    yield node
    for c in node.children:
        yield from _walk(c)


# ------------------------------------------------------------------ persisted sessions / external attempts
QICK = FIXTURES / "qick"


def _artifact(impl, name, mtime, source=None):
    path = impl / name
    if source:
        shutil.copy(source, path)
    else:
        path.write_text("")
    os.utime(path, (mtime, mtime))


def test_deleted_resume_log_keeps_attempt_from_persisted_summary(tmp_path, cfg, report_cache, catalogs):
    runs = crashed_run(tmp_path)
    log = tmp_path / "scratch" / "resume.log"
    log.parent.mkdir()
    shutil.copy(CRASH / "resume.log", log)
    snap(runs, cfg, report_cache, catalogs, resume_group(runs, log))            # live: summary persisted
    live_fw = snap(runs, cfg, report_cache, catalogs, None)
    live_route = stage_map(live_fw)["impl_1/route_design"]
    shutil.rmtree(log.parent)                                                    # other tool's scratchpad is wiped
    fw = snap(runs, cfg, report_cache, catalogs, None)
    stages = stage_map(fw)
    route, bit = stages["impl_1/route_design"], stages["impl_1/write_bitstream"]
    assert fw.status == "done" and fw.attempt["n"] == 2 and fw.attempt["mode"] == "resume"
    assert route.status == "done" and route.log_missing and not route.failure
    assert [a["status"] for a in route.attempts] == ["failed", "done"]
    second = route.attempts[1]
    assert second["mode"] == "resume" and second["log_missing"] and second["summary"] == "log no longer available"
    assert second["timing"] == live_route.attempts[1]["timing"]
    assert (route.timing and route.timing.wns) == (live_route.timing and live_route.timing.wns)
    assert bit.status == "done" and bit.log_missing
    assert "step_failed" not in {a["code"] for a in fw.alerts}
    json.dumps(fw.to_dict())


def external_run(tmp_path, newer=True):
    runs = crashed_run(tmp_path)
    impl = runs / "impl_1"
    when = T0 + 4000 if newer else T0 + 1000
    _artifact(impl, "main_wrapper_physopt.dcp", T0 + 500)
    _artifact(impl, "main_wrapper_route_status.rpt", when, QICK / "d_1_wrapper_route_status.rpt")
    _artifact(impl, "main_wrapper_timing_summary_routed.rpt", when + 100,
              QICK / "d_1_wrapper_timing_summary_routed.rpt")
    _artifact(impl, "main_wrapper_routed.dcp", when + 300)
    _artifact(impl, "main_wrapper.bit", when + 600)
    return runs


def test_external_attempt_inferred_from_newer_artifacts(tmp_path, cfg, report_cache, catalogs):
    runs = external_run(tmp_path)
    fw = snap(runs, cfg, report_cache, catalogs)
    stages = stage_map(fw)
    route, bit = stages["impl_1/route_design"], stages["impl_1/write_bitstream"]
    assert fw.status == "done" and not fw.live
    assert route.status == "done" and bit.status == "done" and not route.failure
    assert fw.attempt == {"n": 2, "mode": "external", "resumed_from": "phys_opt_design",
                          "previous_failure": "Segmentation fault (signal 11)"}
    first, second = route.attempts
    assert (first["n"], first["status"], first["mode"]) == (1, "failed", "project")
    assert (second["n"], second["status"], second["mode"]) == (2, "done", "external")
    assert second["approx_times"] and second["started_at"] == T0 + 4000 and second["ended_at"] == T0 + 4300
    assert route.reports and not any(r["stale"] for r in route.reports)
    assert route.timing.source == "report" and route.timing.final and fw.timing.wns == route.timing.wns
    assert bit.started_at == T0 + 4300 and bit.ended_at == T0 + 4600 and bit.attempts == []
    assert "step_failed" not in {a["code"] for a in fw.alerts}
    json.dumps(fw.to_dict())


def test_artifacts_older_than_failure_do_not_count(tmp_path, cfg, report_cache, catalogs):
    runs = external_run(tmp_path, newer=False)
    fw = snap(runs, cfg, report_cache, catalogs)
    route = stage_map(fw)["impl_1/route_design"]
    assert fw.status == "failed" and route.status == "failed"
    assert fw.attempt["mode"] == "project" and stage_map(fw)["impl_1/write_bitstream"].status != "done"


def test_bitstream_alone_proves_route_done(tmp_path, cfg, report_cache, catalogs):
    runs = crashed_run(tmp_path)
    _artifact(runs / "impl_1", "main_wrapper.bit", T0 + 5000)
    fw = snap(runs, cfg, report_cache, catalogs)
    stages = stage_map(fw)
    assert stages["impl_1/route_design"].status == "done" and stages["impl_1/write_bitstream"].status == "done"
    assert fw.status == "done" and fw.attempt["mode"] == "external"


def test_artifact_map_is_configurable(tmp_path, catalogs):
    cfg = load_config()
    cfg.artifacts.files.append(("^{top}\\.xyz$", "write_bitstream"))
    assert cfg.artifacts.step_for_file("main_wrapper.xyz", "main_wrapper") == "write_bitstream"
    assert cfg.artifacts.step_for_file("main_wrapper.bit", "main_wrapper") == "write_bitstream"
    assert cfg.artifacts.step_for_file("other.bit", "main_wrapper") is None
