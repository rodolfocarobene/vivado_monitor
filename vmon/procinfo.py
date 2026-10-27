"""Platform layer for process discovery and resource sampling; picks the backend for this OS.

A backend exposes (all read-only, never raising for a vanished or protected process):
  name                      "linux" | "windows" | "none"
  vivado_processes()        [{"pid", "ppid", "args" (argv list), "cwd"}] for real Vivado binaries
  hls_processes(names)      [{"pid", "ppid", "args", "cwd", "name"}] for Vitis HLS / v++ binaries (optional; names are
                            comm names on Linux, image names with .exe on Windows)
  process_table()           {pid: ppid} for every process (builds the children map)
  alive(pid)                True while the process exists
  cpu_seconds(pid)          user+system CPU time of one process, or None
  rss_kb(pid)               resident memory of one process in kB (0 if unknown)
  cpu_times()               (total, idle) system counters in any consistent unit, or None
  meminfo()                 {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"} in kB
  load1()                   1-minute load average, None where the OS has none
  cpu_count()
"""
import os
import sys

_backend = None


class NullBackend:
    """Unsupported OS (e.g. macOS): no discovery and no stats; manually added paths still work."""
    name = "none"

    def vivado_processes(self):
        return []

    def hls_processes(self, names):
        return []

    def process_table(self):
        return {}

    def alive(self, pid):
        return False

    def cpu_seconds(self, pid):
        return None

    def rss_kb(self, pid):
        return 0

    def cpu_times(self):
        return None

    def meminfo(self):
        return {}

    def load1(self):
        return None

    def cpu_count(self):
        return os.cpu_count() or 1


def make_backend(platform):
    if platform == "win32":
        from .procinfo_windows import WindowsBackend
        return WindowsBackend()
    if platform.startswith("linux"):
        from .procinfo_linux import LinuxBackend
        return LinuxBackend()
    print("vmon: process discovery and resource stats are not supported on %s; "
          "manually added paths still work" % platform, file=sys.stderr)
    return NullBackend()


def get_backend():
    global _backend
    if _backend is None:
        _backend = make_backend(sys.platform)
    return _backend


def set_backend(backend):
    """Override the backend (tests); None re-selects from sys.platform on next use."""
    global _backend
    _backend = backend
