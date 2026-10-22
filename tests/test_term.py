import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from vmon import cli, status, term, tui
from vmon.source import Source, fetch_state, filter_state

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "qick", "d_1_wrapper.vdi")
NOW = 1_000_000.0


def fw(**kw):
    base = {"id": "a1", "name": "top", "status": "done", "host": None, "path": "/x/top.runs", "current": None,
            "counts": {"error": 0, "critical": 0, "warning": 2, "info": 9}, "alerts": [], "hints": [],
            "timing": None, "eta": None, "elapsed_s": 125.0, "progress_estimate": None, "started_at": None,
            "attempt": {"n": 1}, "flows": []}
    base.update(kw)
    return base


def state(*fws, remotes=()):
    return {"generated_at": NOW, "firmwares": list(fws), "remotes": list(remotes)}


def final(wns, whs, met):
    return {"wns": wns, "whs": whs, "final": True, "met": met, "stage": "Route · final"}


def cells(f, st=None):
    return [c[0] for c in term.row_cells(f, st or state(f), NOW)]


# ------------------------------------------------------------------ formatting
def test_durations_and_clock():
    assert [term.fmt_dur(x) for x in (None, 4.4, 65, 3725)] == ["-", "4s", "1m 05s", "1h 02m"]
    assert len(term.fmt_clock(NOW)) == 5


def test_outcome_words_match_the_ui():
    assert term.outcome(fw())[1:] == ("Done", "green")
    assert term.outcome(fw(status="running"))[1:] == ("Running", "blue")
    assert term.outcome(fw(status="stopped"))[1:] == ("Stopped", "amber")
    assert term.outcome(fw(status="failed"))[1:] == ("Failed", "red")
    assert term.outcome(fw(timing=final(-0.1, 0.0, False)))[1:] == ("Finished, timing not met", "red")
    assert term.outcome(fw(timing=final(0.1, 0.0, True)))[1:] == ("Done", "green")


def test_non_final_timing_is_marked_and_never_red():
    text, tone = term.timing_cell(fw(timing={"wns": -0.2, "whs": 0.01, "final": False}))
    assert text == "~-0.200/+0.010" and tone == "amber"
    assert term.timing_cell(fw(timing=final(0.006, 0.01, True))) == ("+0.006/+0.010", "green")
    assert term.timing_cell(fw(timing=final(-0.1, 0.0, False)))[1] == "red"
    assert term.timing_cell(fw()) == ("-", "dim")


def test_failed_build_shows_reason_and_attempt():
    node = {"id": "n", "label": "Route Design", "status": "failed", "failure": {"reason": "Out of memory"}}
    f = fw(status="failed", flows=[{"stages": [{"id": "s", "label": "Impl", "status": "failed", "children": [node]}]}],
           attempt={"n": 2})
    assert cells(f)[2] == "#2 Route Design: Out of memory"
    assert term.json_state(state(f))["firmwares"][0]["failure"] == "Route Design: Out of memory"


def test_running_row_has_eta_band_progress_and_live_elapsed():
    f = fw(status="running", started_at=NOW - 3725, current={"label": "Route › Global Routing"},
           progress_estimate=0.42, eta={"expected_end": NOW + 600, "low_end": NOW + 300, "high_end": NOW + 1200})
    row = cells(f)
    assert row[2] == "Route > Global Routing" and row[3] == "~42%" and row[4] == "1h 02m"
    assert row[5].startswith("~") and row[5].count("-") == 1 and "(" in row[5]


def test_stale_remote_is_amber_and_unreachable():
    f = fw(host="srv", status="running", current={"label": "Place"})
    st = state(f, remotes=[{"name": "srv", "online": False, "last_ok": NOW, "error": "timed out"}])
    row = term.row_cells(f, st, NOW)
    assert row[0][0] == "top@srv" and row[1] == ("Running · stale", "amber")
    assert row[2][0].startswith("unreachable") and row[5][0] == "-"
    assert "remote srv unreachable (timed out)" in [t for t, _ in term.remote_lines(st)]


def test_detail_lines_alerts_then_hint_max_three():
    alerts = [{"level": "error", "message": "WHS -0.1"}, {"level": "warning", "message": "util 85%"}]
    lines = term.detail_lines(fw(alerts=alerts, hints=[{"title": "Fix clocks"}]))
    assert [t for t, _ in lines] == ["! WHS -0.1", "! util 85%", "> hint: Fix clocks"]
    assert lines[0][1] == "red" and lines[1][1] == "amber"
    many = term.detail_lines(fw(alerts=[{"level": "warning", "message": "m%d" % i} for i in range(5)]))
    assert len(many) == 3 and many[-1][0] == "! +3 more alerts"


# ------------------------------------------------------------------ width and color
@pytest.mark.parametrize("width", [20, 40, 60, 80, 120])
def test_lines_never_exceed_width(width):
    f = fw(status="running", current={"label": "Route › Global Routing with a very long phase name"},
           alerts=[{"level": "warning", "message": "x" * 200}])
    for line in term.status_lines(state(f, fw(id="b", name="n" * 40, host="h")), width, NOW):
        assert len(term.to_text(line)) <= width


def test_narrow_width_drops_secondary_columns_first():
    out = term.to_text(term.table_lines(state(fw()), 50, NOW)[0])
    assert "NAME" in out and "STATUS" in out and "AL" not in out.split() and "E/CW/W" not in out


def test_clip():
    assert term.clip("abcdef", 4) == "abc…" and term.clip("abc", 4) == "abc" and term.clip("abc", 0) == ""


class Tty(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.mark.parametrize("tty,flag,env,expected", [
    (True, False, {}, True), (False, False, {}, False), (True, True, {}, False),
    (True, False, {"NO_COLOR": "1"}, False), (True, False, {"NO_COLOR": ""}, True),
    (True, False, {"TERM": "dumb"}, False)])
def test_color_rules(tty, flag, env, expected):
    assert term.color_enabled(Tty(tty), flag, env) is expected


def test_paint_only_when_enabled():
    line = [("Done", "green")]
    assert term.to_text(line, False) == "Done"
    assert term.to_text(line, True) == "\x1b[32mDone\x1b[0m"


# ------------------------------------------------------------------ json and exit codes
def test_exit_codes():
    assert term.exit_code(state()) == 3
    assert term.exit_code(state(fw(), fw(status="running"))) == 0
    assert term.exit_code(state(fw(), fw(status="failed"))) == 1
    assert term.exit_code(state(fw(timing=final(-1, 0, False)))) == 1
    assert term.exit_code(state(fw(timing={"wns": -1, "final": False, "met": False}, status="running"))) == 0
    assert term.exit_code(state(fw(status="stopped"))) == 0


def test_json_shape():
    out = term.json_state(state(fw(timing=final(0.1, 0.2, True), alerts=[{"level": "warning", "code": "c", "message": "m"}],
                                   hints=[{"title": "t", "severity": "info", "text": "long"}])))
    item = out["firmwares"][0]
    assert out["exit_code"] == 0 and set(out) == {"generated_at", "exit_code", "firmwares", "remotes"}
    assert item["outcome"] == "done" and item["timing"]["met"] is True and item["hints"] == [{"title": "t", "severity": "info"}]
    json.dumps(out)


# ------------------------------------------------------------------ dispatch and data sources
def test_status_dispatch(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cli.status_mod, "run", lambda argv: seen.append(argv) or 7)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["status", "--json", "p"]) == 7 and seen == [["--json", "p"]]
    (tmp_path / "status").mkdir()
    monkeypatch.setattr(cli, "_is_vmon", lambda *a: True)
    monkeypatch.setattr(cli, "_reuse_running", lambda args: args.paths)
    assert cli.main(["status"]) == ["status"]          # an existing path named status stays a path
    assert len(seen) == 1


def test_tui_flag_is_routed(monkeypatch):
    monkeypatch.setattr(cli.tui_mod, "run", lambda args: (args.tui, args.paths))
    assert cli.main(["--tui", "x"]) == (True, ["x"])
    assert cli.main(["--tui", "--remote", "a=http://127.0.0.1:1"]) == 2


def test_bad_arguments_exit_2():
    with pytest.raises(SystemExit) as exc:
        status.run(["--port", "abc"])
    assert exc.value.code == 2
    assert status.run(["--watch", "0"]) == 2


class Canned(BaseHTTPRequestHandler):
    body = b""

    def do_GET(self):
        self.send_response(200 if self.path == "/api/state" else 404)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def fake_vmon():
    Canned.body = json.dumps(state(fw(name="served", status="failed"), fw(id="b", name="other", path="/y/o.runs"))).encode()
    server = HTTPServer(("127.0.0.1", 0), Canned)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_running_vmon_is_the_data_source(fake_vmon):
    assert fetch_state("127.0.0.1", fake_vmon)["firmwares"][0]["name"] == "served"
    source = Source("127.0.0.1", fake_vmon)
    assert source.mode == "running" and source.monitor is None
    assert [f["name"] for f in source.state()["firmwares"]] == ["served", "other"]


def test_paths_filter_a_running_vmon(fake_vmon, tmp_path):
    runs = tmp_path / "top.runs"
    runs.mkdir()
    got = filter_state(state(fw(path=str(runs.resolve())), fw(id="b", path="/elsewhere")), [str(runs)])
    assert [f["id"] for f in got["firmwares"]] == ["a1"]


def test_status_uses_running_vmon_and_exit_code(fake_vmon):
    out = Tty(False)
    assert status.run(["--port", str(fake_vmon)], out) == 1
    assert "served" in out.getvalue() and "Failed" in out.getvalue() and "\x1b" not in out.getvalue()
    out = Tty(False)
    status.run(["--port", str(fake_vmon), "--json"], out)
    assert json.loads(out.getvalue())["exit_code"] == 1


def test_non_vmon_server_is_not_used():
    assert fetch_state("127.0.0.1", 1) is None


def test_local_one_shot_with_fixture_and_no_recent_write(tmp_path, monkeypatch):
    monkeypatch.setattr("vmon.source.fetch_state", lambda *a, **k: None)
    out = Tty(False)
    assert status.run(["--port", "1", FIXTURE], out) == 0
    assert "d_1_wrapper" in out.getvalue() and "Done" in out.getvalue() and "+0.006/+0.010" in out.getvalue()
    assert not os.path.exists(os.path.join(os.environ["HOME"], ".cache", "vmon", "recent.json"))


def test_local_nothing_found_exits_3(monkeypatch, tmp_path):
    monkeypatch.setattr("vmon.source.fetch_state", lambda *a, **k: None)
    monkeypatch.setattr("vmon.monitor.Discovery.discover", lambda self: [])
    assert status.run(["--port", "1", str(tmp_path / "nothing")], Tty(False)) == 3


# ------------------------------------------------------------------ tui model
def tree():
    child = {"id": "c1", "label": "Global Routing", "status": "running", "children": []}
    return [{"stages": [
        {"id": "s1", "label": "Synthesis", "status": "done", "elapsed_s": 60, "children": [
            {"id": "s1a", "label": "Init", "status": "done", "children": []}]},
        {"id": "s2", "label": "Route", "status": "running", "started_at": NOW - 30, "children": [child],
         "timing": {"wns": -0.1, "whs": 0.0, "final": False}},
        {"id": "s3", "label": "Bitstream", "status": "pending", "children": []}]}]


def model(*fws):
    m = tui.Model("test")
    m.update(state(*fws))
    return m


def plain(m, h=20, w=80):
    return [term.to_text(line) for line in m.render(h, w, NOW)]


def test_selection_movement_and_clamping():
    m = model(fw(id="a"), fw(id="b"), fw(id="c"))
    for key, want in [("j", "b"), ("down", "c"), ("j", "c"), ("k", "b"), ("up", "a"), ("k", "a"), ("pgdn", "c")]:
        m.handle(key)
        assert m.selected_id == want
    m.update(state(fw(id="a")))
    assert m.selected_id == "a"                 # the selected firmware vanished


def test_expand_collapse_firmware_and_stages():
    m = model(fw(flows=tree(), alerts=[{"level": "warning", "message": "util high"}]))
    assert "util high" not in "\n".join(plain(m)).split("Alerts")[0]
    m.handle("enter")
    assert "! util high" in plain(m)[2:4][0] + plain(m)[3]
    m.handle("left")
    assert "a1" not in m.expanded
    m.handle("tab")
    assert m.focus == "detail" and [n["id"] for n, _ in m.stage_rows()] == ["s1", "s2", "c1", "s3"]
    m.handle("enter")                           # Synthesis opens
    assert [n["id"] for n, _ in m.stage_rows()][:2] == ["s1", "s1a"]
    m.handle("left")
    assert [n["id"] for n, _ in m.stage_rows()][:2] == ["s1", "s2"]
    m.handle("j"); m.handle("left")             # running nodes can be collapsed too
    assert "c1" not in [n["id"] for n, _ in m.stage_rows()]


def test_keys_return_actions_and_help():
    m = model(fw())
    assert m.handle("q") == "quit" and m.handle("r") == "refresh"
    m.handle("h")
    assert m.show_help and "terminal view" in plain(m)[0]
    assert m.handle("q") is None and not m.show_help      # any key closes help, it does not quit


def test_render_fits_any_size_and_shows_stage_pane():
    m = model(fw(flows=tree(), status="running", started_at=NOW - 100, current={"label": "Route › Global Routing"},
                 alerts=[{"level": "warning", "message": "WHS drifting"}], hints=[{"title": "Check clocks"}]))
    frame = plain(m, 24, 90)
    text = "\n".join(frame)
    assert len(frame) == 24 and all(len(l) <= 90 for l in frame)
    assert "● Route" in text and "~-0.100/+0.000" in text and "Global Routing" in text
    assert "! WHS drifting" in text and "> Check clocks" in text and frame[-1].startswith("q quit")
    for h, w in [(1, 10), (3, 20), (6, 40), (30, 200)]:
        out = plain(m, h, w)
        assert len(out) == h and all(len(l) <= w for l in out)


def test_render_empty_state_and_error():
    m = model()
    assert "No firmware found" in "\n".join(plain(m))
    m.update(None)
    assert "no answer" in plain(m)[0]


def test_selected_row_scrolls_into_view():
    m = model(*[fw(id="f%d" % i, name="fw%d" % i) for i in range(30)])
    for _ in range(25):
        m.handle("j")
    assert "> fw25" in "\n".join(plain(m, 16, 80))


def test_draw_uses_a_window_like_object():
    class Win:
        def __init__(self):
            self.calls = []

        def getmaxyx(self):
            return 3, 10

        def erase(self):
            pass

        def refresh(self):
            pass

        def addnstr(self, y, x, text, n, attr):
            self.calls.append((y, x, text[:n], attr))

    if tui.curses is None:
        pytest.skip("curses is not available on this platform")
    win = Win()
    tui.draw(win, [[("ab", "red"), ("cd", "dim")], []], lambda tone: {"red": 1, "dim": 2}[tone])
    assert win.calls == [(0, 0, "ab", 1), (0, 2, "cd", 2)]


def test_fallback_without_curses(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(tui, "curses", None)
    monkeypatch.setattr(tui.status, "run", lambda argv: calls.append(argv) or 0)
    args = cli_args(paths=["p"])
    assert tui.run(args) == 0
    assert "refreshing text view" in capsys.readouterr().err
    assert calls[0][0] == "p" and "--watch" in calls[0]


def cli_args(**kw):
    import argparse
    base = dict(paths=[], port=8765, host="127.0.0.1", interval=1.0, config=None)
    return argparse.Namespace(**{**base, **kw})


def test_key_names():
    assert tui.key_name(ord("q")) == "q" and tui.key_name(10) == "enter" and tui.key_name(9) == "tab"
    assert tui.key_name(-1) == "" and tui.key_name(300) in ("", "up", "down", "left", "right", "pgup", "pgdn", "enter")


@pytest.mark.skipif(sys.platform == "win32", reason="curses is POSIX-only")
def test_curses_arrow_keys_are_named():
    assert tui.key_name(tui.curses.KEY_UP) == "up" and tui.key_name(tui.curses.KEY_RIGHT) == "right"
