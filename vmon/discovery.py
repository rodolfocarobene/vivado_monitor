"""Find running Vivado processes (read-only, via the platform backend) and group them into firmwares."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .paths import basename as _basename, canon, syntax_path
from .procinfo import get_backend
from .textio import decode
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


def runs_location(cwd):
    """('/x/foo.runs', 'impl_1') when cwd is inside a *.runs dir (any case, any slash), else None."""
    pure = syntax_path(cwd)
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


def _absolute(path, base):
    return paths.normpath(path if paths.is_abs(path) else paths.join(base, path))


def _created_runs(args, base):
    """runs dir of `create_project [options] name [dir]` (dir defaults to the current directory)."""
    if args is None or "-in_memory" in args:
        return None
    positional, skip = [], False
    for word in args:
        if skip:
            skip = False
        elif word.startswith("-"):
            skip = word in ("-part", "-ip_repo_paths")      # options that take a value
        else:
            positional.append(word)
    if not positional:
        return None
    where = positional[1] if len(positional) > 1 else "."
    return _absolute(paths.join(_absolute(where, base), positional[0] + ".runs"), base)


def _substitute(text, values):
    """$var / ${var} from `values`; None when a variable is unknown or a command substitution is left."""
    def one(match):
        name = match.group(1) or match.group(2)
        if name not in values:
            raise KeyError(name)
        return values[name]
    try:
        out = re.sub(r"\$\{(\w+)\}|\$(\w+)", one, text)
    except KeyError:
        return None
    return None if "[" in out else out


def _tcl_words(text):
    """Split a simple Tcl command line into words ({..} and ".." groups); None for anything fancier."""
    if text is None:
        return None
    words, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] in "{\"":
            end = text.find("}" if text[i] == "{" else "\"", i + 1)
            if end < 0:
                return None
            words.append(text[i + 1:end])
            i = end + 1
        else:
            end = i
            while end < len(text) and not text[end].isspace():
                end += 1
            words.append(text[i:end])
            i = end
    return words


def _arg_after(args, flag):
    for i, arg in enumerate(args[:-1]):
        if arg == flag:
            return args[i + 1]
    return None


def _log_of(proc):
    args, cwd = proc["args"], proc["cwd"]
    log = _arg_after(args, "-log") or (os.path.join(cwd, "vivado.log") if cwd else None)
    if log and not paths.is_abs(log) and cwd:
        log = paths.join(cwd, log)
    return log


def is_run_worker(proc, run_dir):
    """True for the process Vivado itself starts for a run (log = the run's .vdi/.vds/runme.log)."""
    log = _log_of(proc)
    if not log:
        return False
    name = _basename(log)
    return (paths.same_path(paths.dirname(paths.normpath(log)), paths.normpath(run_dir))
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
        text = decode(_read(log_path)[:LOG_SCAN_BYTES])
        found = self._projects_in(text, cwd)        # (position, runs dir); the last project opened or created wins
        runs_dir = max(found)[1] if found else None
        self._log_cache[log_path] = (size, runs_dir)
        return runs_dir

    def _projects_in(self, text, cwd):
        """[(position, runs dir)] of each open_project / create_project in a launcher log. Vivado echoes a sourced
        script with its variables unexpanded, so simple `set var value` (and `set var [file normalize x]` /
        `[pwd]`) lines seen before are substituted; anything still unresolved is ignored."""
        cfg, values, out = self.cfg, {}, []
        base_dir = cwd or "."
        events = [(m.start(), "set", m) for m in cfg.tcl_set_re.finditer(text)]
        events += [(m.start(), "dir", m) for m in cfg.tcl_set_dir_re.finditer(text)]
        events += [(m.start(), "open", m) for m in cfg.open_project_re.finditer(text)]
        events += [(m.start(), "create", m) for m in cfg.create_project_re.finditer(text)]
        for pos, kind, match in sorted(events, key=lambda e: e[0]):
            if kind == "set":
                values[match.group(1)] = next((g for g in match.groups()[1:] if g is not None), "")
            elif kind == "dir":
                rel = next((g for g in match.groups()[1:4] if g is not None), None)
                values[match.group(1)] = base_dir if match.group(5) else _absolute(rel, base_dir)
            elif kind == "open":
                xpr = _substitute(next(g for g in match.groups() if g), values)
                if xpr and xpr.endswith(".xpr"):
                    full = _absolute(xpr, base_dir)
                    out.append((pos, paths.join(paths.dirname(full), _basename(full)[:-len(".xpr")] + ".runs")))
            else:
                runs = _created_runs(_tcl_words(_substitute(match.group(1), values)), base_dir)
                if runs:
                    out.append((pos, runs))
        return out

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
            path = canon(path)
            key = (kind, paths.path_key(path))
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
                group = group_for("log", log, Path(_basename(log)).stem)
                group.pids.add(proc["pid"])
                group.launcher = launcher
        return list(groups.values())
