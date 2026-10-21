"""Printable summary of one recorded build (a full history record) as GitHub Markdown or self-contained HTML.

The record is turned into neutral blocks once; `to_markdown` and `to_html` only differ in how they draw a block:
("title", text), ("lede", [(text, kind)]), ("h", text), ("kv", [(key, value, code)]), ("table", headers, rows, aligns),
("note", text). A cell is a plain string, or ("code", text) for ids and paths.
"""
import html
import re
import time
from datetime import datetime

from . import __version__
from .history import SEVERITY_RANK, UTIL_ROWS

OUTCOME = {"met": "Finished, timing met", "timing_not_met": "Finished, timing not met", "stopped": "Stopped",
           "done": "Finished"}
OUTCOME_KIND = {"met": "ok", "timing_not_met": "err", "failed": "err", "stopped": "warn", "done": "muted"}
MODES = {"project": "Project run", "resume": "Resume from checkpoint", "external": "Outside the project flow"}
SEV_LABEL = {"error": "Error", "critical": "Critical warning", "warning": "Warning"}
SEV_KIND = {"error": "err", "critical": "crit", "warning": "warn"}
TOP_MESSAGES = 15
TOP_CLOCKS = 10


def outcome(record):
    if record.get("result") != "failed":
        return OUTCOME.get(record.get("result"), OUTCOME["done"])
    f = record.get("failure") or {}
    why = ": ".join(x for x in (f.get("step"), f.get("reason")) if x)
    return "Failed: " + why if why else "Failed"


def fmt_duration(seconds):
    if seconds is None:
        return "-"
    s = int(round(seconds))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return "%dh %02dm" % (h, m) if h else "%dm %02ds" % (m, sec) if m else "%ds" % sec


def fmt_when(epoch):
    return datetime.fromtimestamp(epoch).astimezone().isoformat(sep=" ", timespec="minutes") if epoch else None


def _ns(value):
    return "-" if value is None else "%.3f" % value


def _count(n):
    return "{:,}".format(int(n))


def _pct(value):
    return "-" if value is None else "%.1f%%" % value


def _code(text):
    return ("code", str(text))


def _info_rows(r):
    strategies = [("Synthesis strategy", r.get("strategy_synth")), ("Implementation strategy", r.get("strategy_impl"))]
    rows = [("Project", r.get("project"), True), ("Part", r.get("part"), True), ("Board", r.get("board"), True),
            ("Vivado", r.get("vivado_version"), False), *((k, v, False) for k, v in strategies)]
    # The host (an IP or machine name from Vivado's markers) stays out on purpose: summaries are meant to be shared.
    for step, directive in (r.get("directives") or {}).items():
        rows.append(("Directive: %s" % step, directive, True))
    return [row for row in rows if row[1]]


def _timing_blocks(r):
    t = r.get("timing")
    if not t or all(t.get(k) is None for k in ("wns", "tns", "whs", "ths")):
        return []
    blocks = [("h", "Timing"),
              ("table", ["WNS (ns)", "TNS (ns)", "WHS (ns)", "THS (ns)"], [[_ns(t.get(k)) for k in ("wns", "tns", "whs", "ths")]], "rrrr")]
    if not t.get("final"):
        blocks.append(("note", "Not final: these numbers come from an earlier step, not from the routed design."))
    clocks = r.get("timing_clocks")
    if clocks:
        worst = sorted(clocks.items(), key=lambda kv: (kv[1].get("wns") is None, kv[1].get("wns") or 0, kv[0]))[:TOP_CLOCKS]
        blocks.append(("table", ["Clock", "WNS (ns)", "WHS (ns)"],
                       [[_code(n), _ns(v.get("wns")), _ns(v.get("whs"))] for n, v in worst], "lrr"))
        if len(clocks) > len(worst):
            blocks.append(("note", "Worst %d of %d clocks by WNS." % (len(worst), len(clocks))))
    return blocks


def _util_block(r):
    util = r.get("utilization")
    rows = [[k, _count(util[k]["used"]), _count(util[k]["available"]), _pct(util[k].get("pct"))]
            for k in UTIL_ROWS if util and k in util and util[k].get("used") is not None and util[k].get("available") is not None]
    return [("h", "Utilization"), ("table", ["Resource", "Used", "Available", "Used %"], rows, "lrrr")] if rows else []


def _steps_block(r):
    steps = r.get("steps")
    if not steps:
        return []
    total = r.get("duration_s") or sum(steps.values())
    rows = [[_code(s), fmt_duration(d), _pct(100.0 * d / total) if total else "-"] for s, d in steps.items()]
    return [("h", "Step durations"), ("table", ["Step", "Duration", "Share of build"], rows, "lrr")]


def top_messages(messages, limit=TOP_MESSAGES):
    """(shown, hidden): every error and critical warning, then warnings by count, at most `limit` rows (never fewer than the serious ones)."""
    items = [(i, m) for i, m in (messages or {}).items() if m.get("severity") in SEVERITY_RANK]
    items.sort(key=lambda im: (-SEVERITY_RANK[im[1]["severity"]], -im[1].get("count", 0), im[0]))
    serious = sum(1 for _, m in items if m["severity"] != "warning")
    keep = max(limit, serious)
    return items[:keep], len(items) - keep if len(items) > keep else 0


def _messages_blocks(r):
    counts, messages = r.get("counts"), r.get("messages")
    blocks = []
    if counts and len(counts) == 4:
        blocks.append(("table", ["Errors", "Critical warnings", "Warnings", "Info"], [[_count(c) for c in counts]], "rrrr"))
    shown, hidden = top_messages(messages)
    if shown:
        rows = [[_code(i), SEV_LABEL[m["severity"]], _count(m.get("count", 0)), m.get("text") or ""] for i, m in shown]
        blocks.append(("table", ["Id", "Severity", "Count", "Text"], rows, "llrl"))
        if hidden:
            blocks.append(("note", "%d more warning id%s not listed." % (hidden, "" if hidden == 1 else "s")))
    return [("h", "Messages"), *blocks] if blocks else []


def _attempts_block(r):
    attempts = r.get("attempts")
    if not attempts or len(attempts) < 2:
        return []
    rows = [[str(a.get("n")), MODES.get(a.get("mode"), a.get("mode") or "-"), (a.get("result") or "-").capitalize(), a.get("detail") or ""]
            for a in attempts]
    return [("h", "Attempts"), ("table", ["#", "Mode", "Result", "Detail"], rows, "llll")]


def _artifacts_block(r):
    rows = [[a.get("label") or a.get("kind") or "", a.get("step") or "", _code(a.get("path") or ""),
             "replaced by a later build" if a.get("current") is False else ""] for a in r.get("artifacts") or ()]
    return [("h", "Reports and bitstream"), ("table", ["Item", "Step", "Path", "Note"], rows, "lllL")] if rows else []


def blocks_of(r, generated_at=None):
    lede = [(x, k) for x, k in ((fmt_when(r.get("started_at")), None),
                                ("Duration " + fmt_duration(r["duration_s"]) if r.get("duration_s") is not None else None, None),
                                (outcome(r), OUTCOME_KIND.get(r.get("result"), "muted"))) if x]
    info = _info_rows(r)
    blocks = [("title", "%s build summary" % (r.get("firmware") or r.get("fw_id") or "Firmware")), ("lede", lede)]
    if info:
        blocks += [("h", "Build info"), ("kv", info)]
    blocks += [*_timing_blocks(r), *_util_block(r), *_steps_block(r), *_messages_blocks(r), *_attempts_block(r),
               *_artifacts_block(r)]
    stamp = time.strftime("%Y-%m-%d", time.localtime(generated_at)) if generated_at else time.strftime("%Y-%m-%d")
    blocks.append(("footer", "Generated by vmon %s on %s" % (__version__, stamp)))
    return blocks


# ---------------------------------------------------------------- Markdown
def _md_text(text):
    text = re.sub(r"[\\|`*<>]", lambda m: "\\" + m.group(), str(text).replace("\r", " ").replace("\n", " "))
    return re.sub(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])", r"\\_", text)


def _md_cell(cell):
    if isinstance(cell, tuple):
        text = cell[1].replace("\n", " ").replace("|", "\\|")
        fence = "``" if "`" in text else "`"
        return "%s%s%s" % (fence, text, fence) if text else ""
    return _md_text(cell)


def to_markdown(r, generated_at=None):
    out = []
    for block in blocks_of(r, generated_at):
        kind = block[0]
        if kind == "title":
            out.append("# " + _md_text(block[1]))
        elif kind == "lede":
            out.append(" · ".join("**%s**" % _md_text(t) if k else _md_text(t) for t, k in block[1]))
        elif kind == "h":
            out.append("## " + block[1])
        elif kind == "kv":
            out.append("\n".join("- **%s:** %s" % (k, _md_cell(_code(v)) if code else _md_text(v)) for k, v, code in block[1]))
        elif kind == "table":
            _, headers, rows, aligns = block
            sep = ["---:" if a == "r" else "---" for a in aligns]
            lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
            lines += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in rows]
            out.append("\n".join(lines))
        elif kind == "note":
            out.append("_%s_" % _md_text(block[1]))
        else:
            out.append("---\n\n_%s_" % _md_text(block[1]))
    return "\n\n".join(out) + "\n"


# ---------------------------------------------------------------- HTML
CSS = """
:root{--bg:#fff;--text:#18212f;--muted:#647186;--border:#d8dfea;--soft:#f6f8fb;--accent:#2d6cdf;--ok:#00783d;--err:#c5233f;--crit:#af4900;--warn:#8c6000;--mono:ui-monospace,"SF Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 24px 48px}
h1{font-size:24px;margin:0 0 6px;letter-spacing:-.2px}
h2{font-size:15px;margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--border);break-after:avoid}
.lede{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--muted);margin:0}
.badge{font-weight:700;padding:1px 10px;border-radius:99px;border:1px solid currentColor}
.ok{color:var(--ok)}.err{color:var(--err)}.crit{color:var(--crit)}.warn{color:var(--warn)}.muted{color:var(--muted)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 18px;margin:0}
dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);background:var(--soft)}
th,td{padding:6px 10px;border-bottom:1px solid var(--border);vertical-align:top}
tr{break-inside:avoid}
.r{text-align:right;font-variant-numeric:tabular-nums}
code{font-family:var(--mono);font-size:12px;overflow-wrap:anywhere}
.note{color:var(--muted);font-style:italic;margin:6px 0 0}
footer{margin-top:36px;padding-top:10px;border-top:1px solid var(--border);color:var(--muted);font-size:12px}
@media(max-width:600px){main{padding:20px 16px}}
@media print{main{max-width:none;padding:0}h2{margin-top:20px}a{color:inherit}}
"""


def _h(text):
    return html.escape(str(text), quote=True)


def _html_cell(cell, align):
    cls = ' class="r"' if align == "r" else ""
    inner = "<code>%s</code>" % _h(cell[1]) if isinstance(cell, tuple) else _h(cell)
    return "<td%s>%s</td>" % (cls, inner)


def to_html(r, generated_at=None):
    blocks, body = blocks_of(r, generated_at), []
    title = blocks[0][1]
    for block in blocks:
        kind = block[0]
        if kind == "title":
            body.append("<h1>%s</h1>" % _h(block[1]))
        elif kind == "lede":
            body.append('<p class="lede">%s</p>' % "".join(
                '<span class="badge %s">%s</span>' % (k, _h(t)) if k else "<span>%s</span>" % _h(t) for t, k in block[1]))
        elif kind == "h":
            body.append("<h2>%s</h2>" % _h(block[1]))
        elif kind == "kv":
            body.append("<dl>%s</dl>" % "".join("<dt>%s</dt><dd>%s</dd>" % (_h(k), "<code>%s</code>" % _h(v) if code else _h(v))
                                                for k, v, code in block[1]))
        elif kind == "table":
            _, headers, rows, aligns = block
            head = "".join('<th%s>%s</th>' % (' class="r"' if a == "r" else "", _h(t)) for t, a in zip(headers, aligns))
            trs = "".join("<tr>%s</tr>" % "".join(_html_cell(c, a) for c, a in zip(row, aligns)) for row in rows)
            body.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (head, trs))
        elif kind == "note":
            body.append('<p class="note">%s</p>' % _h(block[1]))
        else:
            body.append("<footer>%s</footer>" % _h(block[1]))
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title><style>%s</style></head>'
            "<body><main>\n%s\n</main></body></html>\n" % (_h(title), CSS, "\n".join(body)))


RENDERERS = {"md": (to_markdown, "text/markdown; charset=utf-8"), "html": (to_html, "text/html; charset=utf-8")}


def filename(record, fmt):
    """`<firmware>_<YYYY-MM-DD_HHMM>_summary.<fmt>`, safe for a Content-Disposition header."""
    started = record.get("started_at")
    stamp = time.strftime("%Y-%m-%d_%H%M", time.localtime(started)) if started else str(record.get("build") or "build")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", "%s_%s_summary" % (record.get("firmware") or "firmware", stamp)).strip("._")
    return "%s.%s" % (name, fmt)
