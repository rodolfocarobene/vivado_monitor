import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from conftest import marker, touch
from test_project import lockin, qick
from vmon import sysstats
from vmon.monitor import Monitor
from vmon.server import make_server
from vmon.triage import BaselineStore, TriageConfig, UserRules, score_groups


def raw(msg_id, severity="warning", count=3, text="some text", line=10):
    return {"id": msg_id, "severity": severity, "count": count, "text": text,
            "first_line": line, "last_line": line, "log": "x.vds"}


def make_monitor(tmp_path, cfg):
    monitor = Monitor(cfg, recent_file=tmp_path / "cache" / "recent.json",
                      rules_file=tmp_path / "cfg" / "message_rules.json")
    monitor.discovery.discover = lambda: []        # ignore real Vivado processes
    return monitor


# ---------------------------------------------------------------- triage scoring
def test_triage_ordering_and_reasons(cfg):
    tcfg = TriageConfig(cfg.data)
    groups = score_groups([
        raw("Synth 8-7129", count=4000, text="Port x in module y is either unconnected or has no load"),
        raw("Synth 8-327", count=2, text="inferring latch for variable 'q_reg'"),
        raw("Timing 38-282", "critical", 1, "The design failed to meet the timing requirements."),
        raw("Foo 1-1", count=50, text="plain warning"),
        raw("Vivado 12-180", count=1, text="No cells matched 'get_cells foo'"),
    ], tcfg, {}, None)
    order = [g["id"] for g in groups]
    assert order[0] == "Timing 38-282"
    assert order.index("Vivado 12-180") < order.index("Synth 8-327") < order.index("Foo 1-1")
    assert order[-1] == "Synth 8-7129"
    by_id = {g["id"]: g for g in groups}
    latch = by_id["Synth 8-327"]
    assert latch["priority"] == "high" and "rule: latch inferred" in latch["reasons"]
    assert "keyword: latch" in latch["reasons"] and "rare (2×)" in latch["reasons"]
    assert "rare (1×)" in by_id["Timing 38-282"]["reasons"]
    assert any(r.startswith("keyword:") for r in by_id["Vivado 12-180"]["reasons"])
    assert any("very frequent" in r for r in by_id["Synth 8-7129"]["reasons"])
    assert all(g["delta"] is None and g["new"] is False for g in groups)    # no baseline


def test_triage_user_override(cfg):
    tcfg = TriageConfig(cfg.data)
    plain = score_groups([raw("Foo 1-1", count=50)], tcfg, {}, None)[0]
    high = score_groups([raw("Foo 1-1", count=50)], tcfg, {"Foo 1-1": "high"}, None)[0]
    assert high["score"] > plain["score"] and high["user_priority"] == "high"
    assert "user: marked high" in high["reasons"]
    muted = score_groups([raw("Synth 8-327")], tcfg, {"Synth 8-327": "mute"}, None)[0]
    assert muted["muted"] and muted["priority"] == "high"       # user wins, rule still reported


def test_triage_novelty(cfg):
    tcfg = TriageConfig(cfg.data)
    groups = score_groups([raw("A 1-1", count=50), raw("B 1-1", count=50), raw("C 1-1", count=20)],
                          tcfg, {}, {"A 1-1": 50, "C 1-1": 10})
    by_id = {g["id"]: g for g in groups}
    assert by_id["B 1-1"]["new"] and "new since last build" in by_id["B 1-1"]["reasons"]
    assert by_id["B 1-1"]["delta"] == 50 and by_id["A 1-1"]["delta"] == 0 and by_id["C 1-1"]["delta"] == 10
    assert not by_id["A 1-1"]["new"]
    assert groups[0]["id"] == "B 1-1"


def test_user_rules_roundtrip(tmp_path):
    path = tmp_path / "cfg" / "message_rules.json"
    rules = UserRules(path)
    rules.set("Synth 8-327", "high")
    assert json.loads(path.read_text()) == {"Synth 8-327": "high"}
    assert UserRules(path).rules == {"Synth 8-327": "high"}
    with pytest.raises(ValueError):
        rules.set("Synth 8-327", "urgent")
    rules.set("Synth 8-327", None)
    assert json.loads(path.read_text()) == {}
    UserRules(tmp_path / "other.json").set("Nope 1-1", None)
    assert not (tmp_path / "other.json").exists()


def test_baseline_store_rotation(tmp_path):
    store = BaselineStore(tmp_path / "msgs")
    assert store.baseline("fw", "b1") is None
    store.record("fw", "b1", {"A": 1})
    assert store.baseline("fw", "b1") is None            # same build: nothing earlier to compare with
    assert store.baseline("fw", "b2") == {"A": 1}        # next build compares with the last finished one
    store.record("fw", "b2", {"A": 2, "B": 1})
    assert store.baseline("fw", "b2") == {"A": 1}
    store.record("fw", "b2", {"A": 3})                   # idempotent per build
    assert store.baseline("fw", "b2") == {"A": 1}
    assert BaselineStore(tmp_path / "msgs").baseline("fw", "b3") == {"A": 3}      # persisted


def test_triage_on_real_firmware(tmp_path, cfg):
    runs = qick(tmp_path)
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    result = monitor.triage(fw_id)
    assert result["baseline"] is False and result["groups"]
    scores = [g["score"] for g in result["groups"]]
    assert scores == sorted(scores, reverse=True)
    top = monitor.firmwares[fw_id].top_messages
    assert 0 < len(top) <= 5 and top[0]["id"] == result["groups"][0]["id"]
    assert all(g["severity"] in ("warning", "critical", "error") for g in top)
    assert (tmp_path / "cache" / "msgs" / (fw_id + ".json")).exists()   # finished build stored
    first = result["groups"][0]
    assert first["nodes"] and first["log"]
    msgs = monitor.sources[fw_id].messages(None, None, 5, first["id"])
    assert msgs["items"] and all(i["id"] == first["id"] or i["text"][:60] == first["id"] for i in msgs["items"])
    muted_id = first["id"]
    monitor.set_msgrule(muted_id, "mute")
    assert muted_id not in [g["id"] for g in monitor.triage(fw_id)["groups"]]
    assert muted_id in [g["id"] for g in monitor.triage(fw_id, include_muted=True)["groups"]]
    assert muted_id not in [g["id"] for g in monitor.firmwares[fw_id].top_messages]


# ---------------------------------------------------------------- system stats
def test_system_stats_parsing():
    before = sysstats.parse_cpu_times("cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 1 1 1\n")
    after = sysstats.parse_cpu_times("cpu  200 0 200 800 100 0 0 0 0 0\n")
    assert before == (1000, 800) and after == (1300, 900)
    assert sysstats.cpu_percent(before, after) == pytest.approx(66.7)
    assert sysstats.cpu_percent(None, after) == 0.0
    mem = sysstats.parse_meminfo("MemTotal:  16384000 kB\nMemAvailable: 8192000 kB\nSwapTotal: 2048000 kB\n"
                                 "SwapFree: 1024000 kB\n")
    snap = sysstats.system_snapshot(12.5, mem, sysstats.parse_loadavg("1.50 1.0 0.5 1/100 99\n"), 8)
    assert snap["mem_total_mb"] == 16000.0 and snap["mem_used_mb"] == 8000.0
    assert snap["swap_used_mb"] == 1000.0 and snap["load1"] == 1.5 and snap["cpu_count"] == 8
    stat = "123 (vivado (x) y) S 77 1 1 0 -1 0 0 0 0 0 40 10 0 0 20 0 1 0 100 0 0"
    assert sysstats.parse_proc_stat(stat) == (77, 50)
    assert sysstats.parse_status_rss_kb("Name:\tx\nVmRSS:\t  2048 kB\n") == 2048


def test_process_resources_sum_descendants(tmp_path):
    proc = tmp_path / "proc"

    def add(pid, ppid, ticks, rss_kb):
        d = proc / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "stat").write_text("%d (vivado) S %d 1 1 0 -1 0 0 0 0 0 %d 0 0 0 20 0 1 0 1 0 0" % (pid, ppid, ticks))
        (d / "status").write_text("VmRSS:\t%d kB\n" % rss_kb)

    add(10, 1, 100, 1024)
    add(11, 10, 100, 2048)       # child
    add(12, 1, 100, 4096)        # unrelated
    sampler = sysstats.Sampler(str(proc))
    first = sampler.resources({"fw": [10]}, now=100.0)["fw"]
    assert first == {"cpu_pct": 0.0, "rss_mb": 3.0}
    add(10, 1, 100 + sysstats.CLK_TCK, 1024)
    add(11, 10, 100 + sysstats.CLK_TCK // 2, 2048)
    second = sampler.resources({"fw": [10], "other": []}, now=101.0)
    assert second["fw"]["cpu_pct"] == pytest.approx(150.0) and second["other"] is None


def test_state_has_system_and_resources(tmp_path, cfg):
    runs = lockin(tmp_path, impl_pid=os.getpid())
    monitor = make_monitor(tmp_path, cfg)
    monitor.add_path(str(runs))
    monitor.tick()
    state = json.loads(monitor.state_json())
    assert state["system"]["cpu_count"] >= 1 and state["system"]["mem_total_mb"] > 0
    assert state["settings"] == {"interval": 1.0} and state["tick"] >= 1
    assert state["firmwares"][0]["resources"] is None      # no live pids discovered


# ---------------------------------------------------------------- utilization
def test_utilization_headline(tmp_path, cfg):
    runs = qick(tmp_path)
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    util = monitor.firmwares[fw_id].utilization
    assert util["report"].endswith("utilization_placed.rpt") and util["step"]
    names = [r["name"] for r in util["rows"]]
    assert names == [n for n in cfg.data["ui"]["headline_resources"] if n in names]
    assert "LUT" in names and "FF" in names
    lut = util["rows"][names.index("LUT")]
    assert lut["used"] <= lut["available"] and lut["pct"] is not None
    cfg.data["ui"]["headline_resources"] = ["DSP", "LUT"]
    monitor.tick()
    assert [r["name"] for r in monitor.firmwares[fw_id].utilization["rows"]] == ["DSP", "LUT"]


# ---------------------------------------------------------------- events
def test_events_only_for_live_transitions(tmp_path, cfg):
    runs = lockin(tmp_path, impl_pid=os.getpid())
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    assert monitor.firmwares[fw_id].events == []           # already-finished steps: no events
    impl = runs / "impl_1"
    touch(impl / ".place_design.end.rst", 1_000_900.0)
    marker(impl / ".phys_opt_design.begin.rst", pid=os.getpid(), mtime=1_001_000.0)
    monitor.tick()
    kinds = [(e["kind"], e["node_id"]) for e in monitor.firmwares[fw_id].events]
    assert ("step_done", "impl_1/place_design") in kinds
    assert ("step_started", "impl_1/phys_opt_design") in kinds
    touch(impl / ".vivado.end.rst", 1_002_000.0)
    monitor.tick()
    events = monitor.firmwares[fw_id].events
    assert events[-1]["kind"] == "run_done" and events[-1]["level"] == "info"
    assert all(set(e) == {"t", "kind", "level", "code", "node_id", "title", "message"} for e in events)
    monitor.tick()
    assert len(monitor.firmwares[fw_id].events) == len(events)     # no repeats


def test_events_failed_step(tmp_path, cfg):
    runs = lockin(tmp_path, impl_pid=os.getpid())
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    touch(runs / "impl_1" / ".place_design.error.rst", 1_000_900.0)
    monitor.tick()
    kinds = [e["kind"] for e in monitor.firmwares[fw_id].events]
    assert "step_failed" in kinds


# ---------------------------------------------------------------- HTTP
def serve(monitor):
    server = make_server(monitor, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def test_settings_endpoint(tmp_path, cfg):
    monitor = make_monitor(tmp_path, cfg)
    server, base = serve(monitor)
    try:
        assert post(base + "/api/settings", {"interval": 2.5}) == {"interval": 2.5}
        assert monitor.interval == 2.5
        assert json.load(urllib.request.urlopen(base + "/api/state"))["settings"]["interval"] == 2.5
        for bad in (0.1, 61, "fast", None):
            with pytest.raises(urllib.error.HTTPError) as err:
                post(base + "/api/settings", {"interval": bad})
            assert err.value.code == 400
        assert monitor.interval == 2.5
    finally:
        server.shutdown()
        monitor.stop()


def test_triage_endpoints(tmp_path, cfg):
    runs = qick(tmp_path)
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    server, base = serve(monitor)
    try:
        triage = json.load(urllib.request.urlopen("%s/api/triage?fw=%s&limit=3" % (base, fw_id)))
        assert triage["baseline"] is False and 0 < len(triage["groups"]) <= 3
        top = triage["groups"][0]
        msgs = json.load(urllib.request.urlopen(
            "%s/api/messages?fw=%s&id=%s&limit=2" % (base, fw_id, urllib.parse.quote(top["id"]))))
        assert msgs["items"] and msgs["items"][0]["log"] == top["log"]
        around = json.load(urllib.request.urlopen("%s/api/log?fw=%s&log=%s&around=%d&context=3" % (
            base, fw_id, urllib.parse.quote(top["log"]), top["first_line"])))
        assert around["start_line"] <= top["first_line"] <= around["end_line"] and around["lines"]
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen("%s/api/log?fw=%s&log=/etc/passwd&around=1" % (base, fw_id))
        assert err.value.code == 404
        assert post(base + "/api/msgrule", {"id": top["id"], "priority": "mute"}) == {"ok": True}
        assert json.loads((tmp_path / "cfg" / "message_rules.json").read_text()) == {top["id"]: "mute"}
        after = json.load(urllib.request.urlopen("%s/api/triage?fw=%s" % (base, fw_id)))
        assert top["id"] not in [g["id"] for g in after["groups"]]
        with pytest.raises(urllib.error.HTTPError) as err:
            post(base + "/api/msgrule", {"id": "X 1-1", "priority": "bogus"})
        assert err.value.code == 400
    finally:
        server.shutdown()
        monitor.stop()


def test_info_messages_are_never_promoted(cfg):
    tcfg = TriageConfig(cfg.data)
    info = score_groups([raw("Constraints 18-11670", "info", 1, "Building netlist checker database")],
                        tcfg, {}, {})[0]
    assert info["score"] <= 0 and info["new"] is True


def test_group_nodes_scoped_to_stage(tmp_path, cfg):
    runs = qick(tmp_path)
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    fw = monitor.firmwares[fw_id]
    stage = fw.flows[0].stages[0]
    result = monitor.triage(fw_id, stage.id, ["warning", "critical", "error"])
    assert result and result["groups"] and all(g["nodes"] for g in result["groups"])
    assert monitor.triage(fw_id, "nope/none") is None
