"""Streaming parser: log lines -> node tree, messages, timing history.

All Vivado-specific patterns come from the Config (flows.toml). The parser keeps
state, so feed() can be called repeatedly with only the newly appended lines.
"""
import re
import time

SEVERITIES = ("info", "warning", "critical", "error")   # index order used in counts
SEV_INDEX = {name: i for i, name in enumerate(SEVERITIES)}
_SKIP = object()      # marker: the next standalone "Time (s)" line belongs to nothing
_SLUG = re.compile(r"[^a-z0-9]+")


def hms_to_seconds(text):
    try:
        total = 0.0
        for part in text.split(":"):
            total = total * 60 + float(part)
        return total
    except ValueError:
        return None


def slug(text):
    return _SLUG.sub("-", text.lower()).strip("-") or "x"


def parse_number(text):
    if text is None or text.upper() == "N/A":
        return None
    try:
        return float(text.rstrip("."))
    except ValueError:
        return None


class ParseNode:
    __slots__ = ("key", "label", "kind", "cmd", "number", "depth", "status", "line_start",
                 "line_end", "own", "children", "elapsed_s", "peak_mem", "started_at",
                 "ended_at", "history", "summary", "key_counts", "completed_line", "cum_start",
                 "saved_cum", "iters", "iter_ok", "iter_entry", "congestion")

    def __init__(self, kind, label, key):
        self.kind = kind
        self.label = label
        self.key = key
        self.cmd = None
        self.number = None
        self.depth = 0
        self.status = "running"
        self.line_start = None
        self.line_end = None
        self.own = [0, 0, 0, 0]
        self.children = []
        self.elapsed_s = None
        self.peak_mem = None
        self.started_at = None
        self.ended_at = None
        self.history = []
        self.summary = None
        self.key_counts = {}
        self.completed_line = None
        self.cum_start = 0.0
        self.saved_cum = 0.0
        self.iters = []            # steps: router iterations (see LogParser._on_overlaps)
        self.iter_ok = False       # phases: this phase counts as a convergence iteration
        self.iter_entry = None
        self.congestion = {}       # steps: raw congestion tables (see LogParser._on_congestion_row)

    def rolled_counts(self):
        total = list(self.own)
        for child in self.children:
            for i, value in enumerate(child.rolled_counts()):
                total[i] += value
        return total


class LogParser:
    def __init__(self, config, catalogs=None):
        self.cfg = config
        self.catalogs = catalogs
        self.stages = None             # {command: [(name, regex)]} for plain-line stages
        self.last_cum = 0.0            # last cumulative elapsed reading (resets per step/task)
        self.root = ParseNode("root", "log", "root")
        self.root.line_start = 1
        self.stack = [self.root]
        self.cur_step = None
        self.line_no = 0
        self.messages = []             # (line, severity_index, id, text), in line order
        self.agg = {}                  # id (or text[:60]) -> [severity, count, first_text, first_line, last_line]
        self.lines_by_key = {}         # same key -> [line numbers]
        self.msg_count = 0             # bumps on every message: cache key for derived views
        self.version = None
        self.wall = None               # last wall-clock timestamp seen in the log
        self.live = False              # True once the initial catch-up is done
        self.pending_time = None
        self._prev_pending = None
        self.exited = False
        self._cong_open = None         # (kind, step) while an estimated-congestion table is being read
        self._cong_dir = None          # direction of the last "Direction: X" line (final report)

    # ------------------------------------------------------------------ feeding
    def feed(self, lines):
        rules_for = self.cfg.rules_for
        for line in lines:
            self.line_no += 1
            if not line:
                continue
            self._prev_pending = self.pending_time
            self.pending_time = None
            if self.version is None and self.line_no < 40 and "Vivado v" in line:
                match = self.cfg.version_re.search(line)
                if match:
                    self.version = match.group(1)
                    if self.catalogs is not None:
                        self.stages = self.catalogs.stage_matchers(self.version)
            if self.stages and self.cur_step is not None and self.cur_step.completed_line is None:
                self._check_stage(line)
            for rule in rules_for(line[0]):
                if rule.contains is not None and rule.contains not in line:
                    continue
                if not rule.matches_prefix(line):
                    continue
                match = rule.regex.match(line)
                if match is None:
                    continue
                getattr(self, "_on_" + rule.action)(match, line)
                if rule.stop:
                    break

    def mark_live(self):
        self.live = True

    # ------------------------------------------------------------------ helpers
    def _now(self):
        return self.wall if self.wall is not None else (time.time() if self.live else None)

    def _new_node(self, kind, label, key_base, parent=None):
        parent = parent or self.stack[-1]
        count = parent.key_counts.get(key_base, 0) + 1
        parent.key_counts[key_base] = count
        node = ParseNode(kind, label, key_base if count == 1 else "%s~%d" % (key_base, count))
        node.line_start = self.line_no
        node.started_at = self._now()
        parent.children.append(node)
        return node

    def _close(self, node, line_end, status=None):
        if node.status == "running":
            node.status = status or "done"
        if node.line_end is None or node.kind in ("phase", "task", "command"):
            node.line_end = line_end
        node.ended_at = self._now() if node.ended_at is None else node.ended_at

    def _truncate(self, size, line_end, status=None):
        while len(self.stack) > size:
            self._close(self.stack.pop(), line_end, status)

    def _find(self, kinds, predicate):
        for index in range(len(self.stack) - 1, 0, -1):
            node = self.stack[index]
            if node.kind in kinds and predicate(node):
                return index
        return None

    def _check_stage(self, line):
        for name, regex in self.stages.get(self.cur_step.cmd, ()):
            if regex.match(line):
                top = self.stack[-1]
                if top.kind == "phase" and top.number == "stage":
                    self._close(self.stack.pop(), self.line_no - 1)
                node = self._new_node("phase", name, "g-" + slug(name))
                node.number = "stage"
                self.stack.append(node)
                return

    def _apply_time(self, node, line):
        """Time (s) readings are cumulative since the step/task start: phases get differences."""
        match = self.cfg.time_re.search(line)
        if not match or node is None:
            return
        elapsed = hms_to_seconds(match.group(2))
        if elapsed is not None:
            if node.kind == "phase":
                node.elapsed_s = max(0.0, elapsed - node.cum_start)
                self.last_cum = elapsed
            elif node.kind == "task":
                node.elapsed_s = elapsed
                self.last_cum = node.saved_cum
            else:
                node.elapsed_s = elapsed
        peak = parse_number(match.group(3))
        if peak is not None:
            node.peak_mem = peak
            step = self.cur_step
            if step is not None and (step.peak_mem is None or peak > step.peak_mem):
                step.peak_mem = peak

    # ------------------------------------------------------------------ actions
    def _on_wallclock(self, match, line):
        try:
            self.wall = time.mktime(time.strptime(match.group(1), self.cfg.wallclock_format))
        except ValueError:
            pass

    def _on_command(self, match, line):
        name = match.group(1)
        if name in self.cfg.step_commands:
            first = self.cur_step is None
            if self.cur_step is not None and self.cur_step.line_end is None:
                self.cur_step.line_end = self.line_no - 1
            self._truncate(1, self.line_no - 1)
            node = self._new_node("step", name, name, self.root)
            node.cmd = name
            if first:
                node.line_start = 1          # preamble lines belong to the first step
                node.own = list(self.root.own)
                self.root.own = [0, 0, 0, 0]
            self.cur_step = node
            self.last_cum = 0.0
            self._cong_open = self._cong_dir = None
        else:
            parent = self.cur_step or self.root
            self._truncate(self.stack.index(parent) + 1, self.line_no - 1)
            node = self._new_node("command", name, "c-" + name, parent)
            node.cmd = name
        self.stack.append(node)

    def _on_completed(self, match, line):
        name = match.group(1)
        index = self._find(("step", "command"), lambda n: n.cmd == name)
        if index is None:
            return
        node = self.stack[index]
        if node.kind == "step":
            self._truncate(index + 1, self.line_no)
            if node.status == "running":
                node.status = "done"          # line_end stays open: trailing lines belong to the step
            node.completed_line = self.line_no
        else:
            self._truncate(index, self.line_no)
            self.stack.append(node)
            self._close(self.stack.pop(), self.line_no)
        self.pending_time = node

    def _on_command_failed(self, match, line):
        name = match.group(1) if match.lastindex else None
        index = self._find(("step", "command"), lambda n: name is None or n.cmd == name)
        if index is None:
            return
        node = self.stack[index]
        self._truncate(index + 1, self.line_no, "failed")
        node.status = "failed"
        node.line_end = self.line_no if node.kind == "command" else node.line_end
        node.completed_line = self.line_no
        if node.kind == "command":
            self.stack.pop()

    def _on_message(self, match, line):
        severity = SEV_INDEX[self.cfg.severity[match.group(1)]]
        message_id, text = match.group(2), match.group(3)
        key = message_id or text[:60]
        entry = self.agg.get(key)
        if entry is None:
            self.agg[key] = [severity, 1, text, self.line_no, self.line_no]
            self.lines_by_key[key] = [self.line_no]
        else:
            entry[0] = max(entry[0], severity)
            entry[1] += 1
            entry[4] = self.line_no
            self.lines_by_key[key].append(self.line_no)
        self.msg_count += 1
        if len(self.messages) < self.cfg.max_messages:
            self.messages.append((self.line_no, severity, message_id, text))
        self.stack[-1].own[severity] += 1
        if "Timing" in text:
            self._check_timing(text)

    def _check_timing(self, text):
        for pattern in self.cfg.timing_patterns:
            if pattern.contains is not None and pattern.contains not in text:
                continue
            match = pattern.regex.search(text)
            if match is None:
                continue
            entry = {"t": self._now(), "line": self.line_no, "label": pattern.label,
                     "wns": None, "tns": None, "whs": None, "ths": None}
            for field, value in zip(pattern.fields, match.groups()):
                entry[field] = parse_number(value)
            target = self.cur_step or self.root
            if len(target.history) < 2000:
                target.history.append(entry)
            if pattern.label == "Intermediate":
                self._iteration_timing(entry)
            return

    def _on_phase(self, match, line):
        number, name, checksum = match.group(1), match.group(2), match.group(3)
        if checksum:
            index = self._find(("phase",), lambda n: n.number == number and n.label == name)
            if index is None:
                self.pending_time = _SKIP
                return
            node = self.stack[index]
            self._truncate(index + 1, self.line_no)
            self.stack.pop()
            self._close(node, self.line_no)
            self.pending_time = node
            return
        depth = number.count(".") + 1
        while self.stack[-1].kind == "phase" and self.stack[-1].depth >= depth:
            self._close(self.stack.pop(), self.line_no - 1)
        node = self._new_node("phase", name, "p" + number)
        node.number, node.depth = number, depth
        node.iter_ok = self.cur_step is not None and self.cfg.convergence.is_iteration(name)
        node.cum_start = self.last_cum
        self.stack.append(node)

    # ---- router convergence: overlaps per iteration + the timing summary printed after them
    def _open_iteration(self):
        """Iteration entry of the innermost open iteration phase (created on first use), or None."""
        step = self.cur_step
        if step is None:
            return None
        for index in range(len(self.stack) - 1, 0, -1):
            node = self.stack[index]
            if node.kind == "phase" and node.iter_ok:
                if node.iter_entry is None:
                    number = node.number if node.number and node.number[0].isdigit() else ""
                    node.iter_entry = {"label": ("%s %s" % (number, node.label)).strip(), "overlaps": [],
                                       "final_overlaps": None, "wns": None, "tns": None, "whs": None,
                                       "ths": None, "t": self._now(), "line": self.line_no}
                    if len(step.iters) < self.cfg.convergence.max_iterations:
                        step.iters.append(node.iter_entry)
                return node.iter_entry
        return None

    def _on_overlaps(self, match, line):
        entry = self._open_iteration()
        if entry is None:
            return
        value = int(match.group(1))
        values = entry["overlaps"]
        if len(values) < self.cfg.convergence.max_values:
            values.append(value)
        else:
            values[-1] = value
        entry["final_overlaps"] = value
        entry["t"] = self._now()

    def _iteration_timing(self, timing):
        entry = self._open_iteration()
        if entry is None:
            return
        for name in ("wns", "tns", "whs", "ths"):
            entry[name] = timing[name]
        entry["t"] = self._now()

    def _on_task_open(self, match, line):
        name = match.group(1)
        node = self._new_node("task", name + " Task", "t-" + slug(name))
        node.number = name
        node.saved_cum = self.last_cum
        self.last_cum = 0.0
        self.stack.append(node)

    def _on_task_close(self, match, line):
        name = match.group(1)
        index = self._find(("task",), lambda n: n.number == name)
        if index is None:
            self.pending_time = _SKIP
            return
        node = self.stack[index]
        self._truncate(index + 1, self.line_no)
        self.stack.pop()
        self._close(node, self.line_no)
        self.pending_time = node

    def _on_start_timed(self, match, line):
        name = match.group(1)
        reading = self.cfg.time_re.search(line)
        if reading and hms_to_seconds(reading.group(2)) is not None:
            self.last_cum = hms_to_seconds(reading.group(2))
        node = self._new_node("phase", name, "s-" + slug(name))
        node.number = "pair:" + name.lower()
        node.cum_start = self.last_cum
        self.stack.append(node)

    def _on_pair_open(self, match, line):
        name = match.group(1)
        node = self._new_node("phase", name, "s-" + slug(name))
        node.number = "pair:" + name.lower()
        node.cum_start = self.last_cum
        self.stack.append(node)

    def _on_pair_close(self, match, line):
        name, timed = match.group(1), match.group(2) is not None
        index = self._find(("phase",), lambda n: n.number == "pair:" + name.lower())
        if index is not None:
            node = self.stack[index]
            self._truncate(index + 1, self.line_no)
            self.stack.pop()
            self._close(node, self.line_no)
            self._apply_time(node, line)
        elif timed:
            node = self._new_node("phase", name, "s-" + slug(name))
            node.line_end = self.line_no
            node.status = "done"
            node.cum_start = self.last_cum
            self._apply_time(node, line)

    def _on_time_line(self, match, line):
        target = self._prev_pending
        if target is _SKIP:
            return
        top = self.stack[-1]
        if target is None:
            target = top
            # a task that never prints "Ending ..." (e.g. DRC Task) ends with its Time line
            if top.kind == "task" and not top.children:
                self.stack.pop()
                self._close(top, self.line_no)
        self._apply_time(target, line)

    def _on_named_time(self, match, line):
        name = match.group(1)
        node = None
        step = self.cur_step
        if step is not None and step.cmd == name:
            node = step
        elif step is not None:
            for child in reversed(step.children):
                if child.kind == "command" and child.cmd == name:
                    node = child
                    break
        self._apply_time(node, line)

    def _on_summary(self, match, line):
        index = self._find(("step", "command"), lambda n: True)
        if index is not None:
            self.stack[index].summary = [int(g) for g in match.groups()]

    # ---- congestion: estimated tables (placer, router initial) and the final router report
    def _open_congestion(self, kind):
        if self.cur_step is not None:
            self.cur_step.congestion[kind] = {}
            self._cong_open = (kind, self.cur_step)

    def _on_congestion_placer(self, match, line):
        self._open_congestion("placer")

    def _on_congestion_router(self, match, line):
        self._open_congestion("router_initial")

    def _on_congestion_row(self, match, line):
        """Table row: the cells are (size[, % tiles]) for global, long, short; placer tables have sizes only."""
        if self._cong_open is None:
            return
        kind, step = self._cong_open
        settings = self.cfg.congestion
        row = {}
        slots = iter(("global", "long", "short"))
        slot = None
        for cell in (c.strip() for c in match.group(2).split("|")):
            level = settings.level_of_size(cell)
            if level is not None:
                slot = next(slots, None)
                if slot:
                    row[slot] = level
            elif slot and settings.pct_re.match(cell):
                row[slot + "_pct"] = float(cell)
        direction = match.group(1).lower()
        step.congestion[kind][direction] = row
        if len(step.congestion[kind]) >= 4:
            self._cong_open = None

    def _on_congestion_final(self, match, line):
        step = self.cur_step
        if step is None:
            return
        direction = match.group(1).lower()
        level = self.cfg.congestion.level_of_size(match.group(2))
        step.congestion.setdefault("router_final", {})[direction] = {
            "max_pct": float(match.group(3)), "level": level or 0, "congested": match.group(4) is None}

    def _on_congestion_direction(self, match, line):
        self._cong_dir = match.group(1).lower()

    def _on_congestion_effective(self, match, line):
        step, direction = self.cur_step, self._cong_dir
        self._cong_dir = None
        entry = step.congestion.get("router_final", {}).get(direction) if step and direction else None
        if entry is not None:
            entry["level"] = int(match.group(1))
