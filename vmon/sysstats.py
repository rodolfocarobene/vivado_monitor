"""System and per-firmware resource sampling from /proc (read-only, Linux)."""
import os
import time

CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _read(path):
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def parse_cpu_times(text):
    """(busy+idle total, idle) jiffies from the aggregate 'cpu ' line of /proc/stat, or None."""
    for line in text.split("\n"):
        if line.startswith("cpu "):
            try:
                values = [int(v) for v in line.split()[1:]]
            except ValueError:
                return None
            if len(values) < 4:
                return None
            idle = values[3] + (values[4] if len(values) > 4 else 0)     # idle + iowait
            return sum(values[:8]), idle
    return None


def cpu_percent(prev, cur):
    if prev is None or cur is None:
        return 0.0
    total, idle = cur[0] - prev[0], cur[1] - prev[1]
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (total - idle) / total)), 1)


def parse_meminfo(text):
    """Values in kB keyed by field name."""
    out = {}
    for line in text.split("\n"):
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            try:
                out[name] = int(parts[0])
            except ValueError:
                pass
    return out


def parse_loadavg(text):
    try:
        return float(text.split()[0])
    except (IndexError, ValueError):
        return 0.0


def system_snapshot(cpu_pct, meminfo, load1, cpu_count):
    total = meminfo.get("MemTotal", 0)
    used = total - meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    swap_total = meminfo.get("SwapTotal", 0)
    swap_used = swap_total - meminfo.get("SwapFree", 0)
    mb = 1024.0
    return {"cpu_pct": cpu_pct, "cpu_count": cpu_count, "load1": load1,
            "mem_used_mb": round(used / mb, 1), "mem_total_mb": round(total / mb, 1),
            "swap_used_mb": round(swap_used / mb, 1), "swap_total_mb": round(swap_total / mb, 1)}


def parse_proc_stat(text):
    """(ppid, utime+stime ticks) from /proc/PID/stat; comm may contain spaces/parens."""
    try:
        fields = text.rsplit(")", 1)[1].split()
        return int(fields[1]), int(fields[11]) + int(fields[12])
    except (IndexError, ValueError):
        return None


def parse_status_rss_kb(text):
    for line in text.split("\n"):
        if line.startswith("VmRSS:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return 0
    return 0


class Sampler:
    """Keeps the previous readings so each call yields deltas (CPU%)."""

    def __init__(self, proc="/proc"):
        self.proc = proc
        self.cpu_count = os.cpu_count() or 1
        self._cpu = None
        self._ticks = {}            # pid -> cpu ticks at the previous sample
        self._time = None

    def system(self):
        cur = parse_cpu_times(_read(self.proc + "/stat"))
        pct = cpu_percent(self._cpu, cur)
        self._cpu = cur
        return system_snapshot(pct, parse_meminfo(_read(self.proc + "/meminfo")),
                               parse_loadavg(_read(self.proc + "/loadavg")), self.cpu_count)

    def _children_map(self):
        children, ticks = {}, {}
        try:
            names = os.listdir(self.proc)
        except OSError:
            return children, ticks
        for name in names:
            if name.isdigit():
                parsed = parse_proc_stat(_read("%s/%s/stat" % (self.proc, name)))
                if parsed:
                    pid = int(name)
                    children.setdefault(parsed[0], []).append(pid)
                    ticks[pid] = parsed[1]
        return children, ticks

    def resources(self, pid_groups, now=None):
        """pid_groups: {key: [pids]} -> {key: {"cpu_pct", "rss_mb"} | None}, using descendants too."""
        now = now if now is not None else time.monotonic()
        wanted = {k: p for k, p in pid_groups.items() if p}
        if not wanted:
            self._ticks, self._time = {}, now
            return {k: None for k in pid_groups}
        children, ticks = self._children_map()
        dt = (now - self._time) if self._time is not None else 0.0
        out = {k: None for k in pid_groups}
        for key, pids in wanted.items():
            tree, stack = set(), [p for p in pids if p in ticks]
            while stack:
                pid = stack.pop()
                if pid in tree:
                    continue
                tree.add(pid)
                stack.extend(children.get(pid, ()))
            delta = sum(max(0, ticks[p] - self._ticks[p]) for p in tree if p in self._ticks)
            rss = sum(parse_status_rss_kb(_read("%s/%d/status" % (self.proc, p))) for p in tree)
            pct = 100.0 * delta / CLK_TCK / dt if dt > 0 else 0.0
            out[key] = {"cpu_pct": round(pct, 1), "rss_mb": round(rss / 1024.0, 1)}
        self._ticks = {p: t for p, t in ticks.items()}
        self._time = now
        return out
