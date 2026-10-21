"""Parser for the "Location / Delay type" table of one timing path (report_timing_summary).

Fed line by line (the caller streams the report once). The table has three sections split by
dashed lines: source clock path, DATA PATH, destination clock path + check + required/arrival/slack.
A long "Delay type" wraps its numbers onto the next line, so a row without numbers stays pending.
"""
import re

MAX_STEPS = 200        # data-path elements kept per path
MAX_CLOCK_STEPS = 40   # elements kept per clock path (clock paths are short; the cap is a safety net)
_NUM = r"(-?\d+\.\d+)"
_ONLY_NUMS = re.compile(rf"^{_NUM}\s+{_NUM}(?:\s+([rf]))?(?:\s+(\S.*))?$")
_WITH_NUMS = re.compile(rf"^(\S.*?)\s+{_NUM}\s+{_NUM}(?:\s+([rf]))?(?:\s+(\S.*))?$")
_NO_NUMS = re.compile(r"^(\S.*?)\s+([rf])\s+(\S.*)$")
_EDGE = re.compile(r"^\(clock (.+) (rise|fall) edge\)$")
_NET = re.compile(r"^net \(fo=(\d+)(?:, ([^)]*))?\)$")
_CELL = re.compile(r"^(\S+)(?:\s+\((\S+)\))?$")
_SUMMARY = re.compile(rf"^(required time|arrival time|slack)\s+{_NUM}")
_LABELS = ("clock pessimism", "clock uncertainty", "clock network delay", "input delay", "output delay",
           "clock source latency", "ideal clock network latency", "max delay", "min delay")


def _is_check(row):
    """Setup/hold/recovery/removal check row of the destination register."""
    return bool(re.search(r"\((?:Setup|Hold|Recov|Remov)", row["dt"], re.I))


def pins_of(arc, name):
    """(from_pin, to_pin) of a cell arc such as Prop_B5LUT_SLICEL_I2_O; falls back to the pin ending the name."""
    tokens = (arc or "").split("_")
    if len(tokens) >= 3:
        return tokens[-2], tokens[-1]
    return None, (name.rsplit("/", 1)[-1] if name else None)


class PathTable:
    def __init__(self):
        self.pending = None
        self.segments = [[]]          # classified rows between dashed lines
        self.summary = {}
        self.truncated = False

    # ------------------------------------------------------------ feeding
    def feed(self, line):
        text = line.strip()
        if not text:
            return
        if text.startswith("---"):
            self.pending = None
            if self.segments[-1]:
                self.segments.append([])
            return
        found = _SUMMARY.match(text)
        if found:
            self.summary[found.group(1).split()[0]] = float(found.group(2))
            return
        self._row(line, text)

    def _row(self, line, text):
        loc = ""
        if line.startswith("    ") and line[4:5] not in ("", " "):
            if line[24:25].strip() == "":          # fixed location column: a long one is followed by a single space
                loc, text = line[4:25].strip(), line[25:].strip()
            else:
                parts = re.split(r"\s{2,}", line.strip(), maxsplit=1)
                loc, text = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        pending, self.pending = self.pending, None
        if pending is not None and not pending["dt"] and not loc:
            loc = pending["loc"]              # a long location sits alone on its line
        match = _ONLY_NUMS.match(text)
        if match:
            row = pending if pending is not None and pending["dt"] else {"loc": loc, "dt": "port"}
            row.update(incr=float(match.group(1)), at=float(match.group(2)), edge=match.group(3), name=match.group(4))
            return self._store(row)
        match = _WITH_NUMS.match(text)
        if match:
            return self._store({"loc": loc, "dt": match.group(1), "incr": float(match.group(2)), "at": float(match.group(3)),
                                "edge": match.group(4), "name": match.group(5)})
        match = _NO_NUMS.match(text)
        if match:
            return self._store({"loc": loc, "dt": match.group(1), "incr": None, "at": None, "edge": match.group(2),
                                "name": match.group(3), "pin": True})
        self.pending = {"loc": loc, "dt": text}

    def _store(self, row):
        if len(self.segments[-1]) >= MAX_STEPS:
            self.truncated = True
        else:
            self.segments[-1].append(row)

    # ------------------------------------------------------------ result
    @staticmethod
    def _element(row, full):
        dt = row["dt"]
        net = _NET.match(dt)
        if net:
            out = {"kind": "net", "fanout": int(net.group(1)), "routing": (net.group(2) or "").split(",")[0].strip() or None,
                   "incr": row["incr"], "at": row["at"]}
            if full:
                out["name"] = row["name"]
            return out
        cell = _CELL.match(dt)
        site, kind_cell, arc = row["loc"] or None, (cell.group(1) if cell else dt), (cell.group(2) if cell else None)
        if row.get("pin"):
            out = {"kind": "endpoint", "site": site, "cell": kind_cell, "pin": (row["name"] or "").rsplit("/", 1)[-1],
                   "edge": row["edge"], "incr": None, "at": None}
        else:
            out = {"kind": "cell", "site": site, "cell": kind_cell, "incr": row["incr"], "at": row["at"]}
            if full:
                out["arc"] = arc
                out["from_pin"], out["to_pin"] = pins_of(arc, row["name"])
                out["edge"] = row["edge"]
        if full:
            out["name"] = row["name"]
        return out

    def _clock_part(self, rows):
        """{clock, edge, at, path} of a clock-path section; `at` = arrival at the clock pin (the row before it)."""
        out = {"clock": None, "edge": None, "at": None, "path": []}
        for row in rows:
            if row.get("pin") or row["dt"].startswith(_LABELS[:2]) or _is_check(row):
                break
            edge = _EDGE.match(row["dt"])
            if edge:
                out["clock"], out["edge"] = edge.group(1), edge.group(2)
            elif not row["dt"].startswith(_LABELS):
                out["path"].append(self._element(row, False))
            if row.get("at") is not None and not row["dt"].startswith(_LABELS[:2]):
                out["at"] = row["at"]
        del out["path"][MAX_CLOCK_STEPS:]
        return out

    def result(self):
        """(launch, steps, capture) or None when the table is not a usable path."""
        segments = [seg for seg in self.segments if seg]
        if len(segments) < 2:
            return None
        # datapath-only exceptions (set_max_delay -datapath_only) have no clock-path sections
        source, data, dest = segments[:3] if len(segments) >= 3 else ([], segments[0], segments[1])
        launch = self._clock_part(source)
        steps = [self._element(row, True) for row in data
                 if row["dt"] not in ("", "port") and not row["dt"].startswith(_LABELS + ("(clock",))]
        capture = self._clock_part(dest)
        capture.update(pessimism=None, uncertainty=None, setup_or_hold=None, constraint=None)
        for row in dest:
            dt = row["dt"]
            if dt.startswith("clock pessimism"):
                capture["pessimism"] = row["incr"]
            elif dt.startswith("clock uncertainty"):
                capture["uncertainty"] = row["incr"]
            elif dt.startswith(("max delay", "min delay")):    # set_max_delay -datapath_only: no clock path
                capture["constraint"] = {"kind": dt, "value": row["incr"]}
            elif _is_check(row):
                element = self._element(row, True)
                capture["setup_or_hold"] = {"arc": element["arc"], "cell": element["cell"], "incr": row["incr"]}
        capture.update(required=self.summary.get("required"), arrival=self.summary.get("arrival"),
                       slack=self.summary.get("slack"))
        return launch, steps, capture
