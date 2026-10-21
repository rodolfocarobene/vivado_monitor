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
