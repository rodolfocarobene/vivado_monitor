"""Recommended actions: rule-based hints from [[hints]] in flows.toml, evaluated on the Firmware model.

A hint fires when every condition of its `when` table holds (plus one of its `any` tables, if present).
Conditions only read what the model already carries: alerts, step nodes (timing, congestion, convergence,
failure), the compact worst paths of the latest timing report, utilization and the aggregated messages.
Nothing here touches the disk, so evaluating on every tick stays cheap.
"""
import fnmatch
import re
from dataclasses import dataclass, field

from . import congestion as congestion_mod

SEVERITIES = ("info", "warning")
MSG_SEVERITY = {"warning": 1, "critical": 2, "error": 3}
HINT_KEYS = {"id", "title", "severity", "text", "actions", "step", "when"}
ACTION_KEYS = {"text", "command", "doc_url"}
TIMING_KEYS = {"final", "stage", "wns_lt", "tns_lt", "whs_lt", "ths_lt"}
PATH_KEYS = {"type", "top", "route_pct_ge", "logic_pct_ge", "levels_ge", "fanout_ge"}
PATH_LIMITS = (("route_pct_ge", "route_pct"), ("logic_pct_ge", "logic_pct"), ("levels_ge", "levels"),
               ("fanout_ge", "max_fanout"))
TREND_VALUES = {"converging", "stalled", "diverging"}
STATUS_VALUES = {"idle", "queued", "running", "done", "failed", "stopped"}
DEFAULT_UTIL_RESOURCES = ("LUT", "FF", "BRAM", "URAM", "DSP")


class ConfigError(ValueError):
    pass


# ---------------------------------------------------------------- config validation
def _strings(value, what):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise ValueError("%s must be a non-empty list of strings" % what)
    return value


def _number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be a number" % what)
    return value


def _regex(value, what):
    try:
        return re.compile(value)
    except (re.error, TypeError) as exc:
        raise ValueError("%s is not a valid regex: %s" % (what, exc))


def _table(value, allowed, what):
    if not isinstance(value, dict) or not value:
        raise ValueError("%s must be a non-empty table" % what)
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("%s: unknown key(s) %s (known: %s)" % (what, ", ".join(unknown), ", ".join(sorted(allowed))))
    return value


def _enum(value, allowed, what):
    values = _strings(value, what)
    bad = [v for v in values if v not in allowed]
    if bad:
        raise ValueError("%s: unknown value(s) %s (known: %s)" % (what, ", ".join(bad), ", ".join(sorted(allowed))))
    return values


def _c_min_severity(value):
    if value not in MSG_SEVERITY:
        raise ValueError("min_severity must be one of %s" % ", ".join(MSG_SEVERITY))
    return MSG_SEVERITY[value]


def _c_timing(value):
    spec = _table(value, TIMING_KEYS, "timing")
    for key, item in spec.items():
        if key == "final":
            if not isinstance(item, bool):
                raise ValueError("timing.final must be true or false")
        elif key == "stage":
            _strings(item, "timing.stage")
        else:
            _number(item, "timing." + key)
    return spec


def _c_worst_path(value):
    spec = _table(value, PATH_KEYS, "worst_path")
    for key, item in spec.items():
        if key == "type":
            if item not in ("setup", "hold"):
                raise ValueError("worst_path.type must be \"setup\" or \"hold\"")
        elif key == "top":
            if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                raise ValueError("worst_path.top must be a positive integer")
        else:
            _number(item, "worst_path." + key)
    if not set(spec) & {k for k, _ in PATH_LIMITS}:
        raise ValueError("worst_path needs at least one of %s" % ", ".join(k for k, _ in PATH_LIMITS))
    return spec


def _c_util(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("util_pct_ge must be a non-empty table such as {any = 90} or {DSP = 85}")
    for key, item in value.items():
        _number(item, "util_pct_ge." + key)
    return value


# key -> validator returning the value kept for evaluation; the evaluators below use the same keys
CONDITIONS = {
    "alert_codes": lambda v: _strings(v, "alert_codes"),
    "message_ids": lambda v: _strings(v, "message_ids"),
    "message_re": lambda v: _regex(v, "message_re"),
    "min_severity": _c_min_severity,
    "failure_re": lambda v: _regex(v, "failure_re"),
    "status": lambda v: _enum(v, STATUS_VALUES, "status"),
    "timing": _c_timing,
    "worst_path": _c_worst_path,
    "congestion_level_ge": lambda v: _number(v, "congestion_level_ge"),
    "convergence_trend": lambda v: _enum(v, TREND_VALUES, "convergence_trend"),
    "util_pct_ge": _c_util,
    "step_done": lambda v: _strings(v, "step_done"),
}
MODIFIERS = {"min_severity"}        # tune another condition, not a condition by themselves


def _compile_when(spec, where):
    if not isinstance(spec, dict) or not spec:
        raise ValueError("%s must be a non-empty table" % where)
    out = {}
    for key, value in spec.items():
        if key not in CONDITIONS:
            raise ValueError("unknown condition '%s' in %s (known: %s)" % (key, where, ", ".join(sorted(CONDITIONS))))
        try:
            out[key] = CONDITIONS[key](value)
        except ValueError as exc:
            raise ValueError("%s: %s" % (where, exc))
    if not set(out) - MODIFIERS:
        raise ValueError("%s needs a condition besides %s" % (where, ", ".join(sorted(MODIFIERS))))
    return out


@dataclass
class Hint:
    id: str
    title: str
    severity: str
    text: str
    actions: list
    step: str | None
    when: dict
    any: list = field(default_factory=list)


def _compile_action(spec, where):
    if not isinstance(spec, dict) or not isinstance(spec.get("text"), str) or not spec["text"]:
        raise ValueError("%s needs a text" % where)
    unknown = sorted(set(spec) - ACTION_KEYS)
    if unknown:
        raise ValueError("%s: unknown key(s) %s (known: %s)" % (where, ", ".join(unknown), ", ".join(sorted(ACTION_KEYS))))
    for key in ("command", "doc_url"):
        if key in spec and (not isinstance(spec[key], str) or not spec[key]):
            raise ValueError("%s: %s must be a non-empty string" % (where, key))
    return dict(spec)


def _compile_one(spec, index):
    hint_id = spec.get("id") if isinstance(spec, dict) else None
    if not isinstance(hint_id, str) or not hint_id:
        raise ConfigError("hints[%d]: missing id" % index)
    try:
        unknown = sorted(set(spec) - HINT_KEYS)
        if unknown:
            raise ValueError("unknown key(s) %s (known: %s)" % (", ".join(unknown), ", ".join(sorted(HINT_KEYS))))
        for key in ("title", "text"):
            if not isinstance(spec.get(key), str) or not spec[key]:
                raise ValueError("missing %s" % key)
        if spec.get("severity", "info") not in SEVERITIES:
            raise ValueError("severity must be one of %s" % ", ".join(SEVERITIES))
        step = spec.get("step")
        if step is not None and (not isinstance(step, str) or not step):
            raise ValueError("step must be a non-empty string")
        actions = spec.get("actions", [])
        if not isinstance(actions, list):
            raise ValueError("actions must be a list of tables")
        actions = [_compile_action(a, "action %d" % (i + 1)) for i, a in enumerate(actions)]
        when = spec.get("when") or {}
        if not isinstance(when, dict):
            raise ValueError("when must be a table")
        when = dict(when)
        alternatives = when.pop("any", None)
        if alternatives is not None and (not isinstance(alternatives, list) or not alternatives):
            raise ValueError("when.any must be a non-empty list of condition tables")
        compiled_any = [_compile_when(a, "when.any[%d]" % i) for i, a in enumerate(alternatives or ())]
        compiled = _compile_when(when, "when") if when else {}
        if not compiled and not compiled_any:
            raise ValueError("when needs at least one condition (it would always fire)")
    except ValueError as exc:
        raise ConfigError("hint '%s': %s" % (hint_id, exc))
    return Hint(hint_id, spec["title"], spec.get("severity", "info"), spec["text"], actions, step, compiled, compiled_any)


def compile_hints(data):
    """[Hint] from the merged config (config.load_config already resolved ids and `disabled`)."""
    raw = data.get("hints", [])
    if not isinstance(raw, list):
        raise ConfigError("hints must be an array of tables ([[hints]])")
    hints, seen = [], set()
    for index, spec in enumerate(raw):
        hint = _compile_one(spec, index)
        if hint.id in seen:
            raise ConfigError("hint '%s': duplicate id" % hint.id)
        seen.add(hint.id)
        hints.append(hint)
    return hints


def merge_hint_lists(base, extra):
    """Arrays of tables do not deep-merge: a hint of `extra` replaces the one with the same id (in place), else is appended."""
    out = list(base)
    positions = {h.get("id"): i for i, h in enumerate(out) if isinstance(h, dict)}
    for spec in extra:
        key = spec.get("id") if isinstance(spec, dict) else None
        if key in positions:
            out[positions[key]] = spec
        else:
            out.append(spec)
            if key is not None:
                positions[key] = len(out) - 1
    return out


def apply_disabled(raw_hints, disabled):
    """Drop disabled ids; an id that matches no hint is an error (a typo must not silently keep a hint on)."""
    if not isinstance(disabled, list) or not all(isinstance(d, str) for d in disabled):
        raise ConfigError("hints_config.disabled must be a list of hint ids")
    known = {h.get("id") for h in raw_hints if isinstance(h, dict)}
    unknown = sorted(set(disabled) - known)
    if unknown:
        raise ConfigError("hints_config.disabled: unknown hint id(s) %s" % ", ".join(unknown))
    return [h for h in raw_hints if not (isinstance(h, dict) and h.get("id") in disabled)]


# ---------------------------------------------------------------- facts from the model
class Facts:
    """What conditions look at, gathered once per evaluation from the last flow of the firmware."""

    def __init__(self, fw, cfg, messages=None):
        self.fw, self.cfg = fw, cfg
        self.nodes = []            # step and run nodes, flow order (IP out-of-context runs excluded)
        self.steps = {}            # step id -> node ("synth_design" = the top-level synthesis run)
        if fw.flows:
            for stage in fw.flows[-1].stages:
                self._walk(stage, stage.id == "synth")
        self.messages = messages if messages is not None else list(fw.top_messages or ())
        self.timing_node = None    # set by the `timing` condition, read by `worst_path`

    def _walk(self, node, in_synth):
        if node.kind in ("step", "run") and "/ooc" not in node.id:
            self.nodes.append(node)
            if node.kind == "step":
                self.steps[node.id.rsplit("/", 1)[-1]] = node
            elif in_synth:
                self.steps.setdefault("synth_design", node)
        for child in node.children:
            if child.kind not in ("phase", "task"):
                self._walk(child, in_synth)


def _where(node):
    return "after %s" % node.label if node.status == "done" else "during %s" % node.label


# ---------------------------------------------------------------- evaluators: (value, facts, when) -> [evidence] | None
def _e_status(value, facts, when):
    return ["build %s" % facts.fw.status] if facts.fw.status in value else None


def _e_step_done(value, facts, when):
    nodes = [facts.steps.get(s) for s in value]
    if all(n is not None and n.status == "done" for n in nodes):
        return ["%s done" % ", ".join(n.label for n in nodes)]
    return None


def _e_timing(value, facts, when):
    stages = value.get("stage")
    stages = [stages] if isinstance(stages, str) else stages
    candidates = [n for step, n in facts.steps.items() if n.timing and n.timing.wns is not None
                  and n.status != "pending" and (not stages or step in stages)]
    if "final" in value:
        candidates = [n for n in candidates if n.timing.final == value["final"]]
    if not candidates:
        return None
    node = candidates[-1]
    timing, parts = node.timing, []
    for key, name in (("wns_lt", "WNS"), ("tns_lt", "TNS"), ("whs_lt", "WHS"), ("ths_lt", "THS")):
        if key not in value:
            continue
        number = getattr(timing, name.lower())
        if number is None or timing.carried.get(name.lower()) or not number < value[key]:
            return None             # stale (carried) values never trigger a hint
        parts.append("%s %.3f ns" % (name, number))
    facts.timing_node = node
    return ["%s %s%s" % (", ".join(parts) or "timing", _where(node), " (final)" if timing.final else " (not final)")]


def _paths_node(facts):
    """The node whose timing report `worst_path` reads: the one `timing` picked, else the latest with paths (final first)."""
    if facts.timing_node is not None:
        return facts.timing_node
    with_paths = [n for n in facts.steps.values() if n.timing and n.timing.paths]
    pool = [n for n in with_paths if n.timing.final] or with_paths
    return pool[-1] if pool else None


def _e_worst_path(value, facts, when):
    node = _paths_node(facts)
    if node is None:
        return None
    ptype = value.get("type")
    violated = sorted((p for p in node.timing.paths if p.get("status") == "VIOLATED" and (ptype is None or p.get("type") == ptype)),
                      key=lambda p: p["slack"])
    for path in violated[:value.get("top", 1)]:
        if any(key in value and (path.get(name) is None or path[name] < value[key]) for key, name in PATH_LIMITS):
            continue
        what = "worst %s path (slack %.3f ns)" % (path["type"], path["slack"])
        if "fanout_ge" in value:
            text = "net %s has fanout %d on a %s" % (path.get("fanout_net") or "?", path["max_fanout"], what)
        else:
            detail = []
            if "levels_ge" in value:
                detail.append("%d logic levels" % path["levels"])
            if "route_pct_ge" in value or "logic_pct_ge" in value:
                detail.append("route %.0f%%, logic %.0f%% of the data path delay" % (path.get("route_pct") or 0, path.get("logic_pct") or 0))
            text = "%s: %s" % (what, ", ".join(detail))
        return ["%s (%s timing report)" % (text, node.label)]
    return None


def _e_alert_codes(value, facts, when):
    hits = [a for a in facts.fw.alerts if a["code"] in value]
    return ["alert %s: %s" % (hits[0]["code"], hits[0]["message"])] if hits else None


def _e_failure_re(value, facts, when):
    for node in facts.nodes:
        failure = node.failure
        if node.status in ("failed", "stopped") and failure:
            text = " | ".join([failure.get("reason") or ""] + list(failure.get("details") or ()))
            if value.search(text):
                return ["%s failed: %s" % (node.label, failure.get("reason") or "error")]
    return None


def _groups(facts, when):
    floor = when.get("min_severity", 1)
    return [g for g in facts.messages if MSG_SEVERITY.get(g.get("severity"), 0) >= floor]


def _message_evidence(group):
    text = (group.get("text") or "")[:90]
    return "%s (%d×)%s" % (group.get("id") or "message", group.get("count", 1), ": " + text if text else "")


def _e_message_ids(value, facts, when):
    found = sorted((g for g in _groups(facts, when) if any(fnmatch.fnmatchcase(g.get("id") or "", p) for p in value)),
                   key=lambda g: -g.get("count", 1))
    if not found:
        return None
    extra = ", ".join(g["id"] for g in found[1:3])
    return ["message %s%s" % (_message_evidence(found[0]), " (also %s)" % extra if extra else "")]


def _e_message_re(value, facts, when):
    for group in _groups(facts, when):
        if value.search(group.get("text") or ""):
            return ["message %s" % _message_evidence(group)]
    return None


def _e_congestion(value, facts, when):
    best = None
    for node in facts.nodes:
        worst = congestion_mod.worst(node.congestion)
        if worst and worst[0] >= value and (best is None or worst[0] > best[0][0]):
            best = (worst, node)
    if best is None:
        return None
    (level, label, direction, slot), node = best
    return ["congestion level %d during %s (%s %s) in %s" % (level, label, direction, slot, node.label)]


def _e_convergence(value, facts, when):
    minimum = facts.cfg.convergence.alert_min_iterations
    for node in facts.nodes:
        conv = node.convergence
        if conv and conv.get("trend") in value and len(conv["iterations"]) >= minimum:
            finals = [it["final_overlaps"] for it in conv["iterations"] if it.get("final_overlaps") is not None]
            tail = " -> ".join("{:,}".format(v) for v in finals[-4:])
            return ["router %s in %s: overlaps %s (%d iterations)" % (conv["trend"], node.label, tail, len(conv["iterations"]))]
    return None


def _e_util(value, facts, when):
    util = facts.fw.utilization
    if not util or not util.get("rows"):
        return None
    rows = {r["name"]: r for r in util["rows"] if r.get("pct") is not None}
    resources = facts.cfg.data.get("hints_config", {}).get("util_any_resources") or DEFAULT_UTIL_RESOURCES
    hits = {}
    for key, limit in value.items():
        picked = [rows[n] for n in resources if n in rows] if key == "any" else [rows[key]] if key in rows else []
        over = [r for r in picked if r["pct"] >= limit]
        if not over:
            return None
        hits.update((r["name"], r["pct"]) for r in over)
    shown = ", ".join("%s %.0f%%" % (n, p) for n, p in sorted(hits.items(), key=lambda kv: -kv[1]))
    return ["utilization %s (%s)" % (shown, util.get("label") or "report")]


EVALUATORS = {
    "status": _e_status, "step_done": _e_step_done, "timing": _e_timing, "worst_path": _e_worst_path,
    "alert_codes": _e_alert_codes, "failure_re": _e_failure_re, "message_ids": _e_message_ids,
    "message_re": _e_message_re, "congestion_level_ge": _e_congestion, "convergence_trend": _e_convergence,
    "util_pct_ge": _e_util,
}
# `timing` runs before `worst_path`, which reads the report it picked
EVAL_ORDER = ("status", "step_done", "timing", "worst_path", "alert_codes", "failure_re", "message_ids",
              "message_re", "congestion_level_ge", "convergence_trend", "util_pct_ge")


def _check(when, facts):
    """Evidence list when every condition of the table holds, else None."""
    evidence = []
    for key in EVAL_ORDER:
        if key in when:
            found = EVALUATORS[key](when[key], facts, when)
            if found is None:
                return None
            evidence.extend(found)
    return evidence


def _fire(hint, facts):
    evidence = _check(hint.when, facts) if hint.when else []
    if evidence is None:
        return None
    if hint.any:
        for alternative in hint.any:
            more = _check(alternative, facts)
            if more is not None:
                return evidence + more
        return None
    return evidence


def _action(spec, cfg):
    out = dict(spec)
    url = out.get("doc_url")
    if url and "://" not in url:          # a bare command name is a UG835 page, like [docs]
        template = cfg.data.get("docs", {}).get("tcl_command")
        if template:
            out["doc_url"] = template.format(command=url)
        else:
            del out["doc_url"]
    return out


def evaluate(hints, fw, cfg, messages=None):
    """Firmware.hints: [{id, title, severity, text, evidence, actions, node_id}], warnings first."""
    if not hints:
        return []
    facts = Facts(fw, cfg, messages)
    out = []
    for hint in hints:
        facts.timing_node = None
        evidence = _fire(hint, facts)
        if evidence is None:
            continue
        node = facts.steps.get(hint.step) if hint.step else None
        out.append({"id": hint.id, "title": hint.title, "severity": hint.severity, "text": hint.text,
                    "evidence": "; ".join(dict.fromkeys(evidence)),
                    "actions": [_action(a, cfg) for a in hint.actions], "node_id": node.id if node else None})
    out.sort(key=lambda h: h["severity"] != "warning")
    return out
