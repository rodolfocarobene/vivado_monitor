"""Crash / failure detection from log tails and hs_err files (read-only, patterns from flows.toml [failure])."""
import glob
import os
import re

_scan_cache = {}        # path -> ((size, mtime_ns), hits)
_ADDR = re.compile(r"\+0x[0-9a-f]+\)?\s*\[0x[0-9a-f]+\]|\[0x[0-9a-f]+\]")


def _read_tail(path, size, limit):
    with open(path, "rb") as fh:
        fh.seek(max(0, size - limit))
        return fh.read(), max(0, size - limit)


def _count_lines_before(path, offset):
    """Number of newlines before a byte offset (so tail lines get absolute line numbers)."""
    if offset <= 0:
        return 0
    total, left = 0, offset
    with open(path, "rb") as fh:
        while left > 0:
            chunk = fh.read(min(left, 1 << 20))
            if not chunk:
                break
            total += chunk.count(b"\n")
            left -= len(chunk)
    return total


def scan_log(path, cfg):
    """Pattern hits in the tail of a log: [(line_no, pattern_index, text)] in file order."""
    fc = cfg.failure
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (st.st_size, st.st_mtime_ns)
    cached = _scan_cache.get(path)
    if cached and cached[0] == key:
        return cached[1]
    hits = []
    try:
        data, offset = _read_tail(path, st.st_size, fc.tail_bytes)
        base = _count_lines_before(path, offset)
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").split("\n")
    if offset:
        lines = lines[1:]             # first line is probably cut
        base += 1
    for i, line in enumerate(lines):
        if not line:
            continue
        for index, pattern in enumerate(fc.patterns):
            match = pattern.regex.search(line)
            if match:
                hits.append((base + i + 1, index, line.strip()[:fc.max_line_chars], match))
                break
    hits = [(n, idx, text, m.groups()) for n, idx, text, m in hits]
    _scan_cache[path] = (key, hits)
    if len(_scan_cache) > 64:
        _scan_cache.pop(next(iter(_scan_cache)))
    return hits


def _reason(cfg, index, groups):
    pattern = cfg.failure.patterns[index]
    if pattern.signal and groups:
        name = cfg.failure.signals.get(groups[0])
        if name:
            return "%s (signal %s)" % (name, groups[0])
    reason = pattern.reason
    for i, group in enumerate(groups, 1):
        reason = reason.replace("{%d}" % i, group or "")
    return reason


def read_hs_err(path, cfg):
    """(title, top frame) from the head of an hs_err file, both possibly None."""
    fc = cfg.failure
    title = frame = None
    try:
        with open(path, "rb") as fh:
            head = [fh.readline().decode("utf-8", "replace").rstrip() for _ in range(fc.hs_err_head_lines)]
    except OSError:
        return None, None
    for line in head:
        if title is None and fc.hs_err_title_re:
            match = fc.hs_err_title_re.match(line)
            if match:
                title = match.group(1)
        if frame is None and line.startswith("/") and not (
                fc.hs_err_skip_frames and fc.hs_err_skip_frames.search(line)):
            frame = _ADDR.sub("", line).strip()[:fc.max_line_chars]
    return title, frame


def find_hs_err(hits_text, run_dir, since, cfg):
    """hs_err path named by a log line, else the newest one in run_dir not older than `since`."""
    fc = cfg.failure
    if fc.hs_err_path_re:
        for text in hits_text:
            match = fc.hs_err_path_re.search(text)
            if match and os.path.isfile(match.group(1)):
                return match.group(1)
    if run_dir and fc.hs_err_glob:
        best = None
        for path in glob.glob(os.path.join(str(run_dir), fc.hs_err_glob)):
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if (since is None or mtime >= since - 1) and (best is None or mtime > best[0]):
                best = (mtime, path)
        return best[1] if best else None
    return None


def detect(log_paths, cfg, run_dir=None, since=None, extra_text=()):
    """Failure dict (SPEC v5) from pattern hits in the given logs plus an hs_err file, or None.

    Hits from the log whose mtime is older than `since` are ignored (stale launch).
    """
    fc = cfg.failure
    best = None             # (pattern_index, line, log, groups)
    details, first_line, first_log = [], None, None
    texts = list(extra_text)
    for path in log_paths:
        if not path:
            continue
        try:
            if since is not None and os.stat(path).st_mtime < since - 1:
                continue
        except OSError:
            continue
        for line_no, index, text, groups in scan_log(path, cfg):
            texts.append(text)
            if text not in details and len(details) < fc.max_details:
                details.append(text)
            if best is None or index < best[0]:
                best = (index, line_no, path, groups)
            if first_line is None:
                first_line, first_log = line_no, path
    hs_err = find_hs_err(texts, run_dir, since, cfg) if (best or run_dir) else None
    if best is None and hs_err is None:
        return None
    reason = _reason(cfg, best[0], best[3]) if best else "Abnormal termination"
    if hs_err:
        title, frame = read_hs_err(hs_err, cfg)
        for extra in (title, frame and "crash frame: " + frame):
            if extra and extra not in details:
                details.append(extra)
    return {"reason": reason, "details": details,
            "line": best[1] if best else None, "log": best[2] if best else first_log,
            "hs_err": hs_err}


def from_errors(messages, lo, hi, log, limit=3):
    """Fallback failure: the first ERROR messages of a failed step ((line, severity, id, text) tuples)."""
    errors = [m for m in messages if lo <= m[0] <= hi and m[1] == 3]
    if not errors:
        return {"reason": "Error", "details": [], "line": None, "log": log, "hs_err": None}
    return {"reason": "Error", "details": [("[%s] %s" % (m[2], m[3]) if m[2] else m[3])[:240]
                                           for m in errors[:limit]],
            "line": errors[0][0], "log": log, "hs_err": None}
