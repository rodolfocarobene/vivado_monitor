import json
import os
import shutil

from conftest import FIXTURES, build_runs, marker
from test_project import lockin, qick, stage_map
from test_v2 import make_monitor
from vmon.alerts import health
from vmon.discovery import Group
from vmon.project import ProjectSource

T_NOW = 1_010_000.0


def live_route(tmp_path, cfg, report_cache, catalogs):
    """qick log cut right after the first (negative WHS) route Intermediate Timing Summary; route_design running."""
    f = FIXTURES / "qick"
    lines = (f / "d_1_wrapper.vdi").read_text().split("\n")
    cut = next(i for i, ln in enumerate(lines) if "Intermediate Timing Summary" in ln)
    short = tmp_path / "short.vdi"
    short.write_text("\n".join(lines[:cut + 1]) + "\n")
    steps = ["init_design", "opt_design", "place_design", "phys_opt_design"]
    markers = [(s, k) for s in steps for k in ("begin", "end")] + [("route_design", "begin")]
    runs = build_runs(tmp_path, "top", "d_1_wrapper", short, f / "d_1_wrapper.tcl",
                      FIXTURES / "lockin" / "main_wrapper.vds", markers, impl_pid=os.getpid())
    source = ProjectSource(runs, cfg, report_cache, catalogs)
    fw = source.snapshot(Group("project", str(runs), "top", {os.getpid()}), now=1_001_500.0)
    return runs, source, fw


# ---------------------------------------------------------------- timing finality
def test_intermediate_route_timing_is_warning(tmp_path, cfg, report_cache, catalogs):
    _, _, fw = live_route(tmp_path, cfg, report_cache, catalogs)
    route = stage_map(fw)["impl_1/route_design"]
    assert route.status == "running"
    assert route.timing.whs < 0 and route.timing.final is False
    assert route.timing.stage == "Route · intermediate"
    assert fw.timing.final is False and fw.timing.stage == route.timing.stage
    alerts = [a for a in fw.alerts if a["code"] == "timing_fail"]
    assert alerts and all(a["level"] == "warning" for a in alerts)
    msg = alerts[0]["message"]
    assert "intermediate" in msg and "hold fixing" in msg
    assert health(fw.alerts) == "warning" == fw.health


def test_final_timing_not_met_is_error(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=T_NOW)
    assert fw.timing.final is True and fw.timing.stage == "Route · final report"
    # force a violation on the finished build via its log timing
    route = stage_map(fw)["impl_1/route_design"]
    route.timing.wns, route.timing.final = -0.2, True
    from vmon.alerts import node_alerts
    out = node_alerts(route, "route_design", cfg)
    assert [a["level"] for a in out if a["code"] == "timing_fail"] == ["error"]
    assert health(out) == "error"


def test_finished_build_met_is_ok_and_final(tmp_path, cfg, report_cache, catalogs):
    fw = ProjectSource(qick(tmp_path), cfg, report_cache, catalogs).snapshot(None, now=T_NOW)
    assert fw.timing.final is True and fw.timing.met is True
    assert "final" in fw.timing.stage
    place = stage_map(fw)["impl_1/place_design"]
    assert place.timing.final is False and place.timing.stage == "Place · estimate"
    assert fw.to_dict()["timing"]["final"] is True


# ---------------------------------------------------------------- ETA
def test_eta_previous_build_and_fallback(tmp_path, cfg):
    monitor = make_monitor(tmp_path, cfg)
    runs = lockin(tmp_path, impl_pid=os.getpid())
    # fallback: no previous build
    fw = ProjectSource(runs, cfg, monitor.reports, monitor.catalog).snapshot(
        Group("project", str(runs), "lockin", {os.getpid()}), now=1_001_000.0)
    from vmon.eta import estimate
    eta = estimate(fw, None, 1_001_000.0)
    assert eta["method"] == "catalog weights" and eta["confidence"] == "low" and eta["remaining_s"] > 0
    # previous build durations file
    previous = {"build": "1", "total_s": 5000, "steps": {
        "synth_design": 100, "init_design": 20, "opt_design": 100, "place_design": 600,
        "phys_opt_design": 300, "route_design": 1000, "write_bitstream": 80}}
    eta = estimate(fw, previous, 1_001_000.0)
    place = stage_map(fw)["impl_1/place_design"]
    expected = max(600 - place.elapsed_s, 60) + 300 + 1000 + 80
    assert eta["method"] == "previous build" and eta["confidence"] == "medium"
    assert abs(eta["remaining_s"] - expected) < 0.2
    assert abs(eta["expected_end"] - (1_001_000.0 + expected)) < 0.2
    # overrun: current step past its previous duration -> at least 10% of it remains
    previous["steps"]["place_design"] = 1
    eta = estimate(fw, previous, 1_001_000.0)
    assert abs(eta["remaining_s"] - (0.1 + 300 + 1000 + 80)) < 0.2


def test_durations_recorded_for_finished_build_and_used(tmp_path, cfg):
    monitor = make_monitor(tmp_path, cfg)
    runs = qick(tmp_path)
    monitor.add_path(str(runs))
    monitor.tick()
    fw_id = next(iter(monitor.firmwares))
    saved = json.loads((tmp_path / "cache" / "durations" / (fw_id + ".json")).read_text())
    assert saved["steps"]["route_design"] > 0 and "synth_design" in saved["steps"]
    assert monitor.firmwares[fw_id].eta is None          # finished build has no ETA
    assert monitor.durations.load(fw_id)["steps"] == saved["steps"]


# ---------------------------------------------------------------- info
def test_info_parsing(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    shutil.copy(FIXTURES / "info" / "small.xpr", tmp_path / "top.xpr")
    shutil.copy(FIXTURES / "info" / "gen_run.xml", runs / "impl_1" / "gen_run.xml")
    shutil.copy(FIXTURES / "info" / "begin.rst", runs / "impl_1" / ".vivado.begin.rst")
    source = ProjectSource(runs, cfg, report_cache, catalogs)
    fw = source.snapshot(None, now=T_NOW)
    info = fw.info
    assert info["part"] == "xczu48dr-ffvg1517-2-e"
    assert info["board"] == "realdigital.org:rfsoc4x2:part0:1.0"
    assert info["top"] == "d_1_wrapper"
    assert info["strategy_synth"] == "Flow_PerfOptimized_high"
    assert info["strategy_impl"] == "Performance_NetDelay_high"
    assert info["directives"] == {"place_design": "ExtraNetDelay_high", "phys_opt_design": "AggressiveExplore",
                                  "route_design": "NoTimingRelaxation"}
    assert info["host"] == "buildhost" and info["jobs"] == 4
    assert info["project"].endswith("top.xpr")
    json.dumps(fw.to_dict())


def test_info_without_project_files(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    info = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=T_NOW).info
    assert info["board"] is None and info["strategy_impl"] is None and info["project"] is None
    assert info["part"] == "xczu48dr-ffvg1517-2-e"       # from the -part of link_design
    assert info["jobs"] == 2                              # from the run tcl launchOptions


# ---------------------------------------------------------------- doc links
def test_doc_urls(tmp_path, cfg, report_cache, catalogs):
    source = ProjectSource(qick(tmp_path), cfg, report_cache, catalogs)
    fw = source.snapshot(None, now=T_NOW)
    stages = stage_map(fw)
    route = stages["impl_1/route_design"]
    assert route.doc_url.endswith("ug904-vivado-implementation/route_design")
    assert stages["synth"].doc_url and "ug901" in stages["synth"].doc_url
    assert stages["impl_1/init_design"].doc_url.endswith("ug835-vivado-tcl-commands/link_design")
    assert all(c.doc_url == route.doc_url or "ug835" in c.doc_url for c in route.children)
    urls = {r["kind"]: r["doc_url"] for r in route.reports}
    assert urls["timing_summary"].endswith("/report_timing_summary")
    assert urls["drc"].endswith("/report_drc") and urls["power"].endswith("/report_power")
    d = fw.to_dict()
    assert d["flows"][0]["stages"][1]["doc_url"]
    group = source.messages(None, None, 5)["groups"][0]
    assert "docs.amd.com" in group["doc_url"] and "%22" in group["doc_url"]


def test_triage_group_doc_url_encoded(tmp_path, cfg):
    monitor = make_monitor(tmp_path, cfg)
    runs = lockin(tmp_path, impl_pid=os.getpid())
    monitor.add_path(str(runs))
    monitor.tick()
    fw_id = next(iter(monitor.firmwares))
    groups = monitor.triage(fw_id, severities=["warning", "critical", "error"])["groups"]
    with_id = [g for g in groups if " " in g["id"] and "-" in g["id"]]
    assert with_id
    g = with_id[0]
    assert g["doc_url"] and g["id"].replace(" ", "+") in g["doc_url"]
