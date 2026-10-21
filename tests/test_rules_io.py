import json
import urllib.error
import urllib.request

import pytest

from test_v2 import make_monitor, raw, serve
from vmon import rules_io
from vmon.triage import PRIORITIES, TriageConfig, score_groups


def doc(rules, **extra):
    return {"format": "vmon-message-rules", "version": 1, "exported_at": 1, "rules": rules, **extra}


def http(base, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data, {"Content-Type": "application/json"}, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.load(resp), resp
    except urllib.error.HTTPError as err:
        return err.code, json.load(err), err


# ---------------------------------------------------------------- format
def test_parse_new_and_legacy_shapes():
    rules, invalid = rules_io.parse_file(doc({"Synth 8-327": {"priority": "high", "note": "latch"},
                                              "X 1-1": {"priority": "mute"}}), PRIORITIES)
    assert rules == {"Synth 8-327": "high", "X 1-1": "mute"} and invalid == []
    legacy, invalid = rules_io.parse_file({"Synth 8-327": "high", "X 1-1": "mute"}, PRIORITIES)
    assert legacy == rules and invalid == []


@pytest.mark.parametrize("data", [
    [], "x", doc({}, format="other"), doc({}, version=2), doc({}, version="1"), doc({}, version=True),
    {"format": "vmon-message-rules", "version": 1}, doc([]), doc({}, exported_by=5),
    doc({"X %d" % i: {"priority": "high"} for i in range(rules_io.MAX_RULES + 1)})])
def test_unusable_files_are_rejected(data):
    with pytest.raises(rules_io.RulesFileError):
        rules_io.parse_file(data, PRIORITIES)


def test_invalid_entries_are_listed():
    rules, invalid = rules_io.parse_file(doc({
        "Good 1-1": {"priority": "low"}, "Bad 1-2": {"priority": "pin"}, "": {"priority": "high"},
        "L" * 201: {"priority": "high"}, "Note 1-3": {"priority": "high", "note": "n" * 201},
        "Str 1-4": "high", "None 1-5": {"priority": None}, "Num 1-6": {"priority": "high", "note": 3}}), PRIORITIES)
    assert rules == {"Good 1-1": "low"}
    assert {e["id"][:8] for e in invalid} == {"Bad 1-2", "", "L" * 8, "Note 1-3", "Str 1-4", "None 1-5", "Num 1-6"}
    assert all(e["error"] for e in invalid)
    assert rules_io.parse_file({"Str 1-4": "high", "Bad 1-2": "pin"}, PRIORITIES)[1] == [
        {"id": "Bad 1-2", "error": "priority must be one of %s" % ", ".join(PRIORITIES)}]


def test_export_doc_has_no_identity():
    out = rules_io.export_doc({"B 1-1": "mute", "A 1-1": "high"})
    assert out["format"] == "vmon-message-rules" and out["version"] == 1 and out["exported_by"] == ""
    assert list(out["rules"]) == ["A 1-1", "B 1-1"] and out["rules"]["A 1-1"] == {"priority": "high"}
    assert rules_io.export_doc({}, "me\x00\n team")["exported_by"] == "me team"


# ---------------------------------------------------------------- diffs
def test_plan_merge_replace_keep_mine():
    current = {"A 1-1": "high", "B 1-1": "mute", "C 1-1": "low"}
    incoming = {"A 1-1": "high", "B 1-1": "high", "D 1-1": "mute"}
    result, s = rules_io.plan(current, incoming, "merge")
    assert result == {"A 1-1": "high", "B 1-1": "high", "C 1-1": "low", "D 1-1": "mute"}
    assert s["added"] == [{"id": "D 1-1", "priority": "mute"}] and s["removed"] == [] and s["unchanged"] == 1
    assert s["changed"] == [{"id": "B 1-1", "from": "mute", "to": "high"}]
    result, s = rules_io.plan(current, incoming, "merge", keep_mine=True)
    assert result["B 1-1"] == "mute" and s["changed"] == [] and s["kept_mine"] == 1 and len(s["added"]) == 1
    result, s = rules_io.plan(current, incoming, "replace", keep_mine=True)
    assert result == incoming and s["removed"] == [{"id": "C 1-1", "priority": "low"}] and len(s["changed"]) == 1
    with pytest.raises(ValueError):
        rules_io.plan(current, incoming, "append")


# ---------------------------------------------------------------- API
def test_import_api_dry_run_apply_and_scoring(tmp_path, cfg):
    monitor = make_monitor(tmp_path, cfg)
    rules_file = tmp_path / "cfg" / "message_rules.json"
    monitor.set_msgrule("A 1-1", "high")
    monitor.set_msgrule("B 1-1", "mute")
    server, base = serve(monitor)
    try:
        status, exported, resp = http(base, "/api/msgrules/export")
        assert status == 200 and exported["rules"] == {"A 1-1": {"priority": "high"}, "B 1-1": {"priority": "mute"}}
        assert resp.headers["Content-Disposition"].startswith('attachment; filename="vmon_message_rules_20')
        exported["rules"]["B 1-1"]["priority"] = "high"
        exported["rules"]["Synth 8-327"] = {"priority": "mute"}
        before = rules_file.read_text()
        status, s, _ = http(base, "/api/msgrules/import", {"mode": "merge", "dry_run": True, "data": exported})
        assert status == 200 and s["applied"] is False and s["unchanged"] == 1
        assert s["added"] == [{"id": "Synth 8-327", "priority": "mute"}] and s["invalid"] == []
        assert s["changed"] == [{"id": "B 1-1", "from": "mute", "to": "high"}]
        assert rules_file.read_text() == before                       # dry run never writes
        status, s, _ = http(base, "/api/msgrules/import", {"mode": "merge", "dry_run": False, "data": exported})
        assert status == 200 and s["applied"] is True
        assert json.loads(rules_file.read_text()) == {"A 1-1": "high", "B 1-1": "high", "Synth 8-327": "mute"}
        assert not list(rules_file.parent.glob("*.tmp"))
        groups = score_groups([raw("Synth 8-327")], TriageConfig(cfg.data), monitor.user_rules.rules, None)
        assert groups[0]["muted"] and groups[0]["user_priority"] == "mute"
        status, s, _ = http(base, "/api/msgrules/import", {"mode": "replace", "dry_run": False, "data": {"A 1-1": "low"}})
        assert s["removed"] == [{"id": "B 1-1", "priority": "high"}, {"id": "Synth 8-327", "priority": "mute"}]
        assert json.loads(rules_file.read_text()) == {"A 1-1": "low"}
        assert http(base, "/api/msgrules/export")[1]["rules"] == {"A 1-1": {"priority": "low"}}
    finally:
        server.shutdown()
        monitor.stop()


def test_import_api_errors(tmp_path, cfg):
    monitor = make_monitor(tmp_path, cfg)
    server, base = serve(monitor)
    try:
        imp = "/api/msgrules/import"
        good = doc({"A 1-1": {"priority": "high"}})
        assert http(base, imp, {"mode": "merge", "data": doc({}, version=9)})[0] == 400
        assert http(base, imp, {"mode": "append", "data": good})[0] == 400
        assert http(base, imp, {"data": good})[0] == 400
        assert http(base, imp, {"mode": "merge", "dry_run": "no", "data": good})[0] == 400
        assert http(base, imp, {"mode": "merge"})[0] == 400
        bad = doc({"A 1-1": {"priority": "high"}, "B 1-1": {"priority": "pin"}})
        status, s, _ = http(base, imp, {"mode": "merge", "dry_run": True, "data": bad})
        assert status == 200 and [e["id"] for e in s["invalid"]] == ["B 1-1"]
        status, s, _ = http(base, imp, {"mode": "merge", "dry_run": False, "data": bad})
        assert status == 422 and s["applied"] is False and "A 1-1" not in monitor.user_rules.rules
        big = {"mode": "merge", "data": doc({}), "pad": "x" * (rules_io.MAX_BODY_BYTES + 1)}
        assert http(base, imp, big)[0] == 413
        assert http(base, "/api/msgrules/export", {})[0] == 404       # POST on the export route
    finally:
        server.shutdown()
        monitor.stop()
