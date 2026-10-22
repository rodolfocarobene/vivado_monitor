"""Recommended actions: config validation, merging, every condition type, the built-in set."""
import re
import textwrap
import tomllib

import pytest

from vmon import config as config_mod
from vmon import hints as hints_mod
from vmon.model import Firmware, Flow, Node, Timing

with open(config_mod.DEFAULT_FLOWS, "rb") as _fh:      # shipped defaults only, never the developer's own config
    DEFAULTS = config_mod.Config(tomllib.load(_fh))
BUILTIN = DEFAULTS.hints


def step(step_id, status="done", **kw):
    return Node(id="impl_1/" + step_id, label=step_id.replace("_", " ").title(), kind="step", status=status, **kw)


def path(kind="setup", slack=-0.2, route=50.0, logic=50.0, levels=5, fanout=None, net="top/u1/n"):
    return {"id": 0, "type": kind, "slack": slack, "status": "VIOLATED" if slack < 0 else "MET", "levels": levels,
            "route_pct": route, "logic_pct": logic, "max_fanout": fanout, "fanout_net": net if fanout else None}


def timed(step_id, wns=0.1, whs=0.1, final=True, paths=(), carried=None, status="done"):
    node = step(step_id, status)
    node.timing = Timing(wns=wns, whs=whs, final=final, paths=list(paths), carried=carried or {}, source="report")
    return node


def firmware(nodes=(), status="done", alerts=(), messages=(), utilization=None, synth=None):
    stages = ([synth] if synth else []) + list(nodes)
    fw = Firmware(id="x", name="x", kind="project", path="/x", status=status)
    fw.flows = [Flow(id="f", label="f", stages=stages)]
    fw.alerts = list(alerts)
    fw.top_messages = list(messages)
    fw.utilization = utilization
    return fw


def msg(msg_id, text="text", severity="warning", count=3):
    return {"id": msg_id, "text": text, "severity": severity, "count": count}


def one(spec_extra, **kw):
    spec = {"id": "t", "title": "T", "text": "why", "when": {}}
    spec.update(spec_extra)
    return hints_mod.compile_hints({"hints": [spec]})


def fired(hints, fw):
    return [h["id"] for h in hints_mod.evaluate(hints, fw, DEFAULTS)]


def builtin(hint_id):
    return [h for h in BUILTIN if h.id == hint_id]


def ids_for(fw, **kw):
    return [h["id"] for h in hints_mod.evaluate(BUILTIN, fw, DEFAULTS, kw.get("messages"))]


# ---------------------------------------------------------------- config validation
def test_builtin_set_loads_and_is_grounded():
    assert 10 <= len(BUILTIN) <= 14
    assert len({h.id for h in BUILTIN}) == len(BUILTIN)
    for hint in BUILTIN:
        assert hint.actions and hint.severity in ("info", "warning")


def test_unknown_condition_fails_with_hint_id():
    with pytest.raises(hints_mod.ConfigError, match=r"hint 'bad': unknown condition 'wns_below'"):
        hints_mod.compile_hints({"hints": [{"id": "bad", "title": "t", "text": "x", "when": {"wns_below": 1}}]})


@pytest.mark.parametrize("when,fragment", [
    ({"timing": {"wns_lte": 0}}, "unknown key"),
    ({"worst_path": {"type": "setup"}}, "needs at least one"),
    ({"worst_path": {"type": "both", "levels_ge": 1}}, "setup"),
    ({"convergence_trend": ["sideways"]}, "unknown value"),
    ({"status": ["exploded"]}, "unknown value"),
    ({"message_re": "("}, "valid regex"),
    ({"util_pct_ge": {"any": "high"}}, "number"),
    ({"min_severity": "warning"}, "besides"),
    ({"any": [{"nope": 1}]}, "unknown condition 'nope'"),
    ({"any": [{"any": [{"status": ["done"]}]}]}, "unknown condition 'any'"),
    ({}, "always fire"),
])
def test_invalid_conditions(when, fragment):
    with pytest.raises(hints_mod.ConfigError, match="hint 't'.*" + fragment):
        one({"when": when})


@pytest.mark.parametrize("extra,fragment", [
    ({"severity": "error"}, "severity"),
    ({"title": ""}, "title"),
    ({"colour": "red"}, "unknown key"),
    ({"actions": [{"command": "x"}]}, "needs a text"),
    ({"actions": [{"text": "x", "cmd": "y"}]}, "unknown key"),
    ({"actions": "do it"}, "list of tables"),
])
def test_invalid_hint_fields(extra, fragment):
    with pytest.raises(hints_mod.ConfigError, match=fragment):
        one({"when": {"status": ["done"]}, **extra})


def test_missing_and_duplicate_id():
    with pytest.raises(hints_mod.ConfigError, match="missing id"):
        hints_mod.compile_hints({"hints": [{"title": "t"}]})
    spec = {"id": "a", "title": "t", "text": "x", "when": {"status": ["done"]}}
    with pytest.raises(hints_mod.ConfigError, match="duplicate id"):
        hints_mod.compile_hints({"hints": [spec, dict(spec)]})


# ---------------------------------------------------------------- user config merging
def load_with(tmp_path, monkeypatch, text):
    user = tmp_path / "flows.toml"
    user.write_text(textwrap.dedent(text))
    monkeypatch.setattr(config_mod, "config_dir", lambda: tmp_path / "no_config_dir")
    return config_mod.load_config(user)


def test_user_hint_is_added_and_builtins_stay(tmp_path, monkeypatch):
    cfg = load_with(tmp_path, monkeypatch, """
        [[hints]]
        id = "mine"
        title = "Mine"
        text = "x"
        when = {status = ["failed"]}
    """)
    assert [h.id for h in cfg.hints] == [h.id for h in BUILTIN] + ["mine"]


def test_user_hint_with_builtin_id_replaces_it_in_place(tmp_path, monkeypatch):
    cfg = load_with(tmp_path, monkeypatch, """
        [[hints]]
        id = "oom_jobs"
        title = "Custom OOM"
        text = "x"
        when = {status = ["failed"], failure_re = "memory"}
    """)
    assert [h.id for h in cfg.hints] == [h.id for h in BUILTIN]
    assert next(h for h in cfg.hints if h.id == "oom_jobs").title == "Custom OOM"


def test_disabled_ids_are_removed_and_unknown_fail(tmp_path, monkeypatch):
    cfg = load_with(tmp_path, monkeypatch, """
        [hints_config]
        disabled = ["oom_jobs", "latch_inferred"]
    """)
    assert {h.id for h in BUILTIN} - {h.id for h in cfg.hints} == {"oom_jobs", "latch_inferred"}
    with pytest.raises(hints_mod.ConfigError, match="unknown hint id.*oom_job$"):
        load_with(tmp_path, monkeypatch, '[hints_config]\ndisabled = ["oom_job"]\n')


def test_user_hint_with_unknown_condition_fails_at_load(tmp_path, monkeypatch):
    with pytest.raises(hints_mod.ConfigError, match="hint 'mine'"):
        load_with(tmp_path, monkeypatch, """
            [[hints]]
            id = "mine"
            title = "Mine"
            text = "x"
            when = {typo_key = 1}
        """)


def test_hints_as_single_table_is_rejected(tmp_path, monkeypatch):
    with pytest.raises(hints_mod.ConfigError, match="array of tables"):
        load_with(tmp_path, monkeypatch, '[hints]\nid = "x"\n')


# ---------------------------------------------------------------- conditions
def test_status_and_step_done():
    hints = one({"when": {"status": ["failed"], "step_done": "route_design"}})
    assert fired(hints, firmware([step("route_design")], status="failed")) == ["t"]
    assert fired(hints, firmware([step("route_design", "running")], status="failed")) == []
    assert fired(hints, firmware([step("route_design")], status="done")) == []


def test_alert_codes_evidence():
    alert = {"level": "warning", "code": "congestion", "message": "Congestion level 6", "node_id": "n"}
    out = hints_mod.evaluate(one({"when": {"alert_codes": ["congestion", "stalled"]}}), firmware(alerts=[alert]), DEFAULTS)
    assert out[0]["evidence"] == "alert congestion: Congestion level 6"
    assert not hints_mod.evaluate(one({"when": {"alert_codes": ["stalled"]}}), firmware(alerts=[alert]), DEFAULTS)


def test_message_ids_glob_severity_and_evidence():
    fw = firmware(messages=[msg("DRC DPIP-1", "Input pipelining", count=51), msg("DRC DPOP-4", "x", "warning", 3),
                            msg("Synth 8-327", "latch", "info")])
    out = hints_mod.evaluate(one({"when": {"message_ids": ["DRC DP?P-*"]}}), fw, DEFAULTS)
    assert out[0]["evidence"] == "message DRC DPIP-1 (51×): Input pipelining (also DRC DPOP-4)"
    only_critical = one({"when": {"message_ids": ["DRC DPIP-1"], "min_severity": "critical"}})
    assert not hints_mod.evaluate(only_critical, fw, DEFAULTS)
    assert not hints_mod.evaluate(one({"when": {"message_ids": ["Synth 8-327"]}}), fw, DEFAULTS)   # info is not a hint trigger


def test_message_re():
    fw = firmware(messages=[msg("Common 17-1", "Failed to get a license: Implementation", "error", 1)])
    out = hints_mod.evaluate(one({"when": {"message_re": "(?i)licen[cs]e"}}), fw, DEFAULTS)
    assert out[0]["evidence"].startswith("message Common 17-1 (1×): Failed to get a license")


def test_failure_re_on_reason_and_details():
    node = step("route_design", "failed")
    node.failure = {"reason": "Abnormal termination", "details": ["terminate called after std::bad_alloc"]}
    hints = one({"when": {"failure_re": "bad_alloc"}})
    out = hints_mod.evaluate(hints, firmware([node], status="failed"), DEFAULTS)
    assert out[0]["evidence"] == "Route Design failed: Abnormal termination"
    ok = step("route_design")
    ok.failure = node.failure
    assert not hints_mod.evaluate(hints, firmware([ok]), DEFAULTS)       # only failed/stopped steps count


def test_timing_conditions_and_carried_values():
    hints = one({"when": {"timing": {"final": True, "whs_lt": 0, "stage": "route_design"}}})
    out = hints_mod.evaluate(hints, firmware([timed("route_design", whs=-0.034)]), DEFAULTS)
    assert out[0]["evidence"] == "WHS -0.034 ns after Route Design (final)"
    assert not hints_mod.evaluate(hints, firmware([timed("route_design", whs=-0.034, final=False)]), DEFAULTS)
    assert not hints_mod.evaluate(hints, firmware([timed("place_design", whs=-0.034)]), DEFAULTS)
    assert not hints_mod.evaluate(hints, firmware([timed("route_design", whs=-0.034, carried={"whs": {"label": "x"}})]), DEFAULTS)
    both = one({"when": {"timing": {"wns_lt": 0, "whs_lt": 0}}})
    assert not hints_mod.evaluate(both, firmware([timed("route_design", wns=-0.1, whs=0.01)]), DEFAULTS)
    assert hints_mod.evaluate(both, firmware([timed("route_design", wns=-0.1, whs=-0.01)]), DEFAULTS)[0]["evidence"].startswith("WNS -0.100 ns, WHS -0.010 ns")


def test_worst_path_conditions():
    fw = firmware([timed("route_design", wns=-0.2, paths=[path(route=71, logic=29, levels=6), path("hold", -0.03, 40, 60)])])
    route = one({"when": {"timing": {"final": True, "wns_lt": 0}, "worst_path": {"type": "setup", "route_pct_ge": 60}}})
    assert hints_mod.evaluate(route, fw, DEFAULTS)[0]["evidence"] == (
        "WNS -0.200 ns after Route Design (final); worst setup path (slack -0.200 ns): route 71%, logic 29% of the data path delay"
        " (Route Design timing report)")
    assert not hints_mod.evaluate(one({"when": {"worst_path": {"type": "setup", "logic_pct_ge": 60}}}), fw, DEFAULTS)
    assert not hints_mod.evaluate(one({"when": {"worst_path": {"type": "setup", "levels_ge": 10}}}), fw, DEFAULTS)
    assert hints_mod.evaluate(one({"when": {"worst_path": {"type": "hold", "logic_pct_ge": 60}}}), fw, DEFAULTS)


def test_worst_path_fanout_uses_top_n_and_never_met_paths():
    paths = [path(slack=-0.3), path(slack=-0.2, fanout=420, net="u/enable")]
    fw = firmware([timed("route_design", wns=-0.3, paths=paths)])
    assert not hints_mod.evaluate(one({"when": {"worst_path": {"fanout_ge": 100}}}), fw, DEFAULTS)
    out = hints_mod.evaluate(one({"when": {"worst_path": {"fanout_ge": 100, "top": 2}}}), fw, DEFAULTS)
    assert out[0]["evidence"].startswith("net u/enable has fanout 420 on a worst setup path (slack -0.200 ns)")
    met = firmware([timed("route_design", paths=[path(slack=0.2, route=90, fanout=500)])])
    assert not hints_mod.evaluate(one({"when": {"worst_path": {"route_pct_ge": 60}}}), met, DEFAULTS)


def test_congestion_level():
    node = step("place_design")
    node.congestion = {"placer": {"north": {"global": 6, "long": 3, "short": 2}}, "max_level": 6, "level": "warn"}
    hints = one({"when": {"congestion_level_ge": 5}})
    out = hints_mod.evaluate(hints, firmware([node]), DEFAULTS)
    assert out[0]["evidence"] == "congestion level 6 during placement (north global) in Place Design"
    assert not hints_mod.evaluate(one({"when": {"congestion_level_ge": 7}}), firmware([node]), DEFAULTS)


def test_convergence_trend_needs_enough_iterations():
    node = step("route_design", "running")
    iters = lambda n: [{"final_overlaps": 1000 + i * 50} for i in range(n)]
    hints = one({"when": {"convergence_trend": ["stalled", "diverging"]}})
    node.convergence = {"iterations": iters(5), "trend": "diverging"}
    out = hints_mod.evaluate(hints, firmware([node], status="running"), DEFAULTS)
    assert out[0]["evidence"] == "router diverging in Route Design: overlaps 1,050 -> 1,100 -> 1,150 -> 1,200 (5 iterations)"
    node.convergence = {"iterations": iters(2), "trend": "diverging"}
    assert not hints_mod.evaluate(hints, firmware([node], status="running"), DEFAULTS)
    node.convergence = {"iterations": iters(5), "trend": "converging"}
    assert not hints_mod.evaluate(hints, firmware([node], status="running"), DEFAULTS)


def util(**pct):
    return {"label": "Utilization (routed)", "rows": [{"name": n, "pct": p} for n, p in pct.items()]}


def test_util_any_per_resource_and_ignored_resources():
    fw = firmware(utilization=util(LUT=40, DSP=93, IO=99))
    out = hints_mod.evaluate(one({"when": {"util_pct_ge": {"any": 90}}}), fw, DEFAULTS)
    assert out[0]["evidence"] == "utilization DSP 93% (Utilization (routed))"
    assert not hints_mod.evaluate(one({"when": {"util_pct_ge": {"any": 90}}}), firmware(utilization=util(LUT=40, IO=99)), DEFAULTS)
    assert hints_mod.evaluate(one({"when": {"util_pct_ge": {"IO": 95}}}), firmware(utilization=util(IO=99)), DEFAULTS)
    both = one({"when": {"util_pct_ge": {"DSP": 90, "LUT": 50}}})
    assert not hints_mod.evaluate(both, fw, DEFAULTS)


def test_any_group_is_or_and_and_with_when():
    hints = one({"when": {"status": ["done"], "any": [{"message_ids": ["A 1-1"]}, {"alert_codes": ["stalled"]}]}})
    assert fired(hints, firmware(messages=[msg("A 1-1")])) == ["t"]
    assert fired(hints, firmware(status="failed", messages=[msg("A 1-1")])) == []
    assert fired(hints, firmware()) == []


def test_step_anchor_and_doc_url_expansion():
    hints = one({"when": {"status": ["done"]}, "step": "route_design",
                 "actions": [{"text": "a", "command": "route_design", "doc_url": "route_design"},
                             {"text": "b", "doc_url": "https://example.org/x"}, {"text": "c"}]})
    out = hints_mod.evaluate(hints, firmware([step("route_design")]), DEFAULTS)[0]
    assert out["node_id"] == "impl_1/route_design"
    assert out["actions"][0]["doc_url"] == "https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/route_design"
    assert out["actions"][1]["doc_url"] == "https://example.org/x" and "command" not in out["actions"][2]
    assert hints_mod.evaluate(hints, firmware([step("place_design")]), DEFAULTS)[0]["node_id"] is None


def test_warnings_sort_before_info():
    specs = [{"id": "i", "title": "I", "text": "x", "when": {"status": ["done"]}},
             {"id": "w", "title": "W", "text": "x", "severity": "warning", "when": {"status": ["done"]}}]
    out = hints_mod.evaluate(hints_mod.compile_hints({"hints": specs}), firmware(), DEFAULTS)
    assert [h["id"] for h in out] == ["w", "i"]


# ---------------------------------------------------------------- built-in set
def test_healthy_build_has_no_hints():
    fw = firmware([timed("route_design", wns=0.2, whs=0.05, paths=[path("setup", 0.2, 80, 20)])],
                  messages=[msg("Synth 8-7080", "parallel synthesis", "warning", 4)], utilization=util(LUT=30, DSP=45))
    assert ids_for(fw) == []


def test_intermediate_timing_never_produces_timing_hints():
    fw = firmware([timed("place_design", wns=-0.5, whs=-0.3, final=False, paths=[path(route=90, fanout=500)])], status="running")
    assert ids_for(fw) == []


def test_hold_after_route():
    fw = firmware([timed("route_design", wns=0.1, whs=-0.034)])
    out = hints_mod.evaluate(BUILTIN, fw, DEFAULTS)
    assert [h["id"] for h in out] == ["hold_after_route"]
    assert out[0]["evidence"] == "WHS -0.034 ns after Route Design (final)"
    assert any(a.get("command") == "phys_opt_design -directive ExploreWithHoldFix" for a in out[0]["actions"])
    assert out[0]["node_id"] == "impl_1/route_design"


def test_setup_route_vs_logic_dominated():
    route = firmware([timed("route_design", wns=-0.2, paths=[path(route=75, logic=25, levels=4)])])
    assert ids_for(route) == ["setup_route_dominated"]
    logic = firmware([timed("route_design", wns=-0.2, paths=[path(route=30, logic=70, levels=7)])])
    assert ids_for(logic) == ["setup_logic_dominated"]
    deep = firmware([timed("route_design", wns=-0.2, paths=[path(route=45, logic=55, levels=12)])])
    assert ids_for(deep) == ["setup_logic_dominated"]
    mixed = firmware([timed("route_design", wns=-0.2, paths=[path(route=50, logic=50, levels=5)])])
    assert ids_for(mixed) == []


def test_high_fanout():
    fw = firmware([timed("route_design", wns=-0.2, paths=[path(fanout=420, net="u/en")])])
    out = hints_mod.evaluate(BUILTIN, fw, DEFAULTS)
    assert [h["id"] for h in out] == ["high_fanout_worst_path"]
    assert "net u/en has fanout 420" in out[0]["evidence"]


def test_congestion_and_router():
    place = step("place_design")
    place.congestion = {"placer": {"west": {"global": 5}}, "max_level": 5, "level": "warn"}
    assert ids_for(firmware([place], status="running")) == ["congestion_high"]
    route = step("route_design", "running")
    route.convergence = {"iterations": [{"final_overlaps": 100 * (i + 1)} for i in range(5)], "trend": "diverging"}
    assert ids_for(firmware([route], status="running")) == ["router_not_converging"]
    assert ids_for(firmware([route], status="done")) == []


def test_oom_and_license_failures():
    oom = step("route_design", "failed")
    oom.failure = {"reason": "Out of memory", "details": ["ERROR: [Common 17-1] Out of memory"]}
    assert ids_for(firmware([oom], status="failed")) == ["oom_jobs"]
    killed = step("route_design", "stopped")
    killed.failure = {"reason": "Killed (signal 9)", "details": []}
    assert ids_for(firmware([killed], status="stopped")) == ["oom_jobs"]
    lic = step("synth_design", "failed")
    lic.failure = {"reason": "License lost", "details": ["FlexNet Licensing error:-96,491"]}
    out = ids_for(firmware([lic], status="failed"))
    assert out == ["license_lost"]
    segv = step("route_design", "failed")
    segv.failure = {"reason": "Segmentation fault (signal 11)", "details": []}
    assert ids_for(firmware([segv], status="failed")) == []


def test_message_based_builtins():
    fw = firmware(messages=[msg("Synth 8-327", "inferring latch for variable 'q_reg'", "warning", 2),
                            msg("DRC DPIP-2", "Input pipelining", "warning", 51),
                            msg("Timing 38-316", "Clock period mismatch", "critical", 1)])
    # the DSP/BRAM pipeline hint is a timing-closure measure: silent while timing is met
    assert set(ids_for(fw)) == {"latch_inferred", "constraint_problem"}
    out = {h["id"]: h for h in hints_mod.evaluate(BUILTIN, fw, DEFAULTS)}
    assert out["latch_inferred"]["evidence"] == "message Synth 8-327 (2×): inferring latch for variable 'q_reg'"
    assert out["latch_inferred"]["severity"] == "warning"
    failing = firmware([timed("route_design", wns=-0.1, whs=0.01)], messages=[msg("DRC DPIP-2", "Input pipelining", "warning", 51)])
    out = {h["id"]: h for h in hints_mod.evaluate(BUILTIN, failing, DEFAULTS)}
    assert "dsp_pipeline_registers" in out and out["dsp_pipeline_registers"]["severity"] == "info"


def test_high_utilization_builtin_ignores_io():
    assert ids_for(firmware(utilization=util(DSP=91.5, IO=40))) == ["high_utilization"]
    assert ids_for(firmware(utilization=util(DSP=60, IO=99))) == []


def test_disabled_builtin_does_not_fire(tmp_path, monkeypatch):
    cfg = load_with(tmp_path, monkeypatch, '[hints_config]\ndisabled = ["latch_inferred"]\n')
    fw = firmware(messages=[msg("Synth 8-327", "latch")])
    assert hints_mod.evaluate(cfg.hints, fw, cfg) == []


def test_no_hint_text_invents_options():
    """Every Tcl option named in a built-in command is one documented in UG835 (guards against typos on edit)."""
    known = {"-directive", "-force_replication_on_nets", "-logic_level_distribution", "-congestion", "-retiming", "-jobs",
             "-delay_type", "-hierarchical", "-a", "-c"}
    for hint in BUILTIN:
        for action in hint.actions:
            for option in re.findall(r"\s(-[a-z_]+)", action.get("command", "")):
                assert option in known, (hint.id, option)


# ---------------------------------------------------------------- integration
def test_compact_path_carries_max_fanout():
    from vmon import timing_paths
    from tests.conftest import FIXTURES
    found = timing_paths.parse_file(str(FIXTURES / "paths" / "timing_paths_tables.rpt"))
    assert all("max_fanout" in timing_paths.compact(p) for p in found["paths"])
    setup = next(p for p in found["paths"] if p["slack"] == 42.694)
    assert (setup["max_fanout"], setup["fanout_net"]) == (1, setup["steps"][1]["name"])


def test_monitor_publishes_hints_in_the_state(tmp_path, cfg):
    import json
    from vmon.monitor import Monitor
    from tests.test_project import qick
    monitor = Monitor(cfg, recent_file=tmp_path / "cache" / "recent.json", rules_file=tmp_path / "rules.json")
    monitor.discovery.discover = lambda: []
    monitor.add_path(str(qick(tmp_path)))
    monitor.tick()
    state = json.loads(monitor.state_json())
    assert state["firmwares"] and all(isinstance(f["hints"], list) for f in state["firmwares"])
    monitor.cfg.hints = hints_mod.compile_hints({"hints": [
        {"id": "always", "title": "A", "text": "x", "when": {"status": ["done", "failed", "stopped", "running", "idle"]}}]})
    monitor.tick()
    assert [h["id"] for h in json.loads(monitor.state_json())["firmwares"][0]["hints"]] == ["always"]
