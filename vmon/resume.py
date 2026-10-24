"""Recognising a resume session (open_checkpoint in a non-project Vivado log) read-only."""
import os
import time

from . import paths
from .textio import decode

_cache = {}     # log path -> (size, result)


def scan_session(log_path, cwd, cfg):
    """{'checkpoint': abs path | None, 'started_at': float | None} from the head of a log."""
    rc = cfg.resume
    try:
        size = os.stat(log_path).st_size
    except OSError:
        return {"checkpoint": None, "started_at": None}
    hit = _cache.get(log_path)
    if hit and (hit[1]["checkpoint"] is not None or hit[0] == size):
        return hit[1]
    try:
        with open(log_path, "rb") as fh:
            text = decode(fh.read(rc.scan_bytes))
    except OSError:
        return {"checkpoint": None, "started_at": None}
    started_at, checkpoint, here = None, None, cwd
    for line in text.split("\n"):
        if started_at is None and rc.session_start_re:
            match = rc.session_start_re.search(line)
            if match:
                try:
                    started_at = time.mktime(time.strptime(match.group(1), cfg.wallclock_format))
                except ValueError:
                    pass
        if rc.cd_re:
            match = rc.cd_re.match(line)
            if match:
                target = rc.first_group(match)
                here = target if paths.is_abs(target) or not here else paths.join(here, target)
        if checkpoint is None and rc.checkpoint_re:
            match = rc.checkpoint_re.match(line)
            path = rc.first_group(match) if match else None
            # a sourced script is echoed with its variables unexpanded ("# open_checkpoint $dcp"); the
            # "Command: open_checkpoint <path>" line Vivado writes next has the real path
            if path and not any(c in path for c in "$["):
                if not paths.is_abs(path) and here:
                    path = paths.join(here, path)
                checkpoint = paths.normpath(path)
        if checkpoint and started_at is not None:
            break
    result = {"checkpoint": checkpoint, "started_at": started_at}
    _cache[log_path] = (size, result)
    return result
