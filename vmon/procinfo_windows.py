"""Windows backend (ctypes only, read-only): Toolhelp snapshot, PEB reads, GetSystemTimes, psapi."""
import os

from .winapi import split_command_line

KB = 1024


def is_vivado_image(name):
    """vivado.exe, any case. vivado.bat / loader.exe / cmd.exe are launchers, not Vivado processes."""
    return name.lower() == "vivado.exe"


def is_named_image(name, names):
    """Image name in `names` (given with .exe, any case); returns the matching entry or None."""
    return next((n for n in names if n.lower() == name.lower()), None)


def memory_to_meminfo(status):
    """Map GlobalMemoryStatusEx bytes to the Linux-style kB dict. The commit limit minus physical RAM
    approximates the pagefile size (swap), and its free part is derived the same way; both clamp at 0."""
    swap_total = max(0, status["total_pagefile"] - status["total_phys"])
    swap_free = min(swap_total, max(0, status["avail_pagefile"] - status["avail_phys"]))
    return {"MemTotal": status["total_phys"] // KB, "MemAvailable": status["avail_phys"] // KB,
            "SwapTotal": swap_total // KB, "SwapFree": swap_free // KB}


class WindowsBackend:
    name = "windows"

    def __init__(self, api=None):
        if api is None:
            from .winapi import WinApi
            api = WinApi()
        self.api = api

    def _argv(self, text):
        convert = getattr(self.api, "command_line_to_argv", None)
        argv = convert(text) if convert else None
        return argv if argv else split_command_line(text)

    def process_table(self):
        return {pid: ppid for pid, ppid, _name in self.api.process_entries()}

    def vivado_processes(self):
        found = []
        for pid, ppid, name in self.api.process_entries():
            if not is_vivado_image(name):
                continue
            cmdline, cwd = self.api.command_line_and_cwd(pid)
            found.append({"pid": pid, "ppid": ppid, "args": self._argv(cmdline) if cmdline else [],
                          "cwd": cwd or None})
        return found

    def hls_processes(self, names):
        found = []
        for pid, ppid, name in self.api.process_entries():
            match = is_named_image(name, names)
            if match is None:
                continue
            cmdline, cwd = self.api.command_line_and_cwd(pid)
            found.append({"pid": pid, "ppid": ppid, "args": self._argv(cmdline) if cmdline else [],
                          "cwd": cwd or None, "name": match})
        return found

    def alive(self, pid):
        return pid is not None and pid > 0 and self.api.alive(pid)

    def cpu_seconds(self, pid):
        return self.api.process_cpu_seconds(pid)

    def rss_kb(self, pid):
        size = self.api.working_set_bytes(pid)
        return size // KB if size else 0

    def cpu_times(self):
        times = self.api.system_times()
        if not times:
            return None
        idle, kernel, user = times
        return kernel + user, idle

    def meminfo(self):
        status = self.api.memory_status()
        return memory_to_meminfo(status) if status else {}

    def load1(self):
        return None

    def cpu_count(self):
        return os.cpu_count() or 1
