"""Build history: store, classification, backfill, API validation."""
import json
import os
import threading
import urllib.error
import urllib.request
from urllib.parse import quote

from conftest import build_runs
from test_project import qick
from test_v2 import make_monitor
from vmon import history
from vmon.model import Timing
from vmon.server import make_server


def rec(build="100", fw_id="fw1", result="met", started=100.0, artifacts=()):
    return {"build": build, "fw_id": fw_id, "firmware": "top", "started_at": started, "result": result,
            "artifacts": list(artifacts)}


def test_classify():
    final = lambda met: Timing(wns=-1.0 if not met else 0.2, met=met, final=True)
    assert history.classify("done", final(True)) == "met"
    assert history.classify("done", final(False)) == "timing_not_met"
    assert history.classify("done", Timing(wns=-1.0, met=False, final=False)) == "done"
    assert history.classify("done", None) == "done"
    assert history.classify("failed", final(True)) == "failed"
    assert history.classify("stopped", None) == "stopped"


def test_store_dedupe_replace_cap(tmp_path):
    store = history.HistoryStore(tmp_path / "h", cap=3)
    assert store.record(rec("1", started=1.0))
    assert not store.record(rec("1", started=1.0))                     # same key, same result: untouched
    assert store.record(rec("1", result="failed", started=1.0))        # result changed: replaced, not duplicated
    assert [b["result"] for b in store.load("fw1")] == ["failed"]
    for i in range(2, 6):
        store.record(rec(str(i), started=float(i)))
    assert [b["build"] for b in store.load("fw1")] == ["3", "4", "5"]
    assert store.firmwares() == [{"id": "fw1", "name": "top"}]
    assert store.load("../x") == [] and store.load("nope") == []


def test_listing_marks_current(tmp_path):
    f = tmp_path / "a.rpt"
    f.write_text("one")
    st = os.stat(f)
    art = {"kind": "utilization", "label": "U", "path": str(f), "mtime": st.st_mtime, "size": st.st_size}
    store = history.HistoryStore(tmp_path / "h")
    store.record(rec("1", artifacts=[art], started=1.0))
    store.record(rec("2", fw_id="fw2", started=2.0))
    assert [b["build"] for b in store.listing()["builds"]] == ["2", "1"]          # all firmwares, newest first
    assert [b["build"] for b in store.listing("fw1")["builds"]] == ["1"]
    assert store.listing("fw1")["builds"][0]["artifacts"][0]["current"] is True
    f.write_text("changed!")
    assert store.listing("fw1")["builds"][0]["artifacts"][0]["current"] is False
    assert store.artifact("fw1", "1", str(f))[1][0] == 410
    assert store.artifact("fw1", "1", "/etc/passwd")[1][0] == 404
    assert store.artifact("fw1", "9", str(f))[1][0] == 404


def finished_monitor(tmp_path, cfg):
    runs = qick(tmp_path)
    (runs / "impl_1" / "d_1_wrapper.bit").write_bytes(b"\x00BIT" * 1000)
    os.utime(runs / "impl_1" / "d_1_wrapper.bit", (1_004_000.0, 1_004_000.0))
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    return monitor, fw_id


def test_backfill_record(tmp_path, cfg):
    monitor, fw_id = finished_monitor(tmp_path, cfg)
    builds = monitor.history.load(fw_id)
    assert len(builds) == 1
    b = builds[0]
    assert b["fw_id"] == fw_id and b["firmware"] == "top" and b["result"] in ("met", "timing_not_met", "done")
    assert b["started_at"] and b["duration_s"] and len(b["counts"]) == 4
    assert b["timing"] and b["timing"]["final"] is True
    assert b["utilization"] and "LUT" in b["utilization"]
    assert b["steps"] and all(isinstance(v, float) for v in b["steps"].values()) and isinstance(b["phases"], dict)
    assert b["messages"] and all(m["severity"] in ("warning", "critical", "error") and m["count"] > 0 and len(m["text"]) <= 160
                                 for m in b["messages"].values())
    assert b["timing_clocks"] is None or all(set(v) == {"wns", "whs"} for v in b["timing_clocks"].values())
    kinds = {a["kind"] for a in b["artifacts"]}
    assert {"timing_summary", "utilization", "bitstream"} <= kinds
    assert all(set(a) >= {"kind", "label", "path", "mtime", "size"} for a in b["artifacts"])
    monitor.tick()
    monitor.tick()
    assert len(monitor.history.load(fw_id)) == 1                         # dedupe across ticks
    monitor.stop()


def test_failed_build_has_no_old_bitstream(tmp_path, cfg):
    runs = qick(tmp_path)
    bit = runs / "impl_1" / "d_1_wrapper.bit"
    bit.write_bytes(b"old")
    os.utime(bit, (10.0, 10.0))                                          # predates the build
    monitor = make_monitor(tmp_path, cfg)
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    assert "bitstream" not in {a["kind"] for a in monitor.history.load(fw_id)[0]["artifacts"]}
    monitor.stop()


def get(url):
    try:
        return urllib.request.urlopen(url)
    except urllib.error.HTTPError as err:
        return err


def test_history_api(tmp_path, cfg):
    monitor, fw_id = finished_monitor(tmp_path, cfg)
    server = make_server(monitor, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    try:
        data = json.load(get("%s/api/history?fw=%s" % (base, fw_id)))
        assert data["firmwares"] == [{"id": fw_id, "name": "top"}]
        build = data["builds"][0]
        assert json.load(get(base + "/api/history"))["builds"][0]["build"] == build["build"]
        assert all(a["current"] for a in build["artifacts"])
        assert not any(k in build for k in history.HEAVY)                  # light list
        full = json.load(get("%s/api/history/build?fw=%s&build=%s" % (base, fw_id, build["build"])))
        assert full["messages"] and full["phases"] and full["artifacts"][0]["current"] is True
        for bad in ("fw=../etc&build=1", "fw=%s&build=nope" % fw_id, "fw=zzz&build=1", "fw=%s" % fw_id):
            assert get("%s/api/history/build?%s" % (base, bad)).code == 404
        cmp_url = "%s/api/history/compare?fw=%s&a=%s&b=%s" % (base, fw_id, build["build"], build["build"])
        assert get(cmp_url).code == 400                                      # same build twice
        assert get(cmp_url.replace("&b=%s" % build["build"], "&b=nope")).code == 404
        assert get("%s/api/history/compare?fw=../x&a=1&b=2" % base).code == 404
        assert get(cmp_url + "&fw_b=%s" % fw_id).code == 400                 # fw_b naming the same firmware: still one build
        assert get(cmp_url + "&fw_b=zzz").code == 404
        assert get("%s/api/history?fw=../etc" % base).code == 404
        assert json.load(get("%s/api/history?fw=zzz" % base))["builds"] == []

        def url(route, path, b=build["build"]):
            return "%s/api/history/%s?fw=%s&build=%s&path=%s" % (base, route, fw_id, b, quote(path, safe=""))
        rpt = next(a for a in build["artifacts"] if a["kind"] == "timing_summary")
        resp = get(url("report", rpt["path"]))
        assert resp.code == 200 and resp.read()
        for bad in ("/etc/passwd", rpt["path"] + "/../../../etc/passwd", "../../etc/passwd"):
            assert get(url("report", bad)).code == 404
        assert get(url("report", rpt["path"], b="1")).code == 404
        bit = next(a for a in build["artifacts"] if a["kind"] == "bitstream")
        resp = get(url("artifact", bit["path"]))
        assert resp.code == 200 and resp.headers["Content-Type"] == "application/octet-stream"
        assert resp.headers["Content-Disposition"] == 'attachment; filename="d_1_wrapper.bit"'
        assert len(resp.read()) == bit["size"] == 4000
        with open(rpt["path"], "a") as fh:                               # a later build overwrote the report
            fh.write("\n# newer run\n")
        assert get(url("report", rpt["path"])).code == 410
        assert any(not a["current"] for a in json.load(get("%s/api/history?fw=%s" % (base, fw_id)))["builds"][0]["artifacts"])
    finally:
        server.shutdown()
        monitor.stop()


def full(build, started, **kw):
    msg = lambda sev, n, text="t": {"severity": sev, "count": n, "text": text}
    base = {"build": build, "fw_id": "fw1", "firmware": "top", "started_at": started, "duration_s": 100.0, "result": "met",
            "timing": {"wns": 0.1, "tns": 0.0, "whs": 0.05, "ths": 0.0, "final": True}, "counts": [0, 1, 3, 9],
            "utilization": {"LUT": {"used": 100, "available": 1000, "pct": 10.0}},
            "steps": {"synth_design": 60.0, "opt_design": 5.0},
            "messages": {"W1": msg("warning", 2), "CW1": msg("critical", 1, "gone"), "W2": msg("warning", 1)},
            "timing_clocks": {"clk": {"wns": 0.1, "whs": 0.05}}, "artifacts": []}
    return {**base, **kw}, msg


def test_compare_records(tmp_path):
    store = history.HistoryStore(tmp_path / "h")
    a, msg = full("1", 1.0)
    b, _ = full("2", 2.0, duration_s=130.0, result="timing_not_met", counts=[1, 0, 4, 9],
                timing={"wns": -0.2, "tns": -3.0, "whs": 0.05, "ths": 0.0, "final": True},
                utilization={"LUT": {"used": 150, "available": 1000, "pct": 15.0}, "DSP": {"used": 1, "available": 10, "pct": 10.0}},
                steps={"synth_design": 70.0, "place_design": 20.0},
                messages={"W1": msg("warning", 5), "E1": msg("error", 1, "boom"), "W2": msg("warning", 1)},
                timing_clocks={"clk": {"wns": -0.2, "whs": 0.05}, "clk2": {"wns": 0.3, "whs": 0.1}})
    store.record(a)
    store.record(b)
    d, err = store.compare("fw1", "1", "2")
    assert err is None and d["a"]["build"] == "1" and d["b"]["result"] == "timing_not_met"
    assert d["duration"] == {"a": 100.0, "b": 130.0, "delta": 30.0}
    assert d["timing"]["metrics"]["wns"] == {"a": 0.1, "b": -0.2, "delta": -0.3}
    assert d["timing"]["metrics"]["tns"]["delta"] == -3.0 and d["timing"]["final"] == {"a": True, "b": True}
    assert [(c["name"], c["wns"]["delta"]) for c in d["timing"]["clocks"]] == [("clk", -0.3), ("clk2", None)]
    assert d["utilization"]["LUT"]["pct"]["delta"] == 5.0 and d["utilization"]["LUT"]["used"]["delta"] == 50
    assert d["utilization"]["DSP"]["pct"] == {"a": None, "b": 10.0, "delta": None}
    steps = {s["step"]: s for s in d["steps"]}
    assert list(steps) == ["synth_design", "opt_design", "place_design"]            # a's order, then b-only steps
    assert steps["synth_design"]["delta"] == 10.0 and steps["opt_design"]["b"] is None and steps["place_design"]["a"] is None
    m = d["messages"]
    assert [e["id"] for e in m["new"]] == ["E1"] and m["new"][0]["a"] is None and m["new"][0]["b"] == 1
    assert [e["id"] for e in m["removed"]] == ["CW1"] and m["removed"][0]["text"] == "gone"
    assert [(e["id"], e["delta"]) for e in m["changed"]] == [("W1", 3)]
    assert m["counts"] == {"new": 1, "removed": 1, "changed": 1} and m["available"] == {"a": True, "b": True}
    assert m["totals"]["error"] == {"a": 0, "b": 1, "delta": 1} and m["totals"]["warning"]["delta"] == 1


def test_compare_old_records_and_errors(tmp_path):
    store = history.HistoryStore(tmp_path / "h")
    store.record(rec("1", started=1.0))                                  # pre-enrichment record: no steps/messages/timing
    new, _ = full("2", 2.0)
    store.record(new)
    store.record({**rec("3", fw_id="fw2", started=3.0)})
    d, err = store.compare("fw1", "1", "2")
    assert err is None and d["messages"]["available"] == {"a": False, "b": True}
    assert d["messages"]["new"] == [] and d["timing"]["metrics"]["wns"] == {"a": None, "b": 0.1, "delta": None}
    assert d["timing"]["clocks"] is None and d["utilization"]["LUT"]["pct"]["a"] is None
    assert all(s["a"] is None for s in d["steps"]) and d["duration"]["delta"] is None
    assert store.compare("fw1", "1", "3")[1][0] == 404                   # build of another firmware
    assert store.compare("fw1", "1", "9")[1][0] == 404
    assert store.compare("../x", "1", "2")[1][0] == 404
    assert store.compare("fw1", "1", "1")[1][0] == 400
    assert "messages" not in store.listing("fw1")["builds"][1] and store.build("fw1", "2")["messages"]


def test_messages_of_caps_and_filters():
    groups = [{"id": "I", "severity": "info", "count": 99, "text": "x"},
              {"id": "W", "severity": "warning", "count": 9, "text": "y" * 300},
              {"id": "E", "severity": "error", "count": 1, "text": "z"},
              {"id": "C", "severity": "critical", "count": 2, "text": "c"}]
    out = history.messages_of(groups, 500)
    assert list(out) == ["E", "C", "W"] and len(out["W"]["text"]) == 160
    assert list(history.messages_of(groups, 2)) == ["E", "C"] and history.messages_of(None, 5) == {}


def test_compare_across_firmwares(tmp_path):
    store = history.HistoryStore(tmp_path / "h")
    store.record({**full("1", 1.0)[0], "project": "/w/top/top.runs"})
    store.record({**full("1", 2.0, fw_id="fw2", firmware="top_backup")[0], "project": "/w/top_backup/top.runs"})
    d, err = store.compare("fw1", "1", "1", "fw2")                       # same build key, different firmware: allowed
    assert err is None and d["fw_id"] == "fw2"
    assert (d["a"]["fw_id"], d["a"]["firmware"], d["a"]["project"]) == ("fw1", "top", "/w/top/top.runs")
    assert (d["b"]["fw_id"], d["b"]["firmware"], d["b"]["project"]) == ("fw2", "top_backup", "/w/top_backup/top.runs")
    assert store.compare("fw1", "1", "1", "fw1")[1][0] == 400
    assert store.compare("fw1", "1", "1", "nope")[1][0] == 404
    assert store.compare("fw1", "1", "1", "../x")[1][0] == 404


def test_live_record_and_compare(tmp_path, cfg):
    monitor, fw_id = finished_monitor(tmp_path, cfg)
    recorded = monitor.history.load(fw_id)[0]["build"]
    live = monitor.live_record(fw_id)
    assert live["build"] == "live" and live["fw_id"] == fw_id and live["live"]["status"] == "done"
    assert monitor.live_record("nope") is None
    server = make_server(monitor, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/api/history/compare?fw=%s" % (server.server_address[1], fw_id)
    try:
        resp = get("%s&a=%s&b=live" % (base, recorded))
        assert resp.code == 200
        data = json.load(resp)
        assert data["b"]["live"]["status"] == "done" and data["b"]["build"] == "live" and not data["a"].get("live")
        assert json.load(get("%s&a=live&b=%s" % (base, recorded)))["a"]["live"]
        assert get("%s&a=live&b=live" % base).code == 400
        assert get("%s&a=%s&b=live&fw_b=zzz" % (base, recorded)).code == 404       # firmware not loaded
        assert get(base.replace(fw_id, "zzz") + "&a=live&b=1").code == 404
        assert [b["build"] for b in monitor.history.load(fw_id)] == [recorded]    # live is never stored
    finally:
        server.shutdown()
        monitor.stop()
