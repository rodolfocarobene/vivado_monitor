import json
import stat
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from conftest import FIXTURES
from vmon.config import load_config
from vmon.monitor import Monitor
from vmon.notify import Notifier, _latin1, describe_error, redact_url
from vmon.server import make_server

SECRET = "s3cr3t-tok3n"
PATH_SECRET = "T0P/SECRET/path"


class Receiver:
    """Fake HTTP endpoint on 127.0.0.1 that records every request (and answers `status`)."""

    def __init__(self, status=200):
        self.got = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_any(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.got.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
                self.send_response(outer.status)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            do_POST = do_PUT = handle_any

        self.status = status
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def rx():
    r = Receiver()
    yield r
    r.close()


def spec(**over):
    base = {"enabled": True, "kinds": ["step_failed", "run_failed", "run_done"],
            "codes": ["timing_fail", "process_gone"], "min_level": "warning", "timeout_s": 2, "max_per_minute": 20,
            "title_prefix": "vmon"}
    base.update(over)
    return base


def fw(name="lockin", path="/proj/lockin.runs"):
    return SimpleNamespace(id="fw1", name=name, path=path, flows=[])


def ev(kind="step_failed", level="error", code=None, t=None, node="n/route", title="lockin: Route failed", message="boom"):
    return {"t": time.time() + 1 if t is None else t, "kind": kind, "level": level, "code": code,
            "node_id": node, "title": title, "message": message}


def fake_command(tmp_path, exit_code=0):
    out = tmp_path / "argv.txt"
    script = tmp_path / "fake-notify"
    script.write_text('#!/bin/sh\nfor a in "$@"; do printf "%%s\\n" "$a"; done >> %s\nprintf "%%s\\n" "---" >> %s\nexit %d\n'
                      % (out, out, exit_code))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, out


# ---------------------------------------------------------------- config
def test_defaults_are_disabled(cfg):
    notifier = Notifier(cfg.data["notify"])
    status = notifier.status()
    assert status["enabled"] is False
    assert all(not c["enabled"] for c in status["channels"])
    assert notifier.submit(fw(), ev()) is False
    assert notifier._thread is None


def test_user_override_is_deep_merged(tmp_path):
    user = tmp_path / "flows.toml"
    user.write_text('[notify]\nenabled = true\n[notify.ntfy]\nenabled = true\nurl_env = "VMON_T_URL"\n')
    config = load_config(user)
    n = Notifier(config.data["notify"], env={"VMON_T_URL": "https://ntfy.example.org/topic-x"})
    status = n.status()
    ntfy = [c for c in status["channels"] if c["name"] == "ntfy"][0]
    assert status["enabled"] and ntfy["enabled"] and ntfy["configured"]
    assert ntfy["target"] == "https://ntfy.example.org"
    assert "run_failed" in status["kinds"]                 # untouched defaults survive the merge


def test_env_secrets_and_unconfigured():
    n = Notifier(spec(slack={"enabled": True, "webhook_url_env": "HOOK"}), env={})
    slack = [c for c in n.channels if c.name == "slack"][0]
    assert not slack.configured() and slack.target() == ""
    n.env = {"HOOK": "https://hooks.example.org/services/" + PATH_SECRET}
    assert slack.configured() and slack.target() == "https://hooks.example.org"


# ---------------------------------------------------------------- filtering
def test_filter_kinds_codes_and_level():
    n = Notifier(spec())
    assert n.wanted(ev("step_failed")) and n.wanted(ev("run_done", "info"))
    assert not n.wanted(ev("step_done", "info")) and not n.wanted(ev("step_started", "info"))
    assert not n.wanted(ev("attempt_started", "info"))
    assert n.wanted(ev("alert", "warning", "timing_fail"))
    assert not n.wanted(ev("alert", "warning", "congestion"))          # code not listed
    n2 = Notifier(spec(min_level="error"))
    assert not n2.wanted(ev("alert", "warning", "timing_fail")) and n2.wanted(ev("alert", "error", "timing_fail"))
    assert n2.wanted(ev("run_done", "info"))                           # min_level is for alerts only


def test_only_new_events_and_dedupe(rx):
    n = Notifier(spec(webhook={"enabled": True, "url": rx.base + "/h"}))
    assert n.submit(fw(), ev(t=n.t0 - 100)) is False                   # happened before vmon started
    event = ev()
    assert n.submit(fw(), event) is True
    assert n.submit(fw(), dict(event)) is False                        # same key
    assert n.submit(fw(), ev(node="n/other", t=event["t"])) is True
    assert n.wait_idle()
    assert len(rx.got) == 2


def test_monitor_startup_does_not_notify(tmp_path, cfg, rx):
    from test_project import qick
    cfg.data["notify"].update(enabled=True)
    cfg.data["notify"]["webhook"].update(enabled=True, url=rx.base + "/h")
    monitor = Monitor(cfg, recent_file=tmp_path / "recent.json")
    monitor.discovery.discover = lambda: []
    monitor.add_path(str(qick(tmp_path)))
    monitor.tick()
    monitor.tick()
    monitor.notifier.wait_idle()
    assert rx.got == []                                                # finished build seen at startup: silence


def test_monitor_live_transition_notifies(tmp_path, cfg, rx):
    from test_project import qick
    cfg.data["notify"].update(enabled=True, kinds=["run_done"])
    cfg.data["notify"]["webhook"].update(enabled=True, url=rx.base + "/h")
    monitor = Monitor(cfg, recent_file=tmp_path / "recent.json")
    monitor.discovery.discover = lambda: []
    fw_id = monitor.add_path(str(qick(tmp_path)))
    monitor.tick()
    monitor._seen[fw_id]["status"] = "running"                         # pretend it was running a tick ago
    monitor.tick()
    assert monitor.notifier.wait_idle()
    bodies = [json.loads(r["body"]) for r in rx.got]
    assert [b["kind"] for b in bodies] == ["run_done"] and bodies[0]["fw_id"] == fw_id


# ---------------------------------------------------------------- rate limit
def test_rate_limit_coalesces(rx):
    now = [1000.0]
    n = Notifier(spec(max_per_minute=2, webhook={"enabled": True, "url": rx.base + "/h"}), clock=lambda: now[0])
    for i in range(5):
        n.handle(n._message("lockin", "fw1", ev(node="n/%d" % i, t=now[0]), "b", "/p"))
    assert len(rx.got) == 2 and n._overflow == 3
    now[0] += 61
    n._flush_overflow()
    last = json.loads(rx.got[-1]["body"])
    assert len(rx.got) == 3 and last["title"] == "3 more events" and n._overflow == 0


# ---------------------------------------------------------------- channels
def message(n, **over):
    event = ev(**over)
    return n._message("lockin", "fw1", event, "route_design: WNS -0.123", "/proj/lockin.runs")


def test_webhook_request(rx):
    n = Notifier(spec(webhook={"enabled": True, "url": rx.base + "/hook?x=1"}))
    n.handle(message(n))
    req = rx.got[0]
    payload = json.loads(req["body"])
    assert req["method"] == "POST" and req["path"] == "/hook?x=1"
    assert req["headers"]["Content-Type"] == "application/json"
    assert set(payload) == {"firmware", "fw_id", "kind", "code", "level", "title", "body", "t", "project"}
    assert payload["firmware"] == "lockin" and payload["project"] == "/proj/lockin.runs" and payload["level"] == "error"


def test_ntfy_request(rx):
    n = Notifier(spec(ntfy={"enabled": True, "url": rx.base + "/mytopic", "token_env": "TOK",
                            "priority_error": "urgent"}), env={"TOK": SECRET})
    n.handle(message(n))
    req = rx.got[0]
    assert req["method"] == "POST" and req["path"] == "/mytopic"
    assert req["headers"]["Title"] == "vmon \u00b7 lockin: Route failed"
    assert _latin1("a\u2192b\nc") == "a?b c"                           # headers are latin-1 and one line
    assert req["headers"]["Priority"] == "urgent" and req["headers"]["Tags"] == "rotating_light"
    assert req["headers"]["Authorization"] == "Bearer " + SECRET
    assert req["body"].decode() == "route_design: WNS -0.123\n/proj/lockin.runs"


def test_slack_request(rx):
    n = Notifier(spec(slack={"enabled": True, "webhook_url": rx.base + "/services/A/B"}))
    n.handle(message(n))
    req = rx.got[0]
    text = json.loads(req["body"])["text"]
    assert req["method"] == "POST" and req["path"] == "/services/A/B"
    assert text.startswith("*vmon · lockin: Route failed*\n") and "WNS -0.123" in text


def test_matrix_request_and_unique_txn(rx):
    n = Notifier(spec(matrix={"enabled": True, "homeserver": rx.base + "/", "room_id": "!room:example.org",
                              "access_token": SECRET}))
    n.handle(message(n))
    n.handle(message(n))
    a, b = rx.got
    assert a["method"] == "PUT"
    assert a["path"].startswith("/_matrix/client/v3/rooms/%21room%3Aexample.org/send/m.room.message/vmon-")
    assert a["path"] != b["path"]
    assert a["headers"]["Authorization"] == "Bearer " + SECRET
    body = json.loads(a["body"])
    assert body["msgtype"] == "m.text" and "lockin: Route failed" in body["body"] and "/proj/lockin.runs" in body["body"]


def test_desktop_argv_no_shell(tmp_path):
    script, out = fake_command(tmp_path)
    n = Notifier(spec(desktop={"enabled": True, "command": str(script), "urgency_error": "critical"}))
    n.handle(message(n))
    n.handle(message(n, kind="run_done", level="info", title="x; touch /tmp/pwned"))
    lines = out.read_text().split("\n")
    assert lines[:6] == ["-u", "critical", "-a", "vmon", "--", "vmon · lockin: Route failed"]
    assert lines[6] == "route_design: WNS -0.123" and lines[7] == "/proj/lockin.runs"
    assert "-u\nnormal" in out.read_text() and "vmon · x; touch /tmp/pwned" in lines


def test_desktop_command_list(tmp_path):
    script, out = fake_command(tmp_path)
    n = Notifier(spec(desktop={"enabled": True, "command": [str(script), "--extra"]}))
    n.handle(message(n))
    assert out.read_text().split("\n")[0] == "--extra"


# ---------------------------------------------------------------- failures
def test_failure_isolated_and_redacted(capsys):
    r = Receiver(status=500)
    try:
        url = "%s/%s?token=%s" % (r.base, PATH_SECRET, SECRET)
        n = Notifier(spec(ntfy={"enabled": True, "url": url, "token": SECRET},
                          webhook={"enabled": True, "url": r.base + "/ok"}))
        n.handle(message(n))
        n.handle(message(n))
    finally:
        r.close()
    status = n.status()
    blob = json.dumps(status) + capsys.readouterr().err
    assert SECRET not in blob and PATH_SECRET not in blob and "token=" not in blob
    assert status["last_error"]["error"] == "HTTP 500"
    names = {c["name"]: c for c in status["channels"]}
    assert names["ntfy"]["error"] == "HTTP 500" and names["ntfy"]["target"].startswith("http://127.0.0.1:")


def test_failure_logged_once_per_channel(capsys):
    n = Notifier(spec(webhook={"enabled": True, "url": "http://127.0.0.1:9/" + PATH_SECRET}))
    for _ in range(3):
        n.handle(message(n))
    err = capsys.readouterr().err
    assert err.count("notify webhook failed") == 1 and PATH_SECRET not in err


def test_error_strings_hide_details():
    assert describe_error(ValueError("unknown url type: 'x'/secret")) == "invalid URL"
    assert redact_url("https://user:pw@h.example.org:8443/a/b?c=d") == "https://h.example.org:8443"
    assert redact_url("not a url") == "invalid URL" and redact_url("file:///etc/passwd") == "invalid URL"


def test_desktop_failure_and_missing_command(tmp_path):
    script, _ = fake_command(tmp_path, exit_code=3)
    n = Notifier(spec(desktop={"enabled": True, "command": str(script)}))
    assert n._deliver(message(n)) == [{"name": "desktop", "ok": False, "error": "exit 3"}]
    n = Notifier(spec(desktop={"enabled": True, "command": str(tmp_path / "nope")}))
    assert n._deliver(message(n)) == [{"name": "desktop", "ok": False, "error": "not configured"}]


def test_submit_never_raises():
    n = Notifier(spec(webhook={"enabled": True, "url": "http://127.0.0.1:9/x"}))
    assert n.submit(fw(), {"kind": "step_failed"}) is False             # malformed event


# ---------------------------------------------------------------- API
def serve(tmp_path, cfg):
    monitor = Monitor(cfg, recent_file=tmp_path / "recent.json")
    monitor.discovery.discover = lambda: []
    server = make_server(monitor, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def test_api_status_and_test(tmp_path, cfg, rx):
    script, out = fake_command(tmp_path)
    secret_url = rx.base + "/" + PATH_SECRET
    cfg.data["notify"].update(enabled=True)
    cfg.data["notify"]["webhook"].update(enabled=True, url=secret_url)
    cfg.data["notify"]["desktop"].update(enabled=True, command=str(script))
    cfg.data["notify"]["slack"].update(enabled=True)           # enabled but not configured
    server, base = serve(tmp_path, cfg)
    try:
        raw = urllib.request.urlopen(base + "/api/notify").read().decode()
        status = json.loads(raw)
        assert PATH_SECRET not in raw and status["enabled"] is True
        names = {c["name"]: c for c in status["channels"]}
        assert names["webhook"]["target"] == rx.base and names["webhook"]["configured"]
        assert names["slack"]["enabled"] and not names["slack"]["configured"]
        assert names["desktop"]["target"] == "fake-notify" and not names["ntfy"]["enabled"]
        req = urllib.request.Request(base + "/api/notify/test", data=b"{}", method="POST")
        raw = urllib.request.urlopen(req).read().decode()
        results = {r["name"]: r for r in json.loads(raw)["results"]}
        assert PATH_SECRET not in raw
        assert results["webhook"]["ok"] and results["desktop"]["ok"]
        assert results["slack"] == {"name": "slack", "ok": False, "error": "not configured"}
        assert json.loads(rx.got[0]["body"])["kind"] == "test" and "Test notification" in out.read_text()
    finally:
        server.shutdown()
        server.server_close()


def test_api_disabled_by_default(tmp_path, cfg):
    server, base = serve(tmp_path, cfg)
    try:
        assert json.load(urllib.request.urlopen(base + "/api/notify"))["enabled"] is False
        req = urllib.request.Request(base + "/api/notify/test", data=b"{}", method="POST")
        assert json.load(urllib.request.urlopen(req)) == {"results": []}
    finally:
        server.shutdown()
        server.server_close()
