import json
import os
import threading
import urllib.error
import urllib.request

from conftest import FIXTURES, build_runs
from test_project import lockin, qick, stage_map
from test_v2 import make_monitor
from vmon.browse import browse, live_paths
from vmon.discovery import Group
from vmon.project import ProjectSource
from vmon.server import make_server


def route_after_na(tmp_path, cfg, report_cache, catalogs):
    """qick log cut after the Intermediate line with WHS=N/A; route_design running."""
    f = FIXTURES / "qick"
    lines = (f / "d_1_wrapper.vdi").read_text().split("\n")
    cut = [i for i, ln in enumerate(lines) if "Intermediate Timing Summary" in ln][1]
    short = tmp_path / "short.vdi"
    short.write_text("\n".join(lines[:cut + 1]) + "\n")
    steps = ["init_design", "opt_design", "place_design", "phys_opt_design"]
    markers = [(s, k) for s in steps for k in ("begin", "end")] + [("route_design", "begin")]
    runs = build_runs(tmp_path, "top", "d_1_wrapper", short, f / "d_1_wrapper.tcl",
                      FIXTURES / "lockin" / "main_wrapper.vds", markers, impl_pid=os.getpid())
    source = ProjectSource(runs, cfg, report_cache, catalogs)
    return source.snapshot(Group("project", str(runs), "top", {os.getpid()}), now=1_001_500.0)


# ---------------------------------------------------------------- timing carry-forward
def test_na_hold_is_carried_from_previous_line(tmp_path, cfg, report_cache, catalogs):
    fw = route_after_na(tmp_path, cfg, report_cache, catalogs)
    route = stage_map(fw)["impl_1/route_design"]
    t = route.timing
    assert t.history[-1]["whs"] is None                  # history stays raw
    assert t.whs == -0.118 and t.ths == -126.375
    assert t.carried["whs"]["label"] == "Route · intermediate" and t.carried["whs"]["line"] == 242
    assert set(t.carried) == {"whs", "ths"}
    assert t.met is False
    assert fw.timing is t
    assert json.loads(json.dumps(t.to_dict()))["carried"]["ths"]["line"] == 242
    msgs = [a["message"] for a in fw.alerts if a["code"] == "timing_fail"]
    assert any("WHS -0.118" in m and "(from Route · intermediate)" in m for m in msgs)


def test_estimated_line_carries_hold_from_earlier_step(tmp_path, cfg, report_cache, catalogs):
    from vmon.model import Flow, Node, Timing
    entry = lambda line, label, **kw: {"t": None, "line": line, "label": label, "wns": 0.1, "tns": 0.0,
                                       "whs": None, "ths": None, **kw}
    early = Node(id="impl_1/place_design", label="Place", kind="step", status="done")
    early.timing = Timing(wns=0.1, tns=0.0, history=[entry(5, "Estimated")])
    late = Node(id="impl_1/phys_opt_design", label="Phys Opt", kind="step", status="running")
    late.timing = Timing(wns=0.2, tns=0.0, history=[entry(9, "Intermediate", whs=-0.2, ths=-3.0),
                                                    entry(12, "Estimated")])
    source = ProjectSource(tmp_path, cfg, report_cache, catalogs)
    source._carry_timing([Flow(id="impl_1", label="impl_1", stages=[early, late])])
    assert early.timing.carried == {} and early.timing.whs is None
    assert late.timing.whs == -0.2 and late.timing.carried["whs"]["line"] == 9 and late.timing.met is False


def test_report_timing_has_nothing_carried(tmp_path, cfg, report_cache, catalogs):
    fw = ProjectSource(qick(tmp_path), cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    assert fw.timing.source == "report" and fw.timing.carried == {} and fw.timing.whs == 0.01


# ---------------------------------------------------------------- predicted numbers
def flat(node):
    yield node
    for child in node.children:
        yield from flat(child)


def test_predicted_numbers_live_lockin(tmp_path, cfg, report_cache, catalogs):
    runs = lockin(tmp_path, impl_pid=os.getpid())
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(
        Group("project", str(runs), "lockin", {os.getpid()}), now=1_001_000.0)
    place = stage_map(fw)["impl_1/place_design"]
    nodes = {n.label: n for n in flat(place)}
    assert nodes["1 Placer Initialization"].number == "1" and not nodes["1 Placer Initialization"].number_predicted
    for label, number in (("2 Global Placement", "2"), ("3 Detail Placement", "3"),
                          ("4 Post Placement Optimization and Clean-Up", "4")):
        assert nodes[label].number == number and nodes[label].number_predicted and nodes[label].expected
    optional = nodes["Physical Synthesis"]
    assert optional.optional and optional.number is None and not optional.number_predicted
    route = stage_map(fw)["impl_1/route_design"]
    assert "1 Build RT Design" in {n.label for n in flat(route)}
    d = route.to_dict()
    assert "number" in d["children"][0] and "number_predicted" in d["children"][0]


def test_finished_step_placeholders_are_not_numbered(tmp_path, cfg, report_cache, catalogs):
    fw = ProjectSource(qick(tmp_path), cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    skipped = [n for n in flat(stage_map(fw)["impl_1/route_design"]) if n.expected]
    assert skipped and all(n.number is None and not n.number_predicted for n in skipped)


# ---------------------------------------------------------------- browse
def test_browse_kinds_hidden_sorting(tmp_path):
    (tmp_path / "zeta.runs").mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.xpr").write_text("")
    run = tmp_path / "impl_1"
    run.mkdir()
    (run / "runme.log").write_text("")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "plain").mkdir()
    (tmp_path / "b.log").write_text("")
    (tmp_path / "c.xpr").write_text("")
    (tmp_path / "notes.txt").write_text("")
    out = browse(str(tmp_path), "/h", {str(proj)}, ["/r"])
    assert out["path"] == os.path.realpath(tmp_path) and out["home"] == "/h" and out["recent"] == ["/r"]
    names = [(e["name"], e["type"], e["kind"], e["live"]) for e in out["entries"]]
    assert names == [("impl_1", "dir", "run", False), ("plain", "dir", None, False),
                     ("proj", "dir", "project_dir", True), ("zeta.runs", "dir", "runs", False),
                     ("b.log", "file", "log", False), ("c.xpr", "file", "xpr", False)]
    assert out["parent"] == os.path.dirname(os.path.realpath(tmp_path))


def test_browse_errors_and_limits(tmp_path, monkeypatch):
    from vmon import browse as mod
    import pytest
    with pytest.raises(mod.BrowseError) as exc:
        browse("/proc/self", "/h", set(), [])
    assert exc.value.status == 403
    with pytest.raises(mod.BrowseError) as exc:
        browse(str(tmp_path / "missing"), "/h", set(), [])
    assert exc.value.status == 404
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        if not os.access(locked, os.R_OK):          # skipped when running as root
            with pytest.raises(mod.BrowseError) as exc:
                browse(str(locked), "/h", set(), [])
            assert exc.value.status == 403
    finally:
        locked.chmod(0o700)
    monkeypatch.setattr(mod, "MAX_ENTRIES", 5)
    for i in range(10):
        (tmp_path / ("f%d.log" % i)).write_text("")
    assert len(browse(str(tmp_path), "/h", set(), [])["entries"]) == 5
    assert browse("/", "/h", set(), [])["parent"] is None


def test_live_paths_and_http_browse(tmp_path, cfg, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    runs = lockin(tmp_path / "w", impl_pid=os.getpid()) if (tmp_path / "w").mkdir() is None else None
    monitor = make_monitor(tmp_path, cfg)
    monitor.add_path(str(runs))
    monitor.tick()
    fw = next(iter(monitor.firmwares.values()))
    fw.live = True                                  # tracked as live regardless of process scan
    assert str(runs) in live_paths([fw]) and str(runs.parent) in live_paths([fw])
    server = make_server(monitor, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    try:
        out = json.load(urllib.request.urlopen(base + "/api/browse"))
        assert out["path"] == os.path.realpath(home) and out["home"] == str(home)
        assert str(runs) in out["recent"]
        out = json.load(urllib.request.urlopen("%s/api/browse?path=%s" % (base, runs.parent)))
        entry = next(e for e in out["entries"] if e["name"] == runs.name)
        assert entry["kind"] == "runs" and entry["live"] is True
        for bad, code in (("/proc", 403), (str(tmp_path / "nope"), 404)):
            try:
                urllib.request.urlopen("%s/api/browse?path=%s" % (base, bad))
                assert False
            except urllib.error.HTTPError as err:
                assert err.code == code
    finally:
        server.shutdown()
        monitor.stop()
