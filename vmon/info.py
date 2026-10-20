"""Build facts for the info panel: part, board, strategies, directives, host, jobs (all read-only).

Sources: gen_run.xml, the project .xpr, `Command: ... -directive X` lines of the .vdi/.vds log,
.vivado.begin.rst, and the run tcl (`set_param runs.launchOptions { -jobs N }`). Results are cached by
(path, mtime, size); the log is only scanned from the last offset.
"""
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

COMMAND_RE = re.compile(r"^Command: (\w+)(.*)$")
DIRECTIVE_RE = re.compile(r"-directive\s+(\S+)")
PART_RE = re.compile(r"-part\s+(\S+)")
HOST_RE = re.compile(r'Host="([^"]*)"')
JOBS_RE = re.compile(r"-jobs\s+(\d+)")
TCL_JOBS_RE = re.compile(r"runs\.launchOptions\s*\{([^}]*)\}")
# a command that runs more than once in a flow maps to a different step the second time
COMMAND_STEPS = {"link_design": ["init_design"], "opt_design": ["opt_design"],
                 "power_opt_design": ["power_opt_design", "post_place_power_opt_design"],
                 "place_design": ["place_design"],
                 "phys_opt_design": ["phys_opt_design", "post_route_phys_opt_design"],
                 "route_design": ["route_design"], "synth_design": ["synth_design"],
                 "write_bitstream": ["write_bitstream"]}


def empty_info():
    return {"part": None, "board": None, "top": None, "vivado_version": None, "host": None,
            "strategy_synth": None, "strategy_impl": None, "directives": {}, "jobs": None, "project": None}


def _stat(path):
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def _read(path, limit=2_000_000):
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


class InfoReader:
    def __init__(self):
        self._cache = {}          # (kind, path) -> (stat, value)
        self._scans = {}          # log path -> {"offset", "counts", "directives", "part"}

    def _cached(self, kind, path, loader):
        stat = _stat(path)
        if stat is None:
            return None
        key = (kind, str(path))
        hit = self._cache.get(key)
        if hit and hit[0] == stat:
            return hit[1]
        value = loader(path)
        self._cache[key] = (stat, value)
        return value

    # ---- individual files
    def gen_run(self, path):
        def load(p):
            try:
                return ET.parse(p).getroot().get("LaunchPart")
            except (ET.ParseError, OSError):
                return None
        return self._cached("gen_run", path, load)

    def xpr(self, path, impl_run):
        def load(p):
            out = {"board": None, "part": None, "synth": None, "impl": None, "jobs": None}
            try:
                root = ET.parse(p).getroot()
            except (ET.ParseError, OSError):
                return out
            for opt in root.iterfind("Configuration/Option"):
                name = opt.get("Name")
                if name == "BoardPart" and not out["board"]:
                    out["board"] = opt.get("Val") or None
                elif name == "Part" and not out["part"]:
                    out["part"] = opt.get("Val") or None
            runs = {r.get("Id"): r for r in root.iter("Run")}
            impl = runs.get(impl_run)
            if impl is not None:
                out["impl"] = _strategy(impl)
                match = JOBS_RE.search(impl.get("LaunchOptions") or "")
                out["jobs"] = int(match.group(1)) if match else None
                out["part"] = out["part"] or impl.get("Part")
                synth = runs.get(impl.get("SynthRun") or "")
                if synth is not None:
                    out["synth"] = _strategy(synth)
            return out
        return self._cached("xpr:" + str(impl_run), path, load)

    def host(self, *paths):
        for path in paths:
            text = self._cached("host", path, lambda p: (HOST_RE.search(_read(p, 20000)) or [None, None])[1])
            if text:
                return text
        return None

    def jobs_from_tcl(self, path):
        def load(p):
            match = TCL_JOBS_RE.search(_read(p, 200000))
            jobs = JOBS_RE.search(match.group(1)) if match else None
            return int(jobs.group(1)) if jobs else None
        return self._cached("tcl", path, load)

    def scan_log(self, path):
        """Incremental scan of `Command:` lines -> ({step: directive}, part)."""
        stat = _stat(path)
        if stat is None:
            return {}, None
        scan = self._scans.get(path)
        if scan is None or stat[1] < scan["offset"]:
            scan = {"offset": 0, "counts": {}, "directives": {}, "part": None}
            self._scans[path] = scan
        if stat[1] > scan["offset"]:
            try:
                with open(path, "rb") as fh:
                    fh.seek(scan["offset"])
                    data = fh.read()
            except OSError:
                return scan["directives"], scan["part"]
            end = data.rfind(b"\n") + 1            # never act on a half-written line
            scan["offset"] += end
            for line in data[:end].decode("utf-8", "replace").split("\n"):
                if not line.startswith("Command: "):
                    continue
                match = COMMAND_RE.match(line)
                if not match:
                    continue
                command, rest = match.groups()
                steps = COMMAND_STEPS.get(command)
                if not steps:
                    continue
                n = scan["counts"].get(command, 0)
                scan["counts"][command] = n + 1
                step = steps[min(n, len(steps) - 1)]
                directive = DIRECTIVE_RE.search(rest)
                if directive:
                    scan["directives"][step] = directive.group(1)
                part = PART_RE.search(rest)
                if part and not scan["part"]:
                    scan["part"] = part.group(1)
        return scan["directives"], scan["part"]


def _strategy(run):
    handle = run.find("Strategy/StratHandle")
    return handle.get("Name") if handle is not None else None


def collect(reader, runs_dir, impl_run, synth_run, log_path, top, version, xpr_path=None):
    """Assemble Firmware.info for a project (runs_dir=<X>.runs) or a bare log (runs_dir None)."""
    info = empty_info()
    info["top"], info["vivado_version"] = top, version
    impl_dir = Path(runs_dir) / impl_run if runs_dir and impl_run else None
    if log_path:
        info["directives"], part = reader.scan_log(log_path)
        info["part"] = part
    if impl_dir:
        info["part"] = reader.gen_run(impl_dir / "gen_run.xml") or info["part"]
        info["host"] = reader.host(impl_dir / ".vivado.begin.rst",
                                   *( [Path(runs_dir) / synth_run / ".vivado.begin.rst"] if synth_run else []))
        if top:
            info["jobs"] = reader.jobs_from_tcl(impl_dir / (top + ".tcl"))
    if xpr_path and xpr_path.is_file():
        xpr = reader.xpr(xpr_path, impl_run)
        if xpr:
            info["project"] = str(xpr_path)
            info["board"] = xpr["board"]
            info["part"] = info["part"] or xpr["part"]
            info["strategy_synth"], info["strategy_impl"] = xpr["synth"], xpr["impl"]
            info["jobs"] = xpr["jobs"] if xpr["jobs"] is not None else info["jobs"]
    return info
