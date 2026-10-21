"""v6: failing-paths view, per-clock timing history, router convergence."""
import json
import os
import random
import re
import shutil
import threading
import urllib.error
import urllib.request

from conftest import FIXTURES, build_runs, marker
from test_project import qick, stage_map
from test_v2 import make_monitor
from vmon import alerts as alert_rules
from vmon import clocks, convergence, timing_paths
from vmon.discovery import Group
from vmon.logparse import LogParser
from vmon.model import Node
from vmon.project import ProjectSource
from vmon.server import make_server

PATHS = FIXTURES / "paths" / "timing_paths_excerpt.rpt"
QICK = FIXTURES / "qick"


def combined_report(dest, summary=QICK / "d_1_wrapper_timing_summary_routed.rpt"):
    """Real (truncated) summary tables + the path-section excerpt, as one report."""
    dest.write_text(summary.read_text() + "\n" + PATHS.read_text())
    return dest


# ---------------------------------------------------------------- failing paths
def test_path_parsing_types_slack_and_fields():
    found = timing_paths.parse_file(str(PATHS))
    counts, paths = found["counts"], found["paths"]
    assert (counts["total"], counts["setup"], counts["hold"]) == (6, 4, 2)
    assert (counts["setup_failing"], counts["hold_failing"], counts["failing"]) == (2, 1, 3)
    assert counts["failing_clocks"] == 1 and counts["clocks"] == ["mmcm_clkout0"]
    assert [p["slack"] for p in paths] == sorted(p["slack"] for p in paths)          # worst first
    worst = paths[0]
    assert (worst["type"], worst["status"], worst["slack"]) == ("setup", "VIOLATED", -0.412)
    assert (worst["from_clock"], worst["to_clock"]) == ("clk_pl_0", "mmcm_clkout0")
    assert worst["levels"] == 6 and worst["cells"] == {"LUT2": 1, "LUT4": 2, "LUT5": 1, "LUT6": 2}
    assert worst["source"].startswith("d_1_i/qick_processor_0") and worst["destination"]
    assert worst["source_clock"] and worst["dest_clock"] and worst["group"]
    assert worst["path_type"] == "Setup" and worst["corner"] == "Max at Slow Process Corner"
    hold = next(p for p in paths if p["type"] == "hold" and p["status"] == "VIOLATED")
    assert hold["slack"] == -0.051 and hold["path_type"] == "Hold"


def test_path_parsing_met_paths_split_skew_and_uncertainty():
    paths = timing_paths.parse_file(str(PATHS))["paths"]
    met = next(p for p in paths if p["slack"] == 42.694)
    assert met["status"] == "MET" and met["type"] == "setup"
    assert met["requirement"] == 43.403 and met["data_delay"] == 0.637
    assert (met["logic_delay"], met["route_delay"]) == (0.465, 0.172)
    assert abs(met["logic_pct"] + met["route_pct"] - 100) < 0.01 and met["logic_pct"] == 72.998
    assert met["levels"] == 1 and met["cells"] == {"LUT3": 1}
    assert met["skew"] == -0.062 and met["uncertainty"] == 0.035
    hold = next(p for p in paths if p["slack"] == 0.02)
    assert hold["type"] == "hold" and hold["levels"] == 0 and hold["cells"] == {}
    assert hold["uncertainty"] is None and hold["skew"] == 0.073


def test_path_parsing_ignores_unconstrained_and_pulse_width_and_caps():
    found = timing_paths.parse_file(str(PATHS))
    assert all(p["slack"] != 9.999 for p in found["paths"])          # pulse width line is not a path
    assert all(p["source"] != "d_1_i/qick_processor_0/inst/QPROC/DISPATCHER/port_trig_r_reg[9]/C"
               for p in found["paths"])                                # "Slack: inf" block
    capped = timing_paths.parse_file(str(PATHS), max_paths=4)         # 2 setup + 2 hold
    assert capped["counts"]["total"] == 6 and capped["counts"]["capped"] and len(capped["paths"]) == 4
    assert [p["slack"] for p in capped["paths"]][:2] == [-0.412, -0.318]
    assert timing_paths.parse_file("/nonexistent/x.rpt") is None


def test_report_summary_has_paths_and_counts(tmp_path, report_cache):
    path = combined_report(tmp_path / "d_1_wrapper_timing_summary_routed.rpt")
    summary = report_cache.parse(str(path), "timing")[0]
    assert summary["wns"] == 0.006                                   # tables still parsed
    assert summary["path_counts"]["failing"] == 3 and summary["paths"][0]["slack"] == -0.412
    assert {"type", "slack", "status", "source", "destination", "levels"} <= set(summary["paths"][0])
    assert "cells" not in summary["paths"][0]                        # compact form in the state JSON
    full = report_cache.paths(str(path))
    assert len(full["paths"]) == 6
    assert report_cache.parse(str(path), "timing")[0] is summary     # not re-parsed unless the file changes


def test_paths_reparsed_when_report_changes(tmp_path, report_cache):
    path = combined_report(tmp_path / "t.rpt")
    assert report_cache.paths(str(path))["counts"]["total"] == 6
    path.write_text(path.read_text() + "\n" + PATHS.read_text())
    os.utime(path, (os.stat(path).st_mtime + 5, os.stat(path).st_mtime + 5))
    assert report_cache.paths(str(path))["counts"]["total"] == 12


def project_with_paths(tmp_path):
    runs = qick(tmp_path)
    impl = runs / "impl_1"
    combined_report(impl / "d_1_wrapper_timing_summary_routed.rpt")
    os.utime(impl / "d_1_wrapper_timing_summary_routed.rpt", (1_003_000.0, 1_003_000.0))
    return runs


def test_timing_carries_report_path_and_counts(tmp_path, cfg, report_cache, catalogs):
    runs = project_with_paths(tmp_path)
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    timing = fw.to_dict()["timing"]
    assert timing["report"].endswith("d_1_wrapper_timing_summary_routed.rpt")
    assert timing["path_counts"]["failing"] == 3 and timing["paths"][0]["slack"] == -0.412


def test_paths_endpoint_filters_and_validates(tmp_path, cfg):
    runs = project_with_paths(tmp_path)
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    server = make_server(monitor, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    report = str(runs / "impl_1" / "d_1_wrapper_timing_summary_routed.rpt")

    def get(extra):
        return json.load(urllib.request.urlopen("%s/api/paths?fw=%s&path=%s%s" % (base, fw_id, report, extra)))

    def status(url):
        try:
            urllib.request.urlopen(url)
        except urllib.error.HTTPError as err:
            return err.code
        return 200
    try:
        everything = get("")
        assert len(everything["paths"]) == 6 and everything["counts"]["failing"] == 3
        assert {p["type"] for p in get("&type=hold")["paths"]} == {"hold"}
        failing = get("&only_failing=1")["paths"]
        assert len(failing) == 3 and all(p["status"] == "VIOLATED" for p in failing)
        assert [p["slack"] for p in get("&type=setup&only_failing=1")["paths"]] == [-0.412, -0.318]
        assert status("%s/api/paths?fw=%s&path=/etc/passwd" % (base, fw_id)) == 403
        assert status("%s/api/paths?fw=%s&path=%s&type=bogus" % (base, fw_id, report)) == 400
        assert status("%s/api/paths?fw=nope&path=%s" % (base, report)) == 404
    finally:
        server.shutdown()
        monitor.stop()


# ---------------------------------------------------------------- per-clock history
def clock_report(tmp_path, name, wns_shift=0.0):
    """Timing report whose per-clock WNS values are shifted (to tell stages/builds apart)."""
    text = (QICK / "d_1_wrapper_timing_summary_routed.rpt").read_text()
    if wns_shift:
        text = re.sub(r"^(clk_pl_0\s+)1\.230", lambda m: m.group(1) + "%.3f" % (1.230 + wns_shift), text, flags=re.M)
        assert "1.730" in text
    path = tmp_path / name
    path.write_text(text)
    os.utime(path, (1_003_000.0, 1_003_000.0))
    return path


def test_per_clock_extraction_from_report(report_cache):
    summary = report_cache.parse(str(QICK / "d_1_wrapper_timing_summary_routed.rpt"), "timing")[0]
    per = clocks.per_clock(summary["clocks"])
    assert set(per["clk_pl_0"]) == {"wns", "tns", "whs", "ths", "failing"}
    assert per["clk_pl_0"]["wns"] == 1.23 and per["clk_pl_0"]["failing"] == 0
    assert "pll_clk[0]" not in per                                   # pulse-width-only rows have no WNS


def test_clock_history_stages_within_a_build(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    impl = runs / "impl_1"
    shutil.copy(clock_report(tmp_path, "src.rpt", 0.5), impl / "d_1_wrapper_timing_summary_placed.rpt")
    os.utime(impl / "d_1_wrapper_timing_summary_placed.rpt", (1_002_000.0, 1_002_000.0))
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    stages = clocks.stages_of(fw, cfg)
    assert [s["label"] for s in stages] == ["Place · placed", "Route · routed"]
    assert stages[0]["per_clock"]["clk_pl_0"]["wns"] == 1.73
    assert stages[1]["per_clock"]["clk_pl_0"]["wns"] == 1.23
    history = clocks.history(fw, clocks.ClockStore(tmp_path / "t"), cfg)
    assert history["stages"] == stages and history["clocks"][0] in stages[1]["per_clock"]
    assert history["builds"][-1]["current"] is True                  # unstored build shown as the latest point


def test_clock_history_persisted_across_builds_with_temp_home(tmp_path, cfg):
    runs = qick(tmp_path)
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    saved = json.loads((tmp_path / "cache" / "timing" / (fw_id + ".json")).read_text())
    assert len(saved["builds"]) == 1
    build = saved["builds"][0]
    assert build["started_at"] == int(monitor.firmwares[fw_id].started_at) and build["label"]
    assert build["per_clock"]["clk_pl_0"]["wns"] == 1.23
    history = monitor.firmwares[fw_id].clock_history
    assert history["builds"][-1]["started_at"] == build["started_at"] and "current" not in history["builds"][-1]
    assert monitor.firmwares[fw_id].to_dict()["clock_history"]["clocks"]

    # a fresh monitor (restart) keeps the stored build and does not duplicate it
    monitor2 = make_monitor(tmp_path, cfg)
    monitor2.add_path(str(runs))
    monitor2.tick()
    assert len(json.loads((tmp_path / "cache" / "timing" / (fw_id + ".json")).read_text())["builds"]) == 1


def test_clock_store_keeps_last_20_and_replaces_same_build(tmp_path):
    store = clocks.ClockStore(tmp_path / "timing")
    for i in range(25):
        store.record("fw", 1000 + i * 100, {"clkA": {"wns": i * 0.1, "tns": 0, "whs": 0.1, "ths": 0, "failing": 0}})
    builds = store.load("fw")
    assert len(builds) == 20 and builds[0]["started_at"] == 1500 and builds[-1]["started_at"] == 3400
    assert store.record("fw", 3400, {"clkA": {"wns": 9.0, "tns": 0, "whs": 0.1, "ths": 0, "failing": 0}})
    assert store.load("fw")[-1]["per_clock"]["clkA"]["wns"] == 9.0 and len(store.load("fw")) == 20
    assert not store.record("fw", 3400, store.load("fw")[-1]["per_clock"])      # unchanged -> no write
    assert store.load("other") == []
    (tmp_path / "timing" / "bad.json").write_text("{not json")
    assert store.load("bad") == []


def test_unfinished_build_is_not_stored(tmp_path, cfg, report_cache, catalogs):
    runs = qick(tmp_path)
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    stages = clocks.stages_of(fw, cfg)
    fw.status = "running"
    assert clocks.final_stage(fw, stages, cfg) is None
    fw.status = "done"
    assert clocks.final_stage(fw, stages, cfg) is stages[-1]
    fw.status = "failed"                 # failed after the final timing report still has a usable result
    assert clocks.final_stage(fw, stages, cfg) is stages[-1]


# ---------------------------------------------------------------- router convergence
def feed(lines, cfg, chunks=None):
    parser = LogParser(cfg)
    if chunks is None:
        parser.feed(lines)
    else:
        index = 0
        while index < len(lines):
            size = next(chunks)
            parser.feed(lines[index:index + size])
            index += size
    parser.mark_live()
    return parser


def route_step(parser):
    return next(c for c in parser.root.children if c.kind == "step" and c.cmd == "route_design")


def test_convergence_parsed_from_real_route_log(cfg):
    lines = (QICK / "route_iterations.vdi").read_text().split("\n")
    iterations = route_step(feed(lines, cfg)).iters
    assert [it["label"] for it in iterations] == [
        "4.1 Global Iteration 0", "4.2 Global Iteration 1", "4.3 Global Iteration 2"]
    first = iterations[0]
    assert first["overlaps"] == [31569, 2267, 230, 35, 9, 2, 1, 1, 0] and first["final_overlaps"] == 0
    assert (first["wns"], first["tns"], first["whs"], first["ths"]) == (-0.05, -2.259, -0.021, -0.206)
    assert iterations[1]["overlaps"] == [146, 20, 1, 0] and iterations[1]["whs"] is None
    assert iterations[2]["wns"] == -0.03 and iterations[2]["line"] > iterations[1]["line"]
    # overlap lines outside an iteration (global clock routing, delay clean-up) are not iterations
    assert all("Global Iteration" in it["label"] for it in iterations)


def test_convergence_chunked_equals_whole(cfg):
    lines = (QICK / "route_iterations.vdi").read_text().split("\n")
    whole = route_step(feed(lines, cfg)).iters
    rng = random.Random(7)

    def sizes():
        while True:
            yield rng.randint(1, 9)
    for _ in range(5):
        chunked = route_step(feed(lines, cfg, sizes())).iters
        assert chunked == whole
    assert route_step(feed(lines, cfg, iter(lambda: 1, None))).iters == whole       # line by line


def test_convergence_partial_iteration_is_live(cfg):
    lines = (QICK / "route_iterations.vdi").read_text().split("\n")
    cut = next(i for i, ln in enumerate(lines) if "Number of Nodes with overlaps = 230" in ln)
    parser = feed(lines[:cut + 1], cfg)
    live = route_step(parser).iters
    assert len(live) == 1 and live[0]["overlaps"] == [31569, 2267, 230] and live[0]["wns"] is None
    parser.feed(lines[cut + 1:cut + 14])
    assert route_step(parser).iters[0]["overlaps"][-1] == 0 or len(route_step(parser).iters[0]["overlaps"]) > 3


def synthetic_route_log(finals, inner=(5000, 800), with_timing=True):
    out = ["Command: route_design", "Starting Routing Task", "", "Phase 4 Rip-up And Reroute", ""]
    for k, final in enumerate(finals):
        out.append("Phase 4.%d Global Iteration %d" % (k + 1, k))
        for value in inner:
            out.append(" Number of Nodes with overlaps = %d" % (value if value > final else final))
        out.append(" Number of Nodes with overlaps = %d" % final)
        if with_timing:
            out.append("INFO: [Route 35-416] Intermediate Timing Summary | WNS=%.3f | TNS=%.3f | WHS=N/A    | THS=N/A    |"
                       % (-0.01 * (k + 1), -0.1 * (k + 1)))
        out.append("Phase 4.%d Global Iteration %d | Checksum: 1a2b3c%d" % (k + 1, k, k))
        out.append("")
    return out


def trend_of(finals, cfg):
    parser = feed(synthetic_route_log(finals), cfg)
    return convergence.trend(route_step(parser).iters, cfg)


def test_trend_rule(cfg):
    assert trend_of([900], cfg) is None
    assert trend_of([900, 950], cfg) is None                         # too early (window 3) and not dropping
    assert trend_of([900, 700, 400], cfg) == "converging"            # strictly dropping so far
    assert trend_of([900, 500, 100, 0], cfg) == "converging"
    assert trend_of([50, 30, 20, 0], cfg) == "converging"
    assert trend_of([0, 0, 0, 0], cfg) == "converging"               # every iteration clean
    assert trend_of([900, 880, 870, 860], cfg) == "stalled"          # < 20 % better over 3 iterations
    assert trend_of([900, 600, 500, 600, 590], cfg) == "stalled"
    assert trend_of([100, 120, 150, 400], cfg) == "diverging"
    assert trend_of([900, 700, 300, 150], cfg) == "converging"
    cfg.convergence.window = 2
    assert trend_of([900, 880, 870], cfg) == "stalled"
    cfg.convergence.min_improvement_pct = 1
    assert trend_of([900, 880, 870], cfg) == "converging"


def test_trend_in_summary_and_chart_series(cfg):
    parser = feed(synthetic_route_log([900, 890, 880, 870]), cfg)
    conv = convergence.summarize(route_step(parser).iters, cfg)
    assert conv["trend"] == "stalled" and len(conv["iterations"]) == 4
    assert conv["iterations"][0]["wns"] == -0.01 and conv["iterations"][3]["final_overlaps"] == 870
    assert convergence.summarize([], cfg) is None


def route_node(cfg, finals, status="running"):
    node = Node(id="impl_1/route_design", label="Route", kind="step", status=status)
    parser = feed(synthetic_route_log(finals), cfg)
    node.convergence = convergence.summarize(route_step(parser).iters, cfg)
    return node


def test_stalled_router_alert_live_only_and_configurable(cfg):
    alerts = alert_rules.node_alerts(route_node(cfg, [900, 890, 880, 870]), "route_design", cfg, None, True)
    hit = [a for a in alerts if a["code"] == "route_not_converging"]
    assert len(hit) == 1 and hit[0]["level"] == "warning" and hit[0]["node_id"] == "impl_1/route_design"
    assert "stalled" in hit[0]["message"] and "870" in hit[0]["message"] and "4 so far" in hit[0]["message"]
    diverging = alert_rules.node_alerts(route_node(cfg, [100, 120, 150, 400]), "route_design", cfg, None, True)
    assert "diverging" in next(a for a in diverging if a["code"] == "route_not_converging")["message"]
    for node, alive in ((route_node(cfg, [900, 890, 880, 870], "done"), True),
                        (route_node(cfg, [900, 890, 880, 870]), False)):
        assert not [a for a in alert_rules.node_alerts(node, "route_design", cfg, None, alive)
                    if a["code"] == "route_not_converging"]
    healthy = alert_rules.node_alerts(route_node(cfg, [900, 500, 100, 0]), "route_design", cfg, None, True)
    assert not [a for a in healthy if a["code"] == "route_not_converging"]
    cfg.convergence.alert_min_iterations = 6
    assert not [a for a in alert_rules.node_alerts(route_node(cfg, [900, 890, 880, 870]), "route_design", cfg, None, True)
                if a["code"] == "route_not_converging"]
    cfg.convergence.alert_min_iterations = 4
    cfg.convergence.alert = False
    assert not [a for a in alert_rules.node_alerts(route_node(cfg, [900, 890, 880, 870]), "route_design", cfg, None, True)
                if a["code"] == "route_not_converging"]


def test_convergence_on_live_project_node_and_alert(tmp_path, cfg, report_cache, catalogs):
    log = tmp_path / "stalled.vdi"
    log.write_text("\n".join(synthetic_route_log([900, 890, 880, 870])) + "\n")
    steps = ["init_design", "opt_design", "place_design", "phys_opt_design"]
    markers = [(s, k) for s in steps for k in ("begin", "end")] + [("route_design", "begin")]
    runs = build_runs(tmp_path, "top", "d_1_wrapper", log, QICK / "d_1_wrapper.tcl",
                      FIXTURES / "lockin" / "main_wrapper.vds", markers, impl_pid=os.getpid())
    source = ProjectSource(runs, cfg, report_cache, catalogs)
    fw = source.snapshot(Group("project", str(runs), "top", {os.getpid()}), now=1_001_500.0)
    route = stage_map(fw)["impl_1/route_design"]
    data = route.to_dict()["convergence"]
    assert data["trend"] == "stalled" and len(data["iterations"]) == 4
    assert {"label", "overlaps", "final_overlaps", "wns", "tns", "whs", "ths", "t", "line"} <= set(data["iterations"][0])
    assert any(a["code"] == "route_not_converging" for a in fw.alerts)
    # steps without router iterations carry no convergence
    assert stage_map(fw)["impl_1/opt_design"].convergence is None


def test_real_route_fixture_converges_without_alert(tmp_path, cfg, report_cache, catalogs):
    steps = ["init_design", "opt_design", "place_design", "phys_opt_design"]
    markers = [(s, k) for s in steps for k in ("begin", "end")] + [("route_design", "begin")]
    runs = build_runs(tmp_path, "top", "d_1_wrapper", QICK / "route_iterations.vdi", QICK / "d_1_wrapper.tcl",
                      FIXTURES / "lockin" / "main_wrapper.vds", markers, impl_pid=os.getpid())
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(
        Group("project", str(runs), "top", {os.getpid()}), now=1_001_500.0)
    conv = stage_map(fw)["impl_1/route_design"].convergence
    assert conv is not None and conv["trend"] == "converging" and len(conv["iterations"]) == 3
    assert not any(a["code"] == "route_not_converging" for a in fw.alerts)
