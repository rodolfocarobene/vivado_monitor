"""`vmon --tui`: live full-screen terminal view (curses). The Model and its rendering are pure and testable;
only `run`/`_loop` touch the terminal. Without curses (Windows) or a TTY it falls back to `vmon status --watch`."""
import shutil
import sys
import threading
import time

from . import status, term
from .source import Source

try:
    import curses
except ImportError:             # Windows has no curses in the standard library
    curses = None

HELP = ["vmon terminal view", "",
        "  Up/Down, j/k   move in the focused pane", "  Enter, Right, l   expand (firmware alerts, stage children)",
        "  Left            collapse", "  Tab             switch focus: firmwares / stages",
        "  PgUp/PgDn       move by page", "  r               refresh now", "  h or ?          this help",
        "  q               quit", "", "Colors: green done/met, red final failure, amber warning or estimate,",
        "blue running. A '~' before WNS/WHS marks a non-final estimate.", "", "press any key to close"]
KEYS_HINT = "q quit  r refresh  Tab focus  j/k move  Enter expand  h help"


def node_tone(status_):
    return term.STATUS_TONE.get(status_, "dim")


class Model:
    def __init__(self, label=""):
        self.state, self.label = {"firmwares": []}, label
        self.selected_id = None
        self.focus = "list"
        self.expanded = set()           # fw ids showing alerts/hints under their row
        self.node_open = {}             # node id -> bool, overrides "open while running"
        self.node_index = 0
        self.list_top = self.detail_top = 0
        self.show_help = False
        self.error = None

    # ---- state
    @property
    def firmwares(self):
        return self.state.get("firmwares") or []

    def update(self, state):
        self.error = None if state is not None else "no answer from %s" % self.label
        if state is not None:
            self.state = state
        ids = [fw.get("id") for fw in self.firmwares]
        if self.selected_id not in ids:
            self.selected_id = ids[0] if ids else None
        self.node_index = min(self.node_index, max(len(self.stage_rows()) - 1, 0))

    def current(self):
        return next((fw for fw in self.firmwares if fw.get("id") == self.selected_id), None)

    def stage_rows(self, fw=None):
        """[(node, depth)] visible in the stage pane: running nodes open by default, others on request."""
        fw = fw or self.current()
        rows = []

        def add(nodes, depth):
            for node in nodes:
                rows.append((node, depth))
                if self.is_open(node):
                    add(node.get("children") or (), depth + 1)

        add(term.stages(fw) if fw else (), 0)
        return rows

    def is_open(self, node):
        return bool(node.get("children")) and self.node_open.get(node.get("id"), node.get("status") == "running")

    # ---- input
    def move(self, delta):
        if self.focus == "list":
            ids = [fw.get("id") for fw in self.firmwares]
            if ids:
                i = ids.index(self.selected_id) if self.selected_id in ids else 0
                self.selected_id = ids[max(0, min(len(ids) - 1, i + delta))]
                self.node_index = self.detail_top = 0
        else:
            self.node_index = max(0, min(max(len(self.stage_rows()) - 1, 0), self.node_index + delta))

    def expand(self, opened=True):
        if self.focus == "list":
            (self.expanded.add if opened else self.expanded.discard)(self.selected_id)
            return
        rows = self.stage_rows()
        if rows:
            node = rows[self.node_index][0]
            if node.get("children"):
                self.node_open[node["id"]] = opened

    def handle(self, key, page=10):
        """Apply a key name; returns 'quit', 'refresh' or None."""
        if self.show_help:
            self.show_help = False
            return None
        if key == "q":
            return "quit"
        if key == "r":
            return "refresh"
        moves = {"up": -1, "k": -1, "down": 1, "j": 1, "pgup": -page, "pgdn": page}
        if key in moves:
            self.move(moves[key])
        elif key in ("enter", "right", "l"):
            self.expand(True)
        elif key == "left":
            self.expand(False)
        elif key == "tab":
            self.focus = "detail" if self.focus == "list" else "list"
        elif key in ("h", "?"):
            self.show_help = True
        return None

    # ---- rendering
    def render(self, height, width, now=None):
        """Exactly `height` lines, each a list of (text, tone) segments no wider than `width`."""
        now = time.time() if now is None else now
        if self.show_help:
            lines = [[(text, "bold" if i == 0 else "dim")] for i, text in enumerate(HELP)]
        else:
            lines = self._screen(height, width, now)
        lines = [term.clip_line(line, width) for line in lines[:height]]
        return lines + [[] for _ in range(height - len(lines))]

    def _title(self, width, now):
        left = [("vmon ", "bold"), (self.label, "dim")]
        right = time.strftime("%H:%M:%S", time.localtime(now))
        if self.error:
            left.append(("  " + self.error, "amber"))
        used = sum(len(t) for t, _ in left)
        return left + [(" " * max(1, width - used - len(right)) + right, "dim")]

    def _screen(self, height, width, now):
        body = max(height - 2, 0)
        fws = self.firmwares
        table = term.table_lines(self.state, width, now, selected=self.selected_id, expanded=self.expanded)
        list_h = min(len(table), body) if body < 8 else min(len(table), max(3, body // 2))
        out = [self._title(width, now)]
        if not fws:
            out.append([("No firmware found. Start a Vivado build, or run vmon --tui <path>.", "dim")])
            list_h = 1
        else:
            out += self._window(table, list_h)
        if body - list_h > 2 and self.current():
            out += self._detail(body - list_h, width, now)
        out = out[:height - 1]
        return out + [[]] * (height - 1 - len(out)) + [[(KEYS_HINT, "dim")]]

    def _window(self, table, size):
        """Header plus a scrolled slice of the rows that keeps the selected one visible."""
        header, rows = table[:1], table[1:]
        room = max(size - 1, 0)
        sel = next((i for i, line in enumerate(rows) if line and line[0][0].endswith("> ")), 0)
        self.list_top = max(0, min(self.list_top, sel), sel - room + 1) if room else 0
        return header + rows[self.list_top:self.list_top + room]

    def _detail(self, size, width, now):
        fw = self.current()
        stale = term.stale_of(fw, self.state)
        _, label, tone = term.outcome(fw, stale)
        mark = "*" if self.focus == "detail" else " "
        head = [("%s %s · " % (mark, term.name_text(fw)), "bold"), (label, tone),
                (" · " + term.step_text(fw, stale), "dim")]
        rows = [self._stage_line(n, depth, i == self.node_index and self.focus == "detail", width, now)
                for i, (n, depth) in enumerate(self.stage_rows())]
        extra = self._notes(fw)
        room = max(size - 1, 0)
        self.detail_top = max(0, min(self.detail_top, self.node_index), self.node_index - room + 1) if room else 0
        view = (rows + extra)[self.detail_top:self.detail_top + room]
        return [head] + view

    def _stage_line(self, node, depth, selected, width, now):
        status_ = node.get("status", "pending")
        chev = ("▾ " if self.is_open(node) else "▸ ") if node.get("children") else "  "
        dur = node.get("elapsed_s")
        if dur is None and status_ == "running" and node.get("started_at"):
            dur = now - node["started_at"]
        prog = node.get("progress")
        timing, timing_tone = term.timing_cell(node) if node.get("timing") else ("", "dim")
        c = node.get("counts") or {}
        counts = "/".join(str(c.get(k, 0)) for k in ("error", "critical", "warning"))
        # Fixed-width, right-aligned columns (blank when empty) so rows line up; narrow terminals drop the
        # rightmost columns first, like `vmon status`.
        cols = [(("%d/%d" % (prog["done"], prog["total"])) if prog and status_ == "running" else "", "blue", 9),
                (term.fmt_dur(dur) if dur is not None else "", "dim", 8),
                (timing if timing != "-" else "", timing_tone, 16),
                (counts if any(c.get(k) for k in ("error", "critical", "warning")) else "", "amber", 12)]
        for drop, need in ((3, 76), (2, 60)):
            if width < need and len(cols) > drop:
                cols = cols[:drop]
        right = [(("  " + t.rjust(w)), tone) for t, tone, w in cols]
        left = "%s%s%s %s" % ("> " if selected else "  ", "  " * depth + chev, term.MARKER.get(status_, "?"), node.get("label"))
        room = width - sum(len(t) for t, _ in right)
        left = term.clip(left, max(room - 1, 1))
        return [(left.ljust(max(room, 0)), "bold" if selected else node_tone(status_))] + right

    def _notes(self, fw):
        out = []
        if fw.get("alerts"):
            out.append([("", "dim")])
            out.append([("Alerts", "bold")])
            out += [[("  ! " + a.get("message", ""), "red" if a.get("level") == "error" else "amber")]
                    for a in fw["alerts"]]
        if fw.get("hints"):
            out.append([("", "dim")])
            out.append([("Hints", "bold")])
            for h in fw["hints"]:
                out.append([("  > " + h.get("title", ""), "blue"), ((" - " + h["evidence"]) if h.get("evidence") else "", "dim")])
        return out


# ------------------------------------------------------------------ curses
NAMED = {9: "tab", 10: "enter", 13: "enter"}
if curses is not None:
    NAMED.update({curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right",
                  curses.KEY_PPAGE: "pgup", curses.KEY_NPAGE: "pgdn", curses.KEY_ENTER: "enter"})


def key_name(key):
    """Name of a curses key code for Model.handle ('' when unmapped)."""
    return chr(key) if 32 <= key < 127 else NAMED.get(key, "")


def draw(win, lines, attr_of):
    """Paint segment lines on a window-like object (addnstr/getmaxyx/erase)."""
    height, width = win.getmaxyx()
    win.erase()
    for y, line in enumerate(lines[:height]):
        x = 0
        for text, tone in line:
            try:
                win.addnstr(y, x, text, max(width - x, 0), attr_of(tone))
            except curses.error:      # writing the bottom-right cell raises; harmless
                pass
            x += len(text)
    win.refresh()


def tone_attrs(color):
    """tone -> curses attribute, with a monochrome fallback."""
    if color:
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        for i, fg in enumerate((curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_CYAN), 1):
            curses.init_pair(i, fg, bg)
        base = {"green": curses.color_pair(1), "red": curses.color_pair(2), "amber": curses.color_pair(3),
                "blue": curses.color_pair(4)}
    else:
        base = {"red": curses.A_BOLD | curses.A_UNDERLINE, "amber": curses.A_UNDERLINE, "blue": curses.A_BOLD}
    base.update(dim=curses.A_DIM, bold=curses.A_BOLD)
    return lambda tone: base.get(tone, 0)


class Poller(threading.Thread):
    """Fetches the state off the UI thread so a slow vmon or remote never freezes the keys."""

    def __init__(self, source, interval):
        super().__init__(name="vmon-tui-poll", daemon=True)
        self.source, self.interval = source, interval
        self.latest, self.fresh = None, False
        self.wake, self.stop_event, self.lock = threading.Event(), threading.Event(), threading.Lock()

    def run(self):
        while not self.stop_event.is_set():
            state = self.source.state()
            with self.lock:
                self.latest, self.fresh = state, True
            self.wake.wait(self.interval)
            self.wake.clear()

    def take(self):
        with self.lock:
            fresh, self.fresh = self.fresh, False
            return fresh, self.latest


def _loop(stdscr, source, interval):
    import os
    curses.curs_set(0)
    stdscr.timeout(200)
    attr_of = tone_attrs(curses.has_colors() and not os.environ.get("NO_COLOR"))
    model = Model(source.label)
    poller = Poller(source, interval)
    poller.start()
    try:
        while True:
            fresh, state = poller.take()
            if fresh:
                model.update(state)
            height, width = stdscr.getmaxyx()
            draw(stdscr, model.render(height, width), attr_of)
            key = stdscr.getch()
            if key == -1 or key == curses.KEY_RESIZE:
                continue
            action = model.handle(key_name(key), max(height // 2, 1))
            if action == "quit":
                return
            if action == "refresh":
                source.refresh()
                poller.wake.set()
    finally:
        poller.stop_event.set()
        poller.wake.set()


def run(args):
    if curses is None or not (sys.stdin.isatty() and sys.stdout.isatty()):
        why = "curses is not available here" if curses is None else "not a terminal"
        print("vmon: %s, showing a refreshing text view instead (like `vmon status --watch`)" % why, file=sys.stderr)
        argv = list(args.paths) + ["--port", str(args.port), "--host", args.host, "--watch", str(max(args.interval, 1.0))]
        return status.run(argv + (["--config", args.config] if args.config else []))
    import locale
    locale.setlocale(locale.LC_ALL, "")
    try:
        source = Source(args.host, args.port, args.paths, args.config, interval=args.interval, live=True)
    except (ValueError, OSError) as exc:
        print("vmon: %s" % exc, file=sys.stderr)
        return 2
    try:
        curses.wrapper(_loop, source, max(args.interval, 0.5))
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
    for warning in source.warnings:
        print("vmon: %s" % warning, file=sys.stderr)
    return 0
