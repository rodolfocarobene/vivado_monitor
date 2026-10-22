"""Terminal formatting shared by `vmon status` and `vmon --tui`: pure functions over the /api/state dict.

A rendered line is a list of (text, tone) segments, so the same layout can be painted with ANSI codes (status)
or curses attributes (tui). Tones follow the web UI: green met/done, red only for final failures, amber for
warnings, estimates and stale data, blue running, dim for the rest (DESIGN.md, "Never cry wolf").
"""
import os
import sys
import time

ANSI = {"green": "32", "red": "31", "amber": "33", "blue": "94", "dim": "2", "bold": "1"}
STATUS_LABEL = {"pending": "Pending", "queued": "Queued", "running": "Running", "done": "Done", "failed": "Failed",
                "skipped": "Skipped", "stopped": "Stopped", "idle": "Idle"}
STATUS_TONE = {"running": "blue", "done": "green", "failed": "red", "stopped": "amber"}
MARKER = {"done": "✓", "running": "●", "failed": "✗", "queued": "◌", "stopped": "■",
          "skipped": "-", "pending": "○"}
ELLIPSIS = "…"
HEADERS = ("NAME", "STATUS", "STEP", "PROG", "ELAPSED", "ETA", "WNS/WHS", "E/CW/W", "AL")
STEP_COL = 2
DROP_ORDER = (8, 7, 5, 3)          # columns hidden first on a narrow terminal: AL, E/CW/W, ETA, PROG
NAME_MAX, STEP_MIN, MAX_DETAIL = 28, 8, 3


# ------------------------------------------------------------------ color
def color_enabled(stream=None, no_color_flag=False, env=None):
    """ANSI only on a TTY, unless --no-color, NO_COLOR (any non-empty value) or TERM=dumb say otherwise."""
    stream, env = stream or sys.stdout, os.environ if env is None else env
    if no_color_flag or env.get("NO_COLOR") or env.get("TERM") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def enable_vt():
    """Turn on ANSI processing in a Windows console; True when escapes will be interpreted."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode))
                    and kernel.SetConsoleMode(handle, mode.value | 0x0004))      # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError, ValueError):
        return False


def paint(text, tone, color):
    return "\x1b[%sm%s\x1b[0m" % (ANSI[tone], text) if color and tone in ANSI and text else text


def to_text(line, color=False):
    return "".join(paint(text, tone, color) for text, tone in line)


def clip(text, width):
    return text if len(text) <= width else (text[:max(width - 1, 0)] + ELLIPSIS if width > 0 else "")


def clip_line(line, width):
    out = []
    for text, tone in line:
        if width <= 0:
            break
        out.append((clip(text, width), tone))
        width -= len(text)
    return out


# ------------------------------------------------------------------ values
def fmt_dur(seconds):
    if seconds is None:
        return "-"
    s = max(0, round(seconds))
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm %02ds" % (s // 60, s % 60)
    return "%dh %02dm" % (s // 3600, s // 60 % 60)


def fmt_clock(t):
    return "-" if t is None else time.strftime("%H:%M", time.localtime(t))


def fmt_ns(value):
    return "-" if value is None else "%+.3f" % value


def stale_of(fw, state):
    """The offline remote this firmware belongs to, else None."""
    host = fw.get("host")
    return next((r for r in state.get("remotes") or () if host and r.get("name") == host and not r.get("online")), None)


def is_timing_fail(fw):
    t = fw.get("timing") or {}
    return fw.get("status") == "done" and bool(t.get("final")) and t.get("met") is False


def outcome(fw, stale=None):
    """(key, label, tone) with the web UI's words; stale data is never red."""
    if is_timing_fail(fw):
        key, label, tone = "done-fail", "Finished, timing not met", "red"
    else:
        key = fw.get("status") or "idle"
        label, tone = STATUS_LABEL.get(key, key.capitalize()), STATUS_TONE.get(key, "dim")
    if stale:
        return key, label + " · stale", "amber"
    return key, label, tone


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("children") or ())


def stages(fw):
    return [s for flow in fw.get("flows") or () for s in flow.get("stages") or ()]


def failure_text(fw):
    """'Route Design: Segmentation fault (signal 11)' from the deepest failed node, else None."""
    failed = [n for n in walk(stages(fw)) if n.get("status") == "failed"]
    if not failed:
        return None
    node = failed[-1]
    reason = (node.get("failure") or {}).get("reason")
    return "%s: %s" % (node.get("label"), reason) if reason else node.get("label")


def step_text(fw, stale):
    key = fw.get("status")
    if stale:
        return "unreachable" + (" · last update %s" % fmt_clock(stale["last_ok"]) if stale.get("last_ok") else "")
    if key == "running":
        text = ((fw.get("current") or {}).get("label") or "running").replace("›", ">")
    elif key == "failed":
        text = failure_text(fw) or "-"
    elif is_timing_fail(fw):
        text = (fw["timing"].get("stage") or "").replace("·", "-") or "-"
    else:
        text = "-"
    n = (fw.get("attempt") or {}).get("n", 1)
    return "#%d %s" % (n, text) if n > 1 else text


def progress_text(fw):
    pe = fw.get("progress_estimate")
    if fw.get("status") == "done":
        return "100%"
    return "-" if pe is None else "~%d%%" % round(pe * 100)


def eta_text(fw, stale):
    e = fw.get("eta") or {}
    if fw.get("status") != "running" or stale or e.get("expected_end") is None:
        return "-"
    band = " (%s-%s)" % (fmt_clock(e["low_end"]), fmt_clock(e["high_end"])) \
        if e.get("low_end") is not None and e.get("high_end") is not None else ""
    return "~%s%s" % (fmt_clock(e["expected_end"]), band)


def timing_cell(fw):
    """('~' + 'wns/whs', tone): '~' marks a non-final estimate; red only when the final result failed."""
    t = fw.get("timing")
    if not t or (t.get("wns") is None and t.get("whs") is None):
        return "-", "dim"
    text = "%s/%s" % (fmt_ns(t.get("wns")), fmt_ns(t.get("whs")))
    if not t.get("final"):
        bad = any(v is not None and v < 0 for v in (t.get("wns"), t.get("whs")))
        return "~" + text, "amber" if bad else "dim"
    return text, "green" if t.get("met") else "red" if t.get("met") is False else "dim"


def counts_cell(fw):
    c = fw.get("counts") or {}
    e, cw, w = c.get("error", 0), c.get("critical", 0), c.get("warning", 0)
    final_bad = fw.get("status") == "failed" or is_timing_fail(fw)
    return "%d/%d/%d" % (e, cw, w), ("red" if final_bad else "amber") if e else "amber" if cw or w else "dim"


def elapsed_cell(fw, stale, now):
    if fw.get("status") == "running" and fw.get("started_at") and not stale:
        return fmt_dur(now - fw["started_at"])
    return fmt_dur(fw.get("elapsed_s"))


def name_text(fw):
    return "%s@%s" % (fw.get("name"), fw["host"]) if fw.get("host") else fw.get("name") or "?"


def row_cells(fw, state, now):
    """[(text, tone)] for HEADERS, in order."""
    stale = stale_of(fw, state)
    _, label, tone = outcome(fw, stale)
    timing, timing_tone = timing_cell(fw)
    counts, counts_tone = counts_cell(fw)
    n_alerts = len(fw.get("alerts") or ())
    return [(name_text(fw), "bold"), (label, tone), (step_text(fw, stale), "dim" if fw.get("status") != "running" else "blue"),
            (progress_text(fw), "dim"), (elapsed_cell(fw, stale, now), "dim"), (eta_text(fw, stale), "amber"),
            (timing, timing_tone), (counts, counts_tone), (str(n_alerts) if n_alerts else "-", "amber" if n_alerts else "dim")]


def detail_lines(fw, limit=MAX_DETAIL):
    """Alert texts first, then the first hint title; at most `limit` lines."""
    alerts = [a for a in fw.get("alerts") or () if a.get("message")]
    lines = [("! " + a["message"], "red" if a.get("level") == "error" else "amber") for a in alerts[:limit]]
    hints = fw.get("hints") or ()
    if hints and len(lines) < limit:
        lines.append(("> hint: " + hints[0].get("title", ""), "blue"))
    elif len(alerts) > limit:
        lines[-1] = ("! +%d more alerts" % (len(alerts) - limit + 1), "amber")
    return lines


# ------------------------------------------------------------------ table
def column_widths(rows, width, columns):
    """Widths of the kept columns; the STEP column takes what is left (>= STEP_MIN)."""
    widths = {i: max(len(HEADERS[i]), *(len(r[i][0]) for r in rows)) for i in columns}
    widths[0] = min(widths[0], NAME_MAX)
    fixed = sum(w for i, w in widths.items() if i != STEP_COL) + 2 * (len(columns) - 1)
    widths[STEP_COL] = max(STEP_MIN, min(widths[STEP_COL], width - fixed))
    return widths


def table_lines(state, width, now=None, indent=0, detail=True, selected=None, expanded=None):
    """Lines (lists of segments) for the firmware table. `expanded` = fw ids to show detail for (None: all with
    alerts/hints when `detail`); `selected` = fw id drawn with a '>' marker (tui)."""
    now = time.time() if now is None else now
    fws = state.get("firmwares") or []
    rows = [row_cells(fw, state, now) for fw in fws]
    if not rows:
        return []
    columns = list(range(len(HEADERS)))
    avail = max(width - indent, 20)
    while True:
        widths = column_widths(rows, avail, columns)
        if sum(widths.values()) + 2 * (len(columns) - 1) <= avail or not any(c in columns for c in DROP_ORDER):
            break
        columns.remove(next(c for c in DROP_ORDER if c in columns))
    pad = " " * indent
    out = [clip_line([(pad + ("  " if selected is not None else "") + "  ".join(HEADERS[i].ljust(widths[i]) for i in columns).rstrip(), "dim")], width)]
    for fw, row in zip(fws, rows):
        marker = ("> " if fw.get("id") == selected else "  ") if selected is not None else ""
        line = [(pad + marker, "bold")]
        for n, i in enumerate(columns):
            text, tone = row[i]
            line.append((clip(text, widths[i]).ljust(widths[i] if n < len(columns) - 1 else 0), tone))
            if n < len(columns) - 1:
                line.append(("  ", "dim"))
        out.append(clip_line(line, width))
        if detail and (expanded is None or fw.get("id") in expanded):
            for text, tone in detail_lines(fw):
                out.append(clip_line([(pad + "    " + text, tone)], width))
    return out


def summary_line(state):
    fws = state.get("firmwares") or []
    keys = {}
    for fw in fws:
        key = outcome(fw)[0]
        keys[key] = keys.get(key, 0) + 1
    parts = ", ".join("%d %s" % (n, STATUS_LABEL.get(k, k).lower() if k != "done-fail" else "timing not met")
                      for k, n in sorted(keys.items()))
    return "%d firmware%s%s" % (len(fws), "" if len(fws) == 1 else "s", ": " + parts if parts else "")


def remote_lines(state):
    return [("remote %s unreachable%s" % (r["name"], " (%s)" % r["error"] if r.get("error") else ""), "amber")
            for r in state.get("remotes") or () if not r.get("online")]


def status_lines(state, width, now=None):
    out = table_lines(state, width, now)
    out.append([(summary_line(state), "dim")])
    out += [[line] for line in remote_lines(state)]
    return [clip_line(line, width) for line in out]


# ------------------------------------------------------------------ machine output and exit code
def exit_code(state):
    """0 nothing failed; 1 a firmware failed or finished with final timing not met; 3 nothing to show."""
    fws = state.get("firmwares") or []
    if not fws:
        return 3
    return 1 if any(fw.get("status") == "failed" or is_timing_fail(fw) for fw in fws) else 0


def json_state(state):
    """Stable subset of the firmwares for scripts."""
    out = []
    for fw in state.get("firmwares") or []:
        stale = stale_of(fw, state)
        t = fw.get("timing") or {}
        out.append({
            "id": fw.get("id"), "name": fw.get("name"), "host": fw.get("host"), "kind": fw.get("kind"),
            "path": fw.get("path"), "status": fw.get("status"), "outcome": outcome(fw, None)[0],
            "stale": bool(stale), "current": (fw.get("current") or {}).get("label"),
            "failure": failure_text(fw) if fw.get("status") == "failed" else None,
            "progress_estimate": fw.get("progress_estimate"), "elapsed_s": fw.get("elapsed_s"),
            "eta": fw.get("eta"), "attempt": (fw.get("attempt") or {}).get("n", 1),
            "timing": {k: t.get(k) for k in ("wns", "tns", "whs", "ths", "final", "met", "stage")} if t else None,
            "counts": fw.get("counts"),
            "alerts": [{"level": a.get("level"), "code": a.get("code"), "message": a.get("message")}
                       for a in fw.get("alerts") or ()],
            "hints": [{"title": h.get("title"), "severity": h.get("severity")} for h in fw.get("hints") or ()]})
    return {"generated_at": state.get("generated_at"), "exit_code": exit_code(state), "firmwares": out,
            "remotes": [{k: r.get(k) for k in ("name", "online", "last_ok", "error")}
                        for r in state.get("remotes") or ()]}
