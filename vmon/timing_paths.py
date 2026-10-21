"""Streaming parser for the path sections of timing_summary reports.

Reads the report line by line (reports can be several MB) and keeps only the worst
paths per type, so memory and time stay bounded. Only the header of each path block
(everything before the "Location / Delay type" table) is looked at.
"""
import re

MAX_BYTES = 128_000_000
_SLACK = re.compile(r"^Slack \((MET|VIOLATED)\)\s*:\s*(-?[\d.]+)ns")
_FIELD = re.compile(r"^\s{2}([A-Z][A-Za-z ]+?):\s+(.*?)\s*$")
_CLOCKED = re.compile(r"clocked by (\S+)")
_NS = re.compile(r"^(-?[\d.]+)ns")
_DATA = re.compile(r"^(-?[\d.]+)ns\s+\(logic\s+(-?[\d.]+)ns\s+\(([\d.]+)%\)\s+route\s+(-?[\d.]+)ns\s+\(([\d.]+)%\)")
_LEVELS = re.compile(r"^(\d+)\s*(?:\((.*)\))?")
_FROM = re.compile(r"^From Clock:\s+(\S.*?)\s*$")
_TO = re.compile(r"^\s+To Clock:\s+(\S.*?)\s*$")
_FLOAT_KEYS = ("slack", "requirement", "data_delay", "logic_delay", "route_delay", "logic_pct",
               "route_pct", "skew", "uncertainty")


def _num(text):
    match = _NS.match(text or "")
    return float(match.group(1)) if match else None


def _finish(block, section_type, from_clock, to_clock):
    """Block dict (raw strings) -> contract dict."""
    data = block.get("data") or ""
    split = _DATA.match(data)
    levels = _LEVELS.match(block.get("levels") or "")
    cells = {}
    if levels and levels.group(2):
        for item in levels.group(2).split():
            name, _, count = item.partition("=")
            if count.isdigit():
                cells[name] = int(count)
    path_type = block.get("path_type") or ""
    return {
        "type": section_type,
        "slack": block["slack"],
        "status": block["status"],
        "source": block.get("source"),
        "source_clock": block.get("source_clock"),
        "destination": block.get("destination"),
        "dest_clock": block.get("dest_clock"),
        "from_clock": from_clock,
        "to_clock": to_clock,
        "group": block.get("group"),
        "path_type": path_type.split(" (")[0] or None,
        "corner": path_type[path_type.find("(") + 1:path_type.rfind(")")] if "(" in path_type else None,
        "requirement": _num(block.get("requirement")),
        "data_delay": float(split.group(1)) if split else _num(data),
        "logic_delay": float(split.group(2)) if split else None,
        "logic_pct": float(split.group(3)) if split else None,
        "route_delay": float(split.group(4)) if split else None,
        "route_pct": float(split.group(5)) if split else None,
        "levels": int(levels.group(1)) if levels else None,
        "cells": cells,
        "skew": _num(block.get("skew")),
        "uncertainty": _num(block.get("uncertainty")),
    }


def parse_paths(lines, max_paths=200):
    """Iterate over report lines -> {"paths": [...], "counts": {...}} (worst first).

    max_paths is the total cap, split evenly between setup and hold. Slack-less
    (unconstrained, "Slack: inf") blocks are ignored.
    """
    per_type = max(1, max_paths // 2)
    kept = {"setup": [], "hold": []}
    counts = {"total": 0, "setup": 0, "hold": 0, "setup_failing": 0, "hold_failing": 0}
    failing_clocks = set()
    section = None            # "setup" | "hold"
    from_clock = to_clock = None
    block = None              # block currently collecting header fields
    pending_key = None        # "source"/"destination" waiting for its "(... clocked by X ...)" line

    def close():
        nonlocal block
        if block is None:
            return
        item = _finish(block, block["section"], block["from_clock"], block["to_clock"])
        kind = item["type"]
        counts["total"] += 1
        counts[kind] += 1
        if item["status"] == "VIOLATED":
            counts[kind + "_failing"] += 1
            failing_clocks.add(item["to_clock"] or item["dest_clock"] or "?")
        bucket = kept[kind]
        bucket.append(item)
        if len(bucket) > 4 * per_type:
            bucket.sort(key=lambda p: p["slack"])
            del bucket[per_type:]
        block = None

    for line in lines:
        first = line[:1]
        if first == " ":
            if block is not None and not block["done"]:
                if line.startswith("    Location"):
                    block["done"] = True
                    continue
                if pending_key and "clocked by" in line:
                    match = _CLOCKED.search(line)
                    block[pending_key + "_clock"] = match.group(1) if match else None
                    pending_key = None
                    continue
                match = _FIELD.match(line)
                if match:
                    key = match.group(1)
                    value = match.group(2)
                    if key == "Source":
                        block["source"], pending_key = value, "source"
                    elif key == "Destination":
                        block["destination"], pending_key = value, "dest"
                    elif key == "Path Group":
                        block["group"] = value
                    elif key == "Path Type":
                        block["path_type"] = value
                    elif key == "Requirement":
                        block["requirement"] = value
                    elif key == "Data Path Delay":
                        block["data"] = value
                    elif key == "Logic Levels":
                        block["levels"] = value
                    elif key == "Clock Path Skew":
                        block["skew"] = value
                    elif key == "Clock Uncertainty":
                        block["uncertainty"] = value
            elif first == " " and line.startswith("  To Clock:"):
                match = _TO.match(line)
                if match:
                    to_clock = match.group(1)
            continue
        if not first:
            continue
        if first == "S":
            match = _SLACK.match(line)
            if match and section:
                close()
                block = {"status": match.group(1), "slack": float(match.group(2)), "section": section,
                         "from_clock": from_clock, "to_clock": to_clock, "done": False}
                pending_key = None
            continue
        if first == "M":
            if line.startswith("Max Delay Paths"):
                close()
                section = "setup"
            elif line.startswith("Min Delay Paths"):
                close()
                section = "hold"
            continue
        if first == "F":
            match = _FROM.match(line)
            if match:
                close()
                from_clock = match.group(1)
                section = None
            continue
        if first == "P" and line.startswith("Pulse Width Checks"):
            close()
            section = None
    close()
    setup = sorted(kept["setup"], key=lambda p: p["slack"])[:per_type]
    hold = sorted(kept["hold"], key=lambda p: p["slack"])[:per_type]
    paths = sorted(setup + hold, key=lambda p: p["slack"])
    for index, path in enumerate(paths):
        path["id"] = index
    counts["worst_setup"] = setup[0]["slack"] if setup else None
    counts["worst_hold"] = hold[0]["slack"] if hold else None
    counts["failing"] = counts["setup_failing"] + counts["hold_failing"]
    counts["failing_clocks"] = len(failing_clocks)
    counts["clocks"] = sorted(failing_clocks)[:20]
    counts["shown"] = len(paths)
    counts["capped"] = counts["total"] > len(paths)
    return {"paths": paths, "counts": counts}


def parse_file(path, max_paths=200):
    """parse_paths over a report file, or None when unreadable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            def lines():
                read = 0
                for line in fh:
                    read += len(line)
                    if read > MAX_BYTES:
                        return
                    yield line.rstrip("\n")
            return parse_paths(lines(), max_paths)
    except OSError:
        return None


def compact(path):
    """Short form of a path for report summaries (state JSON): drops the verbose fields."""
    keep = ("id", "type", "slack", "status", "source", "destination", "source_clock", "dest_clock",
            "levels", "logic_pct", "route_pct", "skew")
    return {k: path[k] for k in keep}
