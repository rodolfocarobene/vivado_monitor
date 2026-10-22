"""System and per-firmware resource sampling through the platform backend (read-only)."""
import time

from .procinfo import get_backend
from .procinfo_linux import (CLK_TCK, LinuxBackend, parse_cpu_times, parse_loadavg,  # noqa: F401
                             parse_meminfo, parse_proc_stat, parse_status_rss_kb)


def cpu_percent(prev, cur):
    if prev is None or cur is None:
        return 0.0
    total, idle = cur[0] - prev[0], cur[1] - prev[1]
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (total - idle) / total)), 1)


def system_snapshot(cpu_pct, meminfo, load1, cpu_count):
    total = meminfo.get("MemTotal", 0)
    used = total - meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    swap_total = meminfo.get("SwapTotal", 0)
    swap_used = swap_total - meminfo.get("SwapFree", 0)
    mb = 1024.0
    return {"cpu_pct": cpu_pct, "cpu_count": cpu_count, "load1": load1,
            "mem_used_mb": round(used / mb, 1), "mem_total_mb": round(total / mb, 1),
            "swap_used_mb": round(swap_used / mb, 1), "swap_total_mb": round(swap_total / mb, 1)}


class Sampler:
    """Keeps the previous readings so each call yields deltas (CPU%)."""

    def __init__(self, proc=None, backend=None):
        self.backend = backend or (LinuxBackend(proc) if proc else get_backend())
        self.cpu_count = self.backend.cpu_count()
        self._cpu = None
        self._cpu_seconds = {}      # pid -> cpu seconds at the previous sample
        self._time = None

    def system(self):
        cur = self.backend.cpu_times()
        pct = cpu_percent(self._cpu, cur)
        self._cpu = cur
        return system_snapshot(pct, self.backend.meminfo(), self.backend.load1(), self.cpu_count)

    @staticmethod
    def _children(table):
        children = {}
        for pid, ppid in table.items():
            children.setdefault(ppid, []).append(pid)
        return children

    def resources(self, pid_groups, now=None):
        """pid_groups: {key: [pids]} -> {key: {"cpu_pct", "rss_mb"} | None}, using descendants too."""
        now = now if now is not None else time.monotonic()
        wanted = {k: p for k, p in pid_groups.items() if p}
        if not wanted:
            self._cpu_seconds, self._time = {}, now
            return {k: None for k in pid_groups}
        table = self.backend.process_table()
        children = self._children(table)
        dt = (now - self._time) if self._time is not None else 0.0
        out = {k: None for k in pid_groups}
        seconds = {}
        for key, pids in wanted.items():
            tree, stack = set(), [p for p in pids if p in table]
            while stack:
                pid = stack.pop()
                if pid in tree:
                    continue
                tree.add(pid)
                stack.extend(children.get(pid, ()))
            for pid in tree:
                if pid not in seconds:
                    seconds[pid] = self.backend.cpu_seconds(pid)
            delta = sum(max(0.0, seconds[p] - self._cpu_seconds[p])
                        for p in tree if seconds[p] is not None and p in self._cpu_seconds)
            rss = sum(self.backend.rss_kb(p) for p in tree)
            pct = 100.0 * delta / dt if dt > 0 else 0.0
            out[key] = {"cpu_pct": round(pct, 1), "rss_mb": round(rss / 1024.0, 1)}
        self._cpu_seconds = {p: s for p, s in seconds.items() if s is not None}
        self._time = now
        return out
