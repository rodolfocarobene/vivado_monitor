import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_project import qick
from vmon import remote as remote_mod
from vmon.config import load_config
from vmon.monitor import Monitor
from vmon.server import make_server


def serve(monitor):
    server = make_server(monitor, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def get_json(url):
    status, _, body = get(url)
    return status, json.loads(body)


def closed_port_url():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return "http://127.0.0.1:%d" % sock.getsockname()[1]


def make_monitor(cfg, tmp_path, name, runs=None, remotes=()):
    monitor = Monitor(cfg, recent_file=tmp_path / name / "recent.json", remotes=remotes)
    monitor.discovery.discover = lambda: []        # ignore real Vivado processes
    fw_id = monitor.add_path(str(runs)) if runs else None
    monitor.tick()
    return monitor, fw_id


@pytest.fixture()
def pair(tmp_path, cfg):
    """A 'server' vmon with one finished build and a 'front' vmon aggregating it, both on 127.0.0.1."""
    runs = qick(tmp_path)
    back, fw_id = make_monitor(cfg, tmp_path, "back", runs)
    back_server, back_url = serve(back)
    front, _ = make_monitor(cfg, tmp_path, "front", remotes=[("srv", back_url)])
    front_server, front_url = serve(front)
    front.remotes.poll(front.remotes.get("srv"))
    front.tick()
    yield {"back": back, "front": front, "fw": fw_id, "ns": "srv~" + fw_id, "url": front_url, "back_url": back_url,
           "back_server": back_server, "runs": runs}
    for server, monitor in ((front_server, front), (back_server, back)):
        server.shutdown()
        monitor.stop()


# ---------------------------------------------------------------- config and validation
def test_parse_spec_and_validation():
    assert remote_mod.parse_spec("buildsrv=http://127.0.0.1:9001/") == ("buildsrv", "http://127.0.0.1:9001")
    assert remote_mod.parse_spec("a_b-1=https://example.org") == ("a_b-1", "https://example.org")
    for bad in ("nourl", "=http://x:1", "bad name=http://x:1", "a~b=http://x:1", "x" * 33 + "=http://x:1",
                "n=ftp://x:1", "n=file:///etc/passwd", "n=http://user:pw@x:1", "n=http://x:1/path",
                "n=http://x:1?q=1", "n=http://", "n=http://x:99999", "n=javascript:alert(1)"):
        with pytest.raises(ValueError):
            remote_mod.parse_spec(bad)


def test_redact_keeps_scheme_host_port():
    assert remote_mod.redact("https://build.example.org:9443/") == "https://build.example.org:9443"
    assert remote_mod.redact("http://[::1]:9001") == "http://[::1]:9001"


def test_config_hosts_and_defaults(tmp_path):
    assert remote_mod.settings(load_config()) == ([], 3.0, 5.0)
    user = tmp_path / "flows.toml"
    user.write_text('[remote]\nhosts = [{name = "buildsrv", url = "http://127.0.0.1:9001"}]\ninterval_s = 7\n')
    hosts, interval, timeout = remote_mod.settings(load_config(user))
    assert hosts == [("buildsrv", "http://127.0.0.1:9001")] and (interval, timeout) == (7.0, 5.0)
    for body in ('hosts = [{name = "bad name", url = "http://x:1"}]', 'hosts = [{name = "a", url = "ssh://x"}]',
                 'hosts = ["http://x:1"]', "interval_s = 0", 'timeout_s = "5"'):
        user.write_text("[remote]\n" + body + "\n")
        with pytest.raises(ValueError):
            remote_mod.settings(load_config(user))


def test_duplicate_names_rejected(cfg, tmp_path):
    with pytest.raises(ValueError):
        remote_mod.Remotes([("a", "http://127.0.0.1:1"), ("a", "http://127.0.0.1:2")])
    remotes = remote_mod.Remotes([("a", "http://127.0.0.1:1")])
    with pytest.raises(ValueError):
        remotes.add("a", "http://127.0.0.1:2")


def test_command_line_remote_wins_over_config(tmp_path):
    user = tmp_path / "flows.toml"
    user.write_text('[remote]\nhosts = [{name = "a", url = "http://127.0.0.1:1"}, {name = "b", url = "http://127.0.0.1:2"}]\n')
    monitor = Monitor(load_config(user), recent_file=tmp_path / "r.json", remotes=[("a", "http://127.0.0.1:3")])
    assert {n: r.url for n, r in monitor.remotes.remotes.items()} == {"b": "http://127.0.0.1:2", "a": "http://127.0.0.1:3"}


def test_ssh_argv():
    assert remote_mod.ssh_argv("me@build.example.org:9000", 9101) == [
        "ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
        "-L", "9101:127.0.0.1:9000", "--", "me@build.example.org"]
    assert remote_mod.ssh_argv("build", 9101)[-3:] == ["9101:127.0.0.1:8765", "--", "build"]
    for bad in ("-oProxyCommand=x", "a b@c", "me@host:0", "me@host:70000", ""):
        with pytest.raises(ValueError):
            remote_mod.ssh_argv(bad, 9101)


# ---------------------------------------------------------------- local state is unchanged without remotes
def test_state_without_remotes(tmp_path, cfg):
    monitor, fw_id = make_monitor(cfg, tmp_path, "solo", qick(tmp_path))
    state = json.loads(monitor.state_json())
    assert state["remotes"] == []
    assert [f["id"] for f in state["firmwares"]] == [fw_id] and state["firmwares"][0]["host"] is None
    assert not monitor.remotes


# ---------------------------------------------------------------- merge and status
def test_merged_state_namespaces_remote_firmwares(pair):
    state = json.loads(pair["front"].state_json())
    [fw] = state["firmwares"]
    assert fw["id"] == pair["ns"] and fw["host"] == "srv" and fw["name"] == "top"
    [status] = state["remotes"]
    assert status["name"] == "srv" and status["online"] is True and status["error"] is None
    assert status["url"] == pair["back_url"] and status["firmwares"] == 1 and status["last_ok"]


def test_local_and_remote_firmwares_side_by_side(pair, tmp_path, cfg):
    (tmp_path / "other").mkdir()
    runs = qick(tmp_path / "other")
    local_id = pair["front"].add_path(str(runs))
    pair["front"].tick()
    fws = {f["id"]: f for f in json.loads(pair["front"].state_json())["firmwares"]}
    assert fws[local_id]["host"] is None and fws[pair["ns"]]["host"] == "srv"


def test_remote_change_wakes_sse_waiters(pair):
    front, back = pair["front"], pair["back"]
    version = front.version
    back._body = back._body.replace('"status":"done"', '"status":"failed"', 1)
    front.remotes.poll(front.remotes.get("srv"))
    assert front.version > version


def test_offline_remote_keeps_stale_snapshot_and_recovers(pair):
    front, remote = pair["front"], pair["front"].remotes.get("srv")
    pair["back_server"].shutdown()
    pair["back_server"].server_close()
    version = front.version
    front.remotes.poll(remote)
    state = json.loads(front.state_json())
    [status] = state["remotes"]
    assert status["online"] is False and status["error"] and status["last_ok"]
    assert pair["back_url"] not in status["error"]
    assert [f["id"] for f in state["firmwares"]] == [pair["ns"]]       # kept, shown as stale by the UI
    assert front.version > version
    version = front.version
    front.remotes.poll(remote)                                          # still down: nothing new to publish
    assert front.version == version


def test_poll_error_kinds(tmp_path):
    class Bad(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = b"not json" if self.path == "/api/state" else b""
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bad)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        remotes = remote_mod.Remotes([("bad", "http://127.0.0.1:%d" % server.server_address[1]),
                                      ("gone", closed_port_url())], timeout=2)
        for remote in remotes.remotes.values():
            remotes.poll(remote)
        bad, gone = remotes.statuses()
        assert not bad["online"] and bad["error"] == "not a vmon state"
        assert not gone["online"] and gone["last_ok"] is None
        # Windows retries the SYN after an RST, so a closed port may only time out within the poll timeout
        allowed = ("refused", "timed out") if sys.platform == "win32" else ("refused",)
        assert any(word in gone["error"] for word in allowed)
        assert remotes.firmwares_json() == ""
    finally:
        server.shutdown()


def test_aggregated_firmwares_of_a_remote_are_not_chained(pair, tmp_path, cfg):
    third, _ = make_monitor(cfg, tmp_path, "third", remotes=[("srv", pair["back_url"])])
    third_server, third_url = serve(third)
    top, _ = make_monitor(cfg, tmp_path, "top", remotes=[("mid", third_url)])
    try:
        third.remotes.poll(third.remotes.get("srv"))
        top.remotes.poll(top.remotes.get("mid"))
        assert json.loads(top.state_json())["firmwares"] == []
    finally:
        third_server.shutdown()


# ---------------------------------------------------------------- proxy
def first_node(pair):
    state = json.loads(pair["back"].state_json())
    return state["firmwares"][0]["flows"][0]["stages"][2]["id"]


def test_proxy_messages_and_log_use_the_remote_id(pair):
    node = first_node(pair).replace("/", "%2F")
    ns = pair["ns"]
    status, via = get_json("%s/api/messages?fw=%s&node=%s&limit=5" % (pair["url"], ns, node))
    _, direct = get_json("%s/api/messages?fw=%s&node=%s&limit=5" % (pair["back_url"], pair["fw"], node))
    assert status == 200 and via == direct and via["items"]
    status, log = get_json("%s/api/log?fw=%s&node=%s&tail=3" % (pair["url"], ns, node))
    assert status == 200 and log["lines"]
    status, tri = get_json("%s/api/triage?fw=%s&node=%s" % (pair["url"], ns, node))
    assert status == 200 and "groups" in tri


def test_proxy_report_validation_is_the_remotes(pair):
    state = json.loads(pair["front"].state_json())
    route = [s for s in state["firmwares"][0]["flows"][0]["stages"] if s["id"].endswith("route_design")][0]
    path = route["reports"][0]["path"]
    status, headers, body = get("%s/api/report?fw=%s&path=%s" % (pair["url"], pair["ns"], path))
    assert status == 200 and headers["Content-Type"].startswith("text/plain") and body
    status, _, body = get("%s/api/report?fw=%s&path=/etc/passwd" % (pair["url"], pair["ns"]))
    assert status == 403 and json.loads(body)["error"]


def test_proxy_history_rewrites_ids_and_streams_downloads(pair):
    ns, url = pair["ns"], pair["url"]
    status, listing = get_json("%s/api/history?fw=%s" % (url, ns))
    assert status == 200 and listing["builds"]
    build = listing["builds"][0]
    assert build["fw_id"] == ns and build["host"] == "srv"
    assert listing["firmwares"][0]["id"] == ns
    status, record = get_json("%s/api/history/build?fw=%s&build=%s" % (url, ns, build["build"]))
    assert status == 200 and record["fw_id"] == ns
    status, _, _ = get("%s/api/history/build?fw=%s&build=nope" % (url, ns))
    assert status == 404
    status, headers, body = get("%s/api/history/summary?fw=%s&build=%s&format=md&download=1" % (url, ns, build["build"]))
    assert status == 200 and headers["Content-Disposition"].startswith('attachment; filename="')
    assert headers["Content-Type"].startswith("text/markdown") and body.startswith(b"#")
    assert get("%s/api/history/summary?fw=%s&build=%s&format=pdf" % (url, ns, build["build"]))[0] == 400


def test_proxy_artifact_download_headers(pair):
    ns, url = pair["ns"], pair["url"]
    build = get_json("%s/api/history?fw=%s" % (url, ns))[1]["builds"][0]
    art = build["artifacts"][0]
    status, headers, body = get("%s/api/history/artifact?fw=%s&build=%s&path=%s" % (url, ns, build["build"], art["path"]))
    assert status == 200 and headers["Content-Type"] == "application/octet-stream"
    assert "attachment" in headers["Content-Disposition"] and len(body) == art["size"]


def test_proxy_compare_passes_query(pair):
    ns, url = pair["ns"], pair["url"]
    build = get_json("%s/api/history?fw=%s" % (url, ns))[1]["builds"][0]["build"]
    status, body = get_json("%s/api/history/compare?fw=%s&a=%s&b=%s" % (url, ns, build, build))
    assert status == 400 and body["error"]                               # the remote's own "pick two different builds"


def test_global_history_includes_remote_builds(pair):
    status, listing = get_json(pair["url"] + "/api/history")
    assert status == 200 and listing["unreachable"] == []
    assert [b["fw_id"] for b in listing["builds"]] == [pair["ns"]]
    assert [f["id"] for f in listing["firmwares"]] == [pair["ns"]]


def test_global_history_marks_offline_remote(pair):
    pair["back_server"].shutdown()
    pair["back_server"].server_close()
    pair["front"].remotes.poll(pair["front"].remotes.get("srv"))
    status, listing = get_json(pair["url"] + "/api/history")
    assert status == 200 and listing["unreachable"] == ["srv"] and listing["builds"] == []


def test_delete_is_forwarded_to_the_remote(pair):
    req = urllib.request.Request("%s/api/firmware?fw=%s" % (pair["url"], pair["ns"]), method="DELETE")
    assert json.load(urllib.request.urlopen(req, timeout=10))["ok"]
    assert pair["fw"] not in pair["back"].firmwares


def test_unreachable_remote_is_502(pair):
    pair["back_server"].shutdown()
    pair["back_server"].server_close()
    for path in ("/api/messages?fw=%s&node=x", "/api/history?fw=%s", "/api/history/summary?fw=%s&build=1",
                 "/api/report?fw=%s&path=/x"):
        status, body = get_json(pair["url"] + path % pair["ns"])
        assert status == 502 and "srv" in body["error"] and pair["back_url"] not in body["error"]
    req = urllib.request.Request("%s/api/firmware?fw=%s" % (pair["url"], pair["ns"]), method="DELETE")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=10)
    assert err.value.code == 502


def test_unknown_host_prefix_is_404(pair):
    for fw in ("nope~abc", "~abc", "srv2~abc"):
        for path in ("/api/messages?fw=%s&node=x", "/api/history?fw=%s", "/api/log?fw=%s&node=x"):
            assert get(pair["url"] + path % fw)[0] == 404
    req = urllib.request.Request(pair["url"] + "/api/firmware?fw=nope~abc", method="DELETE")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=10)
    assert err.value.code == 404


def test_msgrule_notify_and_watch_stay_local(pair, tmp_path):
    front = pair["front"]
    data = json.dumps({"path": str(pair["runs"])}).encode()
    req = urllib.request.Request(pair["url"] + "/api/watch", data=data, method="POST")
    assert json.load(urllib.request.urlopen(req, timeout=10))["id"]
    assert "srv~" not in json.dumps(list(front.sources))
    assert "channels" in get_json(pair["url"] + "/api/notify")[1]


class Recorder(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        type(self).hits.append(self.path)
        if self.server.redirect_to:
            self.send_response(302)
            self.send_header("Location", self.server.redirect_to + self.path)
            self.send_header("Content-Length", "0")
        else:
            self.send_response(200)
            self.send_header("Content-Length", "2")
        self.end_headers()
        if not self.server.redirect_to:
            self.wfile.write(b"{}")


def recorder(redirect_to=None):
    class Handler(Recorder):
        hits = []

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.redirect_to = redirect_to
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, Handler.hits, "http://127.0.0.1:%d" % server.server_address[1]


def test_never_contacts_a_host_outside_the_config(pair):
    evil, hits, evil_url = recorder()
    try:
        for fw in ("evil~x", "%s~x" % evil_url, "evil~x~y"):
            for path in ("/api/messages?fw=%s&node=n", "/api/history?fw=%s", "/api/history/summary?fw=%s&build=1"):
                assert get(pair["url"] + path % urllib.request.quote(fw, safe=""))[0] == 404
        assert hits == []
    finally:
        evil.shutdown()


def test_redirects_from_a_remote_are_not_followed(tmp_path, cfg):
    evil, evil_hits, evil_url = recorder()
    redirecting, _, redirect_url = recorder(redirect_to=evil_url)
    front, _ = make_monitor(cfg, tmp_path, "front", remotes=[("srv", redirect_url)])
    server, url = serve(front)
    try:
        front.remotes.poll(front.remotes.get("srv"))
        assert json.loads(front.state_json())["remotes"][0]["online"] is False
        assert get(url + "/api/messages?fw=srv~x&node=n")[0] == 502
        assert get(url + "/api/history?fw=srv~x")[0] == 502
        assert evil_hits == []
    finally:
        for s in (server, redirecting, evil):
            s.shutdown()


def test_environment_proxies_are_ignored(tmp_path, cfg, monkeypatch):
    evil, hits, evil_url = recorder()
    monkeypatch.setenv("http_proxy", evil_url)
    monkeypatch.setenv("no_proxy", "")
    back, _ = make_monitor(cfg, tmp_path, "back")
    back_server, back_url = serve(back)
    remotes = remote_mod.Remotes([("srv", back_url)])
    try:
        remotes.poll(remotes.get("srv"))
        assert remotes.statuses()[0]["online"] is True and hits == []
    finally:
        back_server.shutdown()
        evil.shutdown()
