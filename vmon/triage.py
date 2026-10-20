"""Message triage: score aggregated log messages so the ones worth reading come first.

Rules, keywords and weights live in flows.toml ([messages]); user overrides in
~/.config/vmon/message_rules.json; the novelty baseline in ~/.cache/vmon/msgs/<fw_id>.json.
"""
import json
import os
import re
import threading
from pathlib import Path

PRIORITIES = ("critical", "high", "medium", "low", "mute")
SEV_ORDER = {"info": 0, "warning": 1, "critical": 2, "error": 3}


def default_rules_file():
    return Path.home() / ".config" / "vmon" / "message_rules.json"


class TriageConfig:
    def __init__(self, data):
        messages = data.get("messages", {})
        self.rules = []
        for spec in messages.get("rules", ()):
            text = spec.get("match_text")
            self.rules.append((re.compile(spec["match_id"]), re.compile(text, re.I) if text else None,
                               spec["priority"], spec.get("reason", ""), frozenset(spec.get("severity", ()))))
        self.keywords = [(re.compile(k["pattern"], re.I), k.get("bonus", 0), k.get("reason") or k["pattern"])
                         for k in messages.get("keywords", ())]
        scoring = messages.get("scoring", {})
        self.severity_base = scoring.get("severity_base", {})
        self.priority_bonus = scoring.get("priority_bonus", {})
        self.keyword_cap = scoring.get("keyword_cap", 30)
        self.rarity = scoring.get("rarity", {})
        self.novelty = scoring.get("novelty", {})

    def match_rule(self, msg_id, text, severity=None):
        for id_re, text_re, priority, reason, severities in self.rules:
            if severities and severity not in severities:
                continue
            if id_re.search(msg_id) and (text_re is None or text_re.search(text)):
                return priority, reason
        return None, None


class UserRules:
    """{"<id>": priority} persisted as JSON; the only file vmon writes outside ~/.cache/vmon."""

    def __init__(self, path=None):
        self.path = Path(path) if path else default_rules_file()
        self.lock = threading.Lock()
        self.version = 0
        self.rules = {}
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict):
                self.rules = {str(k): v for k, v in data.items() if v in PRIORITIES}
        except (OSError, ValueError):
            pass

    def set(self, msg_id, priority):
        """priority None removes the override. Raises ValueError on bad input."""
        if not isinstance(msg_id, str) or not msg_id.strip() or len(msg_id) > 200:
            raise ValueError("bad id")
        if priority is not None and priority not in PRIORITIES:
            raise ValueError("priority must be one of %s or null" % ", ".join(PRIORITIES))
        with self.lock:
            if priority is None:
                if self.rules.pop(msg_id, None) is None:
                    return
            else:
                self.rules[msg_id] = priority
            self.version += 1
            if not self.rules and not self.path.exists():
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self.rules, indent=1, sort_keys=True))
            os.replace(tmp, self.path)


class BaselineStore:
    """Previous-build message counts per firmware: {"current": {...}, "previous": {...}}."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.version = 0
        self._cache = {}

    def _load(self, fw_id):
        if fw_id not in self._cache:
            try:
                data = json.loads((self.dir / (fw_id + ".json")).read_text())
                if not isinstance(data, dict):
                    data = {}
            except (OSError, ValueError):
                data = {}
            self._cache[fw_id] = data
        return self._cache[fw_id]

    def baseline(self, fw_id, build):
        """Counts of the build before `build` (or the last finished one for a build in progress)."""
        data = self._load(fw_id)
        current, previous = data.get("current"), data.get("previous")
        if current and current.get("build") == build:
            return previous["counts"] if previous else None
        return current["counts"] if current else None

    def record(self, fw_id, build, counts):
        """Store a finished build; idempotent per build key. Returns True when something was written."""
        data = self._load(fw_id)
        current = data.get("current")
        if current and current.get("build") == build:
            data["current"] = {"build": build, "counts": counts}
        else:
            data = {"previous": current, "current": {"build": build, "counts": counts}}
            if data["previous"] is None:
                del data["previous"]
        self._cache[fw_id] = data
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / (fw_id + ".json")).write_text(json.dumps(data))
        except OSError:
            return False
        self.version += 1
        return True


def score_groups(raw_groups, tcfg, user_rules, baseline, docs=None):
    """raw_groups: [{"id","severity","count","text","first_line","last_line","log"}] -> TriageGroups."""
    out = []
    for raw in raw_groups:
        msg_id, text, count = raw["id"], raw["text"], raw["count"]
        reasons = []
        severity = raw["severity"]
        score = tcfg.severity_base.get(severity, 0)
        priority, why = tcfg.match_rule(msg_id, text, severity)
        user = user_rules.get(msg_id)
        effective = user or priority
        if user:
            reasons.append("user: marked %s" % user)
        elif priority:
            reasons.append("rule: %s" % why if why else "rule: %s" % priority)
        info = severity == "info"       # INFO lines only ever get demoted, never promoted
        if effective:
            bonus = tcfg.priority_bonus.get(effective, 0)
            score += min(bonus, 0) if info else bonus
        kw_total = 0
        for regex, bonus, kw_reason in tcfg.keywords:
            if regex.search(text):
                kw_total += bonus
                reasons.append("keyword: %s" % kw_reason)
        score += 0 if info else min(kw_total, tcfg.keyword_cap)
        rarity = tcfg.rarity
        if info:
            pass
        elif count == 1:
            score += rarity.get("once", 0)
            reasons.append("rare (1×)")
        elif count <= rarity.get("few_max", 5):
            score += rarity.get("few", 0)
            reasons.append("rare (%d×)" % count)
        elif count >= rarity.get("huge_min", 1000):
            score += rarity.get("huge_penalty", 0)
            reasons.append("very frequent (%d×)" % count)
        elif count >= rarity.get("many_min", 100):
            score += rarity.get("many_penalty", 0)
            reasons.append("frequent (%d×)" % count)
        is_new, delta = False, None
        if baseline is not None:
            before = baseline.get(msg_id)
            is_new = before is None
            delta = count - (before or 0)
            if is_new and not info:
                score += tcfg.novelty.get("new", 0)
                reasons.append("new since last build")
            elif delta > 0 and not info:
                score += tcfg.novelty.get("grew", 0)
                reasons.append("up %d since last build" % delta)
        out.append({"id": msg_id, "severity": severity, "count": count, "text": text,
                    "score": round(score, 1), "priority": priority, "user_priority": user,
                    "reasons": reasons, "new": is_new, "delta": delta, "nodes": [],
                    "first_line": raw["first_line"], "last_line": raw["last_line"],
                    "log": raw.get("log"), "muted": effective == "mute",
                    "doc_url": docs.message_url(msg_id) if docs and re.search(r"\w+ \d+-\d+", msg_id) else None})
    out.sort(key=lambda g: (-g["score"], -SEV_ORDER.get(g["severity"], 0), g["first_line"]))
    return out
