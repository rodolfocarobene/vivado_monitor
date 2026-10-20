from conftest import FIXTURES

Q = FIXTURES / "qick" / "d_1_wrapper_"


def test_timing_summary(report_cache):
    summary = report_cache.parse(str(Q) + "timing_summary_routed.rpt", "timing")[0]
    assert (summary["wns"], summary["tns"], summary["whs"], summary["tns_fail"]) == (0.006, 0.0, 0.01, 0)
    assert summary["clocks"] and {"name", "period", "wns", "tns", "whs", "ths"} <= set(summary["clocks"][0])


def test_utilization_rows_and_alert(report_cache, cfg):
    summary, alerts = report_cache.parse(str(Q) + "utilization_placed.rpt", "utilization")
    rows = {r["name"]: r for r in summary["rows"]}
    assert rows["LUT"]["used"] == 84081 and rows["LUT"]["available"] == 425280
    assert alerts == []
    cfg.alerts["utilization_pct"] = 10
    assert report_cache.parse(str(Q) + "utilization_placed.rpt", "utilization")[1] == []   # cached


def test_drc_counts(report_cache):
    summary, alerts = report_cache.parse(str(Q) + "drc_routed.rpt", "drc")
    assert set(summary["counts"]) == {"error", "critical", "warning", "info"}
    assert summary["counts"]["warning"] > 0 and summary["rules"][0]["id"] and alerts == []


def test_route_status_and_power(report_cache):
    status = report_cache.parse(str(Q) + "route_status.rpt", "route_status")[0]
    assert status["unrouted"] == 0 and status["routable"] == status["fully_routed"]
    power = report_cache.parse(str(Q) + "power_routed.rpt", "power")[0]
    assert power["total_w"] == 15.082 and power["junction_c"] == 37.7


def test_reparse_only_on_change(report_cache, tmp_path):
    path = tmp_path / "t.rpt"
    path.write_text("Violations\n")
    first = report_cache.parse(str(path), "generic")
    assert report_cache.parse(str(path), "generic") is first
