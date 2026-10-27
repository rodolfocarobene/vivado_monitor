"""Reads the Tcl script of a non-project build: which step commands it calls, in order.

Best effort and read-only: a `source`d file is followed (cycles and huge files are skipped), commented lines are
ignored, procs are not special-cased (a proc body that is called counts, one that is not is a false step).
"""
import ntpath
import posixpath
import os
import re

from .textio import decode


def _join(base, name):
    pathmod = ntpath if "\\" in base or ":" in base[:2] else posixpath
    return pathmod.normpath(pathmod.join(base, name))


_VAR = re.compile(r"\$(?:\{(\w+)\}|(?:::)?(\w+))")
_LINDEX = re.compile(r"^\[\s*lindex\s+\$(?:::)?argv\s+(\d+)\s*\]$")
_NORMALIZE = re.compile(r"^\[\s*file\s+normalize\s+(.+?)\s*\]$")


def substitute(text, variables):
    """`$name` / `${name}` replaced; None when one is unknown."""
    missing = []

    def value(match):
        found = variables.get(match.group(1) or match.group(2))
        if found is None:
            missing.append(match.group(0))
            return ""
        return found

    out = _VAR.sub(value, text)
    return None if missing else out


def _unwrap(word):
    return word[1:-1] if len(word) > 1 and word[0] + word[-1] in ("{}", '""') else word


def _evaluate(expr, variables, cwd, tclargs):
    """Value of the right side of a simple `set`, or None when it needs more than Tcl-lite."""
    if expr == "[pwd]":
        return cwd
    if m := _LINDEX.match(expr):
        index = int(m.group(1))
        return tclargs[index] if index < len(tclargs) else None
    if m := _NORMALIZE.match(expr):
        inner = _evaluate(m.group(1), variables, cwd, tclargs)
        return _join(cwd, inner) if inner and cwd else inner
    if expr[:1] == "[" or (expr[:1] != "{" and " " in expr and expr[:1] != '"'):
        return None
    text = _unwrap(expr)
    return text if expr[:1] == "{" else substitute(text, variables)


def _read(path, limit):
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as fh:
            return decode(fh.read())
    except OSError:
        return None


def script_commands(script, cwd, cfg, tclargs=()):
    """(commands, files, variables): the step/report commands the script calls in order, following `source`, the
    files read, and the simple `set var value` assignments (last wins; `[lindex $argv N]` from tclargs).
    commands is None when the script itself cannot be read."""
    spec = cfg.nonproject
    commands, files, seen, variables = [], [], set(), {}

    def visit(path):
        key = os.path.normcase(os.path.abspath(path))
        if key in seen or len(seen) >= spec.max_script_files:
            return True
        seen.add(key)
        text = _read(path, spec.script_size_limit)
        if text is None:
            return False
        files.append(path)
        here = os.path.dirname(path)
        for line in text.split("\n"):
            if line.lstrip().startswith("#"):
                continue
            if m := spec.set_re.match(line):
                value = _evaluate(m.group(2), variables, cwd, tclargs)
                if value is not None:
                    variables[m.group(1)] = value
            hits = [(m.start(1), m.group(1), None) for m in spec.command_re.finditer(line)]
            for m in spec.source_re.finditer(line):
                hits.append((m.start(), None, m))
            for _, command, source in sorted(hits, key=lambda h: h[0]):
                if command:
                    commands.append(command)
                    continue
                braced, quoted, from_script, bare = source.groups()
                target = braced or quoted or bare
                if from_script:
                    target = _join(here, from_script)
                elif target and "$" not in target and "[" not in target:
                    target = _join(cwd, target) if cwd and not os.path.isabs(target) else target
                    if not os.path.exists(target):
                        target = _join(here, os.path.basename(target))
                else:
                    continue
                visit(target)
        return True

    first = script if os.path.isabs(script) or not cwd else _join(cwd, script)
    if not visit(first):
        return None, files, variables
    return commands, files, variables


def plan_steps(commands, cfg):
    """Step ids the commands run, in flow order: a repeated command takes the next step that runs it (a second
    phys_opt_design after route_design is post_route_phys_opt_design)."""
    planned, last = [], -1
    for command in commands:
        for step in cfg.steps_for_command(command):
            index = cfg.step_order.index(step.id)
            if step.id not in planned and index > last:
                planned.append(step.id)
                last = index
                break
    return planned
