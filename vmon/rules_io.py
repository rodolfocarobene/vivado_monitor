"""Sharing of message rules: the vmon-message-rules file format, strict validation and import diffs."""
import time

FORMAT = "vmon-message-rules"
VERSION = 1
MAX_RULES = 5000
MAX_NOTE = 200
MAX_ID = 200
MAX_BODY_BYTES = 2_000_000
MODES = ("merge", "replace")


class RulesFileError(ValueError):
    """The whole file is unusable (wrong format/version/shape, too many rules)."""


def valid_id(msg_id):
    return isinstance(msg_id, str) and bool(msg_id.strip()) and len(msg_id) <= MAX_ID


def export_doc(rules, exported_by=""):
    return {"format": FORMAT, "version": VERSION, "exported_at": int(time.time()),
            "exported_by": "".join(c for c in str(exported_by) if c.isprintable())[:100].strip(),
            "rules": {k: {"priority": v} for k, v in sorted(rules.items())}}


def export_filename():
    return "vmon_message_rules_%s.json" % time.strftime("%Y-%m-%d")


def _entry(msg_id, spec, priorities, legacy):
    """-> (priority, error). Legacy files map id -> priority string; the new format maps id -> {priority, note?}."""
    if not valid_id(msg_id):
        return None, "bad id (a non-empty string of at most %d characters)" % MAX_ID
    if legacy and isinstance(spec, str):
        spec = {"priority": spec}
    if not isinstance(spec, dict):
        return None, "entry must be an object with a priority"
    if spec.get("priority") not in priorities:
        return None, "priority must be one of %s" % ", ".join(priorities)
    note = spec.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
        return None, "note must be a string of at most %d characters" % MAX_NOTE
    return spec["priority"], None


def parse_file(data, priorities):
    """-> (rules {id: priority}, invalid [{id, error}]). Raises RulesFileError for a file that is not usable at all.
    Notes are validated but not stored: vmon keeps a priority per id only."""
    if not isinstance(data, dict):
        raise RulesFileError("the rules file must be a JSON object")
    legacy = "format" not in data
    if legacy:
        entries = data
    else:
        if data["format"] != FORMAT:
            raise RulesFileError("unknown format %r (expected %r)" % (str(data["format"])[:40], FORMAT))
        if isinstance(data.get("version"), bool) or data.get("version") != VERSION:
            raise RulesFileError("unsupported version %r (this vmon reads version %d)" % (str(data.get("version"))[:20], VERSION))
        entries = data.get("rules")
        if not isinstance(entries, dict):
            raise RulesFileError('"rules" must be an object')
        if not isinstance(data.get("exported_by", ""), str):
            raise RulesFileError('"exported_by" must be a string')
    if len(entries) > MAX_RULES:
        raise RulesFileError("too many rules (%d, at most %d)" % (len(entries), MAX_RULES))
    rules, invalid = {}, []
    for msg_id, spec in entries.items():
        priority, err = _entry(msg_id, spec, priorities, legacy)
        if err:
            invalid.append({"id": str(msg_id)[:MAX_ID], "error": err})
        else:
            rules[msg_id] = priority
    return rules, invalid


def plan(current, incoming, mode, keep_mine=False):
    """-> (resulting rules, summary). Merge: imported rules win on conflicts unless keep_mine. Replace: result is incoming."""
    if mode not in MODES:
        raise ValueError("mode must be merge or replace")
    summary = {"added": [], "changed": [], "removed": [], "unchanged": 0, "kept_mine": 0}
    result = {} if mode == "replace" else dict(current)
    for msg_id, priority in sorted(incoming.items()):
        mine = current.get(msg_id)
        if mine is None:
            summary["added"].append({"id": msg_id, "priority": priority})
        elif mine == priority:
            summary["unchanged"] += 1
        elif keep_mine and mode == "merge":
            summary["kept_mine"] += 1
            continue
        else:
            summary["changed"].append({"id": msg_id, "from": mine, "to": priority})
        result[msg_id] = priority
    if mode == "replace":
        summary["removed"] = [{"id": k, "priority": v} for k, v in sorted(current.items()) if k not in incoming]
    return result, summary
