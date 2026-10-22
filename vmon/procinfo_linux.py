"""Linux backend: everything comes from /proc (read-only)."""
import os

CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def _read_text(path):
    return _read(path).decode("utf-8", "replace")


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


class LinuxBackend:
    name = "linux"

    def __init__(self, proc="/proc"):
        self.proc = proc

    def _pids(self):
        try:
            return [int(n) for n in os.listdir(self.proc) if n.isdigit()]
        except OSError:
            return []

    def _stat(self, pid):
        return parse_proc_stat(_read_text("%s/%d/stat" % (self.proc, pid)))

    def process_table(self):
        table = {}
        for pid in self._pids():
            parsed = self._stat(pid)
            if parsed:
                table[pid] = parsed[0]
        return table

    def alive(self, pid):
        return pid is not None and os.path.exists("%s/%d" % (self.proc, pid))

    def cpu_seconds(self, pid):
        parsed = self._stat(pid)
        return parsed[1] / CLK_TCK if parsed else None

    def rss_kb(self, pid):
        return parse_status_rss_kb(_read_text("%s/%d/status" % (self.proc, pid)))

    def cpu_times(self):
        return parse_cpu_times(_read_text(self.proc + "/stat"))

    def meminfo(self):
        return parse_meminfo(_read_text(self.proc + "/meminfo"))

    def load1(self):
        return parse_loadavg(_read_text(self.proc + "/loadavg"))

    def cpu_count(self):
        return os.cpu_count() or 1

    def vivado_processes(self):
        """Real vivado binaries (not the bash wrappers)."""
        found = []
        for pid in self._pids():
            if _read("%s/%d/comm" % (self.proc, pid)).strip() != b"vivado":
                continue
            try:
                exe = os.path.basename(os.readlink("%s/%d/exe" % (self.proc, pid)))
            except OSError:
                exe = ""
            args = [a.decode("utf-8", "replace")
                    for a in _read("%s/%d/cmdline" % (self.proc, pid)).split(b"\0") if a]
            if exe != "vivado" and not (args and os.path.basename(args[0]) == "vivado"
                                        and "unwrapped" in args[0]):
                continue
            try:
                cwd = os.readlink("%s/%d/cwd" % (self.proc, pid))
            except OSError:
                cwd = None
            parsed = self._stat(pid)
            found.append({"pid": pid, "ppid": parsed[0] if parsed else None, "args": args, "cwd": cwd})
        return found
