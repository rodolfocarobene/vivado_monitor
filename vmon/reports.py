"""Report parsers: a small registry keyed by name (see [reports.types] in flows.toml).

Each parser takes (text, config) and returns (summary_dict, alerts) where alerts is a
list of {"level", "code", "message"} dicts (node_id is added by the caller).
Reports are re-parsed only when (mtime, size) changes.
"""
import os
import re

HEAD_BYTES = 3_000_000          # tables of interest are near the top of big reports
_NUM = re.compile(r"^<?-?\d+(\.\d+)?$")
PARSERS = {}


def register(name):
    def deco(func):
        PARSERS[name] = func
        return func
    return deco


def to_float(text):
    text = (text or "").strip()
    if text.startswith("<"):
        text = text[1:]
    try:
        return float(text)
    except ValueError:
        return None


def to_int(text):
    value = to_float(text)
    return None if value is None else int(value)


def table_rows(text):
    """Yield (header, rows) for each ASCII '+---+' table; cells are stripped strings."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].startswith("+-") and i + 2 < len(lines) and lines[i + 1].startswith("|"):
            header = [c.strip() for c in lines[i + 1].strip().strip("|").split("|")]
            j = i + 2
            if lines[j].startswith("+-"):
                j += 1
            rows = []
            while j < len(lines) and lines[j].startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            yield header, rows
            i = j
        else:
            i += 1


@register("generic")
def parse_generic(text, cfg):
    return {}, []


@register("utilization")
def parse_utilization(text, cfg):
    found = {}
    for header, rows in table_rows(text):
        if "Used" not in header or "Available" not in header:
            continue
        used_i, avail_i = header.index("Used"), header.index("Available")
        pct_i = next((i for i, h in enumerate(header) if h.startswith("Util")), None)
        for row in rows:
            label = row[0].strip()
            for short, regex in cfg.utilization_map:
                if short in found or not regex.search(label):
                    continue
                used, avail = to_float(row[used_i]), to_float(row[avail_i])
                pct = to_float(row[pct_i]) if pct_i is not None else None
                if pct is None and used is not None and avail:
                    pct = round(100.0 * used / avail, 2)
                if used is not None and avail:
                    found[short] = {"name": short, "label": label, "used": used,
                                    "available": avail, "pct": pct}
    resources = [found[k] for k, _ in cfg.utilization_map if k in found]
    limit = cfg.alerts.get("utilization_pct", 90)
    alerts = [{"level": "warning", "code": "utilization",
               "message": "%s utilization %.1f%% (limit %s%%)" % (r["name"], r["pct"], limit)}
              for r in resources if r["pct"] is not None and r["pct"] > limit]
    return {"rows": resources}, alerts


@register("drc")
def parse_drc(text, cfg):
    severity_key = {"error": "error", "critical warning": "critical", "warning": "warning",
                    "advisory": "info", "info": "info"}
    counts = {"error": 0, "critical": 0, "warning": 0, "info": 0}
    rules = []
    for header, rows in table_rows(text):
        if header[:2] != ["Rule", "Severity"] or "Violations" not in header:
            continue
        for row in rows:
            key = severity_key.get(row[1].lower(), "info")
            count = to_int(row[header.index("Violations")]) or 0
            counts[key] += count
            rules.append({"id": row[0], "severity": key, "message": row[2], "count": count})
        break
    rank = {"error": 0, "critical": 1, "warning": 2, "info": 3}
    rules.sort(key=lambda r: (rank[r["severity"]], -r["count"]))
    summary = {"counts": counts, "rules": rules[:10], "rule_count": len(rules)}
    alerts = []
    if counts["error"]:
        alerts.append({"level": "error", "code": "drc", "message": "%d error violation(s)" % counts["error"]})
    if counts["critical"]:
        alerts.append({"level": "warning", "code": "drc",
                       "message": "%d critical warning violation(s)" % counts["critical"]})
    return summary, alerts


@register("route_status")
def parse_route_status(text, cfg):
    values = {}
    for match in re.finditer(r"# of ([^.\n]+?)\.* :\s+(\d+)", text):
        values[match.group(1).strip()] = int(match.group(2))
    routable = values.get("routable nets")
    fully = values.get("fully routed nets")
    unrouted = next((v for k, v in values.items() if "unrouted" in k), None)
    if unrouted is None and routable is not None and fully is not None:
        unrouted = routable - fully
    errors = values.get("nets with routing errors", 0)
    summary = {"routable": routable, "fully_routed": fully, "unrouted": unrouted,
               "routing_errors": errors}
    for key, value in values.items():
        summary.setdefault(key.replace(" ", "_"), value)
    alerts = []
    if unrouted:
        alerts.append({"level": "error", "code": "unrouted", "message": "%d unrouted net(s)" % unrouted})
    if errors:
        alerts.append({"level": "error", "code": "unrouted", "message": "%d net(s) with routing errors" % errors})
    return summary, alerts


@register("power")
def parse_power(text, cfg):
    wanted = {"Total On-Chip Power (W)": "total_w", "Dynamic (W)": "dynamic_w",
              "Device Static (W)": "static_w", "Junction Temperature (C)": "junction_c",
              "Confidence Level": "confidence"}
    out = {}
    for match in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", text, re.M):
        key = wanted.get(match.group(1))
        if key and key not in out:
            out[key] = match.group(2) if key == "confidence" else to_float(match.group(2))
    return out, []


@register("control_sets")
def parse_control_sets(text, cfg):
    match = re.search(r"Total control sets\s*\|\s*(\d+)", text)
    return ({"control_sets": int(match.group(1))} if match else {}), []


@register("clock_utilization")
def parse_clock_utilization(text, cfg):
    out = {}
    for header, rows in table_rows(text):
        if header[:2] == ["Type", "Used"]:
            for row in rows:
                out[row[0]] = "%s / %s" % (row[1], row[2] if len(row) > 2 else "?")
            break
    return out, []


def parse_timing_text(text, cfg):
    """Design Timing Summary row + intra-clock table. Returns a summary dict or None."""
    pos = text.find("| Design Timing Summary")
    if pos < 0:
        return None
    lines = text[pos:].split("\n")
    result = None
    for i, line in enumerate(lines[:30]):
        if line.strip().startswith("WNS(ns)"):
            names = re.split(r"\s{2,}", line.strip())
            values = lines[i + 2].split() if i + 2 < len(lines) else []
            if len(values) >= len(names):
                result = {}
                for name, value in zip(names, values):
                    field = cfg.timing_columns.get(name)
                    if field:
                        result[field] = to_int(value) if field.endswith(("_fail", "_total")) else to_float(value)
            break
    if result is None:
        return None
    clocks = []
    periods = {}
    spos = text.find("| Clock Summary")
    if spos >= 0:
        block = text[spos:].split("\n")
        start = next((i for i, l in enumerate(block[:12]) if l.startswith("Clock ") and "Period" in l), None)
        if start is not None:
            for row in block[start + 2:start + 202]:
                parts = row.split()
                if not parts:
                    break
                if len(parts) >= 4 and _NUM.match(parts[-2]):
                    periods[parts[0]] = to_float(parts[-2])
    cpos = text.find("| Intra Clock Table")
    if cpos >= 0:
        block = text[cpos:].split("\n")
        start = next((i for i, l in enumerate(block) if l.startswith("Clock ") and "WNS(ns)" in l), None)
        if start is not None:
            for row in block[start + 2:start + 2 + 200]:
                if not row.strip():
                    break
                parts = row.split()
                if len(parts) >= 5 and _NUM.match(parts[1]):
                    clocks.append({"name": parts[0], "period": periods.get(parts[0]),
                                   "wns": to_float(parts[1]), "tns": to_float(parts[2]),
                                   "tns_fail": to_int(parts[3]),
                                   "whs": to_float(parts[5]) if len(parts) > 6 else None,
                                   "ths": to_float(parts[6]) if len(parts) > 6 else None})
    clocks.sort(key=lambda c: (c["wns"] is None, c["wns"] or 0))
    result["clocks"] = clocks[:30]
    return result


@register("timing")
def parse_timing(text, cfg):
    return (parse_timing_text(text, cfg) or {}), []


class ReportCache:
    def __init__(self, cfg):
        self.cfg = cfg
        self._cache = {}            # path -> ((mtime, size), (summary, alerts))

    def parse(self, path, parser_name):
        try:
            st = os.stat(path)
        except OSError:
            return None
        sig = (st.st_mtime, st.st_size)
        hit = self._cache.get(path)
        if hit and hit[0] == sig:
            return hit[1]
        try:
            with open(path, "rb") as fh:
                text = fh.read(HEAD_BYTES).decode("utf-8", "replace")
        except OSError:
            return None
        try:
            result = PARSERS.get(parser_name, parse_generic)(text, self.cfg)
        except Exception as exc:        # a malformed report must never take the monitor down
            result = ({"parse_error": str(exc)}, [])
        self._cache[path] = (sig, result)
        return result

    def timing(self, path):
        result = self.parse(path, "timing")
        return result[0] if result and result[0] else None
