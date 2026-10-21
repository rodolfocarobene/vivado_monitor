"""Infers which steps ran after a failure from files in the run dir (read-only)."""


def scan(entries, top, fail_time, cfg):
    """(proven, before): proven = {step: {"first", "last", "files"}} for artifacts newer than fail_time;
    before = step of the newest checkpoint written at or before the failure (what a resume started from)."""
    rc, ac = cfg.resume, cfg.artifacts
    proven, before = {}, None
    before_mtime = None
    prefix = top + "_"
    for name, entry in entries.items():
        if name.startswith(".") or not top:
            continue
        step = None
        is_checkpoint = name.endswith(".dcp") and name.startswith(prefix)
        if is_checkpoint:
            step = rc.step_for_checkpoint(name)
        elif name.endswith(".rpt") and name.startswith(prefix):
            tail = name[len(prefix):]
            step = next((r.step for r in cfg.report_types if r.step and r.regex.search(tail)), None)
        if step is None:
            step = ac.step_for_file(name, top)
        if step is None:
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime > fail_time + ac.tolerance_s:
            hit = proven.setdefault(step, {"first": mtime, "last": mtime, "files": []})
            hit["first"], hit["last"] = min(hit["first"], mtime), max(hit["last"], mtime)
            hit["files"].append(name)
        elif is_checkpoint and (before_mtime is None or mtime > before_mtime):
            before, before_mtime = step, mtime
    return proven, before
