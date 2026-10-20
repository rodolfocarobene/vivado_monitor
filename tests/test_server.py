import json
import threading
import urllib.error
import urllib.request

from conftest import FIXTURES, build_runs
from test_project import qick
from vmon.monitor import Monitor
from vmon.server import make_server


def test_http_api(tmp_path, cfg):
    runs = qick(tmp_path)
    monitor = Monitor(cfg, recent_file=tmp_path / "recent.json")
    monitor.discovery.discover = lambda: []        # ignore real Vivado processes
    fw_id = monitor.add_path(str(runs))
    monitor.tick()
    server = make_server(monitor, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    try:
        state = json.load(urllib.request.urlopen(base + "/api/state"))
        fw = state["firmwares"][0]
        assert fw["id"] == fw_id and fw["status"] == "done" and state["version"] == 1
        node = fw["flows"][0]["stages"][2]
        msgs = json.load(urllib.request.urlopen("%s/api/messages?fw=%s&node=%s&limit=5" % (base, fw_id, node["id"].replace("/", "%2F"))))
        assert msgs["node_id"] == node["id"] and len(msgs["items"]) <= 5
        log = json.load(urllib.request.urlopen("%s/api/log?fw=%s&node=%s&tail=3" % (base, fw_id, node["id"].replace("/", "%2F"))))
        assert log["lines"]
        route = [s for s in fw["flows"][0]["stages"] if s["id"].endswith("route_design")][0]
        path = route["reports"][0]["path"]
        text = urllib.request.urlopen("%s/api/report?fw=%s&path=%s" % (base, fw_id, path)).read()
        assert text
        try:
            urllib.request.urlopen("%s/api/report?fw=%s&path=/etc/passwd" % (base, fw_id))
            assert False
        except urllib.error.HTTPError as err:
            assert err.code == 403
        try:
            urllib.request.urlopen(base + "/static/../../pyproject.toml")
            assert False
        except urllib.error.HTTPError as err:
            assert err.code == 404
        req = urllib.request.Request("%s/api/firmware?fw=%s" % (base, fw_id), method="DELETE")
        assert json.load(urllib.request.urlopen(req))["ok"]
        assert json.load(urllib.request.urlopen(base + "/api/state"))["firmwares"] == []
    finally:
        server.shutdown()
        monitor.stop()
