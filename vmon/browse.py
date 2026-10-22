"""Read-only directory listing for the UI's path picker (GET /api/browse)."""
import os
import string
import sys
from pathlib import Path

from .paths import path_key

MAX_ENTRIES = 2000
MAX_PEEK_DIRS = 300            # subdirectories whose content is looked at for kind detection
MAX_PEEK_ENTRIES = 200         # entries read per peeked directory
FILE_SUFFIXES = (".xpr", ".log", ".vdi", ".vds")
SPECIAL_FS = ("/proc", "/sys", "/dev")
RUN_MARKERS = ("runme.log", "gen_run.xml")
DEVICE_PREFIXES = ("\\\\.\\", "\\\\?\\")      # \\.\ and \\?\ device namespaces (Windows)
DRIVES = "::drives"          # pseudo path: the list of drive roots, the parent of every drive root on Windows


class BrowseError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _windows():
    return sys.platform == "win32"


def is_special(path):
    if _windows():
        return path.startswith(DEVICE_PREFIXES)
    return any(path == p or path.startswith(p + "/") for p in SPECIAL_FS)


def list_drives():
    """Existing drive roots such as 'C:\\' (os.listdrives needs 3.12+; older versions probe A-Z)."""
    if hasattr(os, "listdrives"):
        return sorted(os.listdrives())
    return [root for root in ("%s:\\" % c for c in string.ascii_uppercase) if os.path.exists(root)]


def _drive_listing(home, recent):
    entries = [{"name": d, "path": d, "type": "dir", "kind": None, "mtime": 0, "live": False} for d in list_drives()]
    return {"path": DRIVES, "parent": None, "home": home, "drives": True, "entries": entries, "recent": recent}


def _peek_kind(path):
    """'run' | 'project_dir' | None from one level of the directory (bounded)."""
    kind = None
    try:
        with os.scandir(path) as it:
            for index, entry in enumerate(it):
                if index >= MAX_PEEK_ENTRIES:
                    break
                if entry.name in RUN_MARKERS:
                    return "run"
                if entry.name.endswith(".xpr"):
                    kind = "project_dir"
    except OSError:
        return None
    return kind


def live_paths(firmwares):
    """Paths (runs dirs, their run dirs and project dir, logs) used by live firmwares."""
    out = set()
    for fw in firmwares:
        if not fw.live:
            continue
        out.add(fw.path)
        if fw.kind == "project":
            runs = Path(fw.path)
            out.add(str(runs.parent))
            try:
                out.update(str(p) for p in runs.iterdir() if p.is_dir())
            except OSError:
                pass
            if runs.name.endswith(".runs"):
                out.add(str(runs.parent / (runs.name[:-5] + ".xpr")))
    return out


def browse(text, home, live, recent):
    if _windows() and text == DRIVES:
        return _drive_listing(home, recent)
    if text.startswith(DEVICE_PREFIXES) and _windows():
        raise BrowseError(403, "not browsable")
    path = os.path.realpath(os.path.expanduser(text)) if text else home
    if is_special(path):
        raise BrowseError(403, "not browsable")
    if not os.path.isdir(path):
        raise BrowseError(404, "not a directory")
    live = {path_key(p) for p in live}
    entries, peeked = [], 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                if len(entries) >= MAX_ENTRIES:
                    break
                name = entry.name
                if name.startswith("."):
                    continue
                full = os.path.join(path, name)
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    continue
                if is_dir:
                    if name.endswith(".runs"):
                        kind = "runs"
                    elif peeked < MAX_PEEK_DIRS and not is_special(full):
                        peeked += 1
                        kind = _peek_kind(full)
                    else:
                        kind = None
                elif name.endswith(FILE_SUFFIXES):
                    kind = "xpr" if name.endswith(".xpr") else "log"
                else:
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    mtime = 0
                entries.append({"name": name, "path": full, "type": "dir" if is_dir else "file",
                                "kind": kind, "mtime": mtime, "live": path_key(full) in live})
    except PermissionError:
        raise BrowseError(403, "permission denied")
    except OSError:
        raise BrowseError(404, "unreadable")
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    parent = os.path.dirname(path)
    if parent == path:
        parent = DRIVES if _windows() else None
    return {"path": path, "parent": parent, "home": home, "drives": _windows(),
            "entries": entries, "recent": recent}
