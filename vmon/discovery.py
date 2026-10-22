"""Find running Vivado processes (read-only, via the platform backend) and group them into firmwares."""
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PureWindowsPath

from .procinfo import get_backend
from .resume import scan_session

LOG_SCAN_BYTES = 2_000_000


@dataclass
class Group:
    kind: str                       # "project" | "log"
    path: str                       # .runs dir or log path
    name: str
    pids: set = field(default_factory=set)
    run_pids: dict = field(default_factory=dict)   # run id -> {pid}
    launcher: dict | None = None
    # resume sessions (open_checkpoint + route_design ... in a non-project Vivado): they ARE the workers
    # of the run they continue, not launchers. {"pid","run","log","script","checkpoint","cwd"}
    resumes: list = field(default_factory=list)


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def _windows_style(path):
    """Drive-letter or UNC paths are split the Windows way even when vmon runs elsewhere (tests)."""
    return sys.platform == "win32" or bool(re.match(r"^([A-Za-z]:[\\/]|\\\\)", path))


def _pure_path(path):
    return PureWindowsPath(path) if _windows_style(path) else PurePath(path)


def _basename(path):
    return _pure_path(path).name


def runs_location(cwd):
    """('/x/foo.runs', 'impl_1') when cwd is inside a *.runs dir (any case, any slash), else None."""
    pure = _pure_path(cwd)
    parts = pure.parts
    for i, part in enumerate(parts):
        if part.lower().endswith(".runs") and len(part) > 5:
            runs_dir = str(type(pure)(*parts[:i + 1]))
            return runs_dir, (parts[i + 1] if i + 1 < len(parts) else None)
    return None


def pid_alive(pid):
    return pid is not None and get_backend().alive(pid)


def scan_vivado():
    """Return [{'pid','ppid','args','cwd'}] for real Vivado processes (platform backend decides)."""
    return get_backend().vivado_processes()


def _arg_after(args, flag):
    for i, arg in enumerate(args[:-1]):
        if arg == flag:
            return args[i + 1]
    return None


def _log_of(proc):
    args, cwd = proc["args"], proc["cwd"]
    log = _arg_after(args, "-log") or (os.path.join(cwd, "vivado.log") if cwd else None)
    if log and not os.path.isabs(log) and cwd:
        log = os.path.join(cwd, log)
    return log


def is_run_worker(proc, run_dir):
    """True for the process Vivado itself starts for a run (log = the run's .vdi/.vds/runme.log)."""
    log = _log_of(proc)
    if not log:
        return False
    name = os.path.basename(log)
    return (os.path.normcase(os.path.dirname(os.path.normpath(log))) == os.path.normcase(os.path.normpath(run_dir))
            and (name.endswith((".vdi", ".vds")) or name == "runme.log"))


def _descendants(pid, children_of):
    out, todo = set(), [pid]
    while todo:
        for child in children_of.get(todo.pop(), ()):
            if child not in out:
                out.add(child)
                todo.append(child)
    return out


class Discovery:
    def __init__(self, config):
        self.cfg = config
        self._log_cache = {}        # log path -> (size, runs_dir | None)

    def _project_from_log(self, log_path, cwd):
        try:
            size = os.stat(log_path).st_size
        except OSError:
            return None
        cached = self._log_cache.get(log_path)
        if cached and (cached[1] is not None or cached[0] == size):
            return cached[1]
        text = _read(log_path)[:LOG_SCAN_BYTES].decode("utf-8", "replace")
        runs_dir = None
        for match in self.cfg.open_project_re.finditer(text):
            xpr = next(g for g in match.groups() if g)
            if not xpr.endswith(".xpr"):
                continue
            xpr_path = Path(xpr) if os.path.isabs(xpr) else Path(cwd or ".") / xpr
            runs_dir = str(xpr_path.parent / (xpr_path.stem + ".runs"))
        self._log_cache[log_path] = (size, runs_dir)
        return runs_dir

    def _resume_target(self, proc, log):
        """(runs_dir, run) when this process's log opens a checkpoint inside a *.runs dir."""
        session = scan_session(log, proc["cwd"], self.cfg)
        return runs_location(session["checkpoint"]) if session["checkpoint"] else None

    def _add_resume(self, group, proc, run):
        log = _log_of(proc)
        session = scan_session(log, proc["cwd"], self.cfg) if log else {"checkpoint": None}
        if run is None and session["checkpoint"]:
            loc = runs_location(session["checkpoint"])
            run = loc[1] if loc else None
        group.resumes.append({"pid": proc["pid"], "run": run, "log": log,
                              "script": _arg_after(proc["args"], "-source"),
                              "checkpoint": session["checkpoint"], "cwd": proc["cwd"]})

    def discover(self):
        procs = scan_vivado()
        if not procs:
            return []
        children_of = {}
        for pid, parent in get_backend().process_table().items():
            children_of.setdefault(parent, []).append(pid)
        groups = {}

        def group_for(kind, path, name):
            key = (kind, path)
            if key not in groups:
                groups[key] = Group(kind, path, name)
            return groups[key]

        in_runs = {}
        for proc in procs:
            loc = runs_location(proc["cwd"]) if proc["cwd"] else None
            if loc:
                in_runs[proc["pid"]] = loc
                runs_dir, run = loc
                group = group_for("project", runs_dir, _basename(runs_dir)[:-5])
                group.pids.add(proc["pid"])
                if run and is_run_worker(proc, os.path.join(runs_dir, run)):
                    group.run_pids.setdefault(run, set()).add(proc["pid"])
                else:
                    self._add_resume(group, proc, run)
        for proc in procs:
            if proc["pid"] in in_runs:
                continue
            args, cwd = proc["args"], proc["cwd"]
            log = _log_of(proc)
            script = _arg_after(args, "-source")
            launcher = {"pid": proc["pid"], "log": log, "script": script}
            target = None
            for pid in _descendants(proc["pid"], children_of):
                if pid in in_runs:
                    target = in_runs[pid][0]
                    break
            if target is None and log:
                target = self._project_from_log(log, cwd)
            if target:
                group = group_for("project", target, _basename(target)[:-5])
                group.pids.add(proc["pid"])
                group.launcher = launcher
            elif log and (ckpt := self._resume_target(proc, log)):
                group = group_for("project", ckpt[0], _basename(ckpt[0])[:-5])
                group.pids.add(proc["pid"])
                self._add_resume(group, proc, ckpt[1])
            elif log and os.path.exists(log):
                group = group_for("log", log, Path(log).stem)
                group.pids.add(proc["pid"])
                group.launcher = launcher
        return list(groups.values())
