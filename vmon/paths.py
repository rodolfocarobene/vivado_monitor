"""Where vmon keeps its files, and how filesystem paths are compared.

Linux: cache ~/.cache/vmon, config ~/.config/vmon. Windows: cache %LOCALAPPDATA%\\vmon, config %APPDATA%\\vmon
(falling back to ~\\AppData\\Local and ~\\AppData\\Roaming). Resolved on every call so tests can redirect them.

Path contract: parsing keeps the separator style of its input (Vivado writes C:/x and C:\\x in the same file). `runs_location` is the one syntax-only
parser: drive/UNC input comes back with backslashes, anything else as POSIX;
anything that becomes a key or is shown to the user (group paths, watched paths, firmware ids) goes through
`canon`: native form on Windows (backslashes, upper-case drive letter), untouched elsewhere. `path_key` compares
case-insensitively on Windows.
"""
import ntpath
import os
import re
import time
import sys
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

_WINDOWS_PATH = re.compile(r"^([A-Za-z]:[\\/]|\\\\)")


def _on_windows():
    return sys.platform == "win32"


def cache_dir():
    if _on_windows():
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "vmon"
    return Path.home() / ".cache" / "vmon"


def config_dir():
    if _on_windows():
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "vmon"
    return Path.home() / ".config" / "vmon"


def windows_style(path):
    """Drive-letter or UNC syntax: split the Windows way even when vmon runs elsewhere (tests)."""
    return bool(_WINDOWS_PATH.match(str(path)))


def syntax_path(path):
    """Pure path by syntax alone, independent of the OS vmon runs on."""
    return PureWindowsPath(path) if windows_style(path) else PurePosixPath(path)


def pure_path(path):
    return PureWindowsPath(path) if _on_windows() or windows_style(path) else PurePath(path)


def basename(path):
    return pure_path(path).name


def canon(path):
    """Native, normalised spelling of a path for keys and display; identity off Windows."""
    path = str(path)
    if not _on_windows() or not path:
        return path
    path = ntpath.normpath(path)
    return path[0].upper() + path[1:] if re.match(r"^[A-Za-z]:", path) else path


def path_key(path):
    """Comparison key: case-folded and normalised on Windows, the path itself elsewhere."""
    path = str(path)
    return ntpath.normcase(ntpath.normpath(path)) if _on_windows() else path


def same_path(a, b):
    return path_key(a) == path_key(b)


def _mod(*paths):
    """ntpath for Windows-style operands (also when vmon runs elsewhere), else the native os.path."""
    return ntpath if windows_style_any(paths) else os.path


def windows_style_any(paths):
    return _on_windows() or any(windows_style(p) for p in paths if p)


def is_abs(path):
    return _mod(path).isabs(path)


def join(base, rel):
    return _mod(base, rel).join(base, rel)


def normpath(path):
    return _mod(path).normpath(path)


def dirname(path):
    return _mod(path).dirname(path)


def split_name(path):
    """Last component of a path written with either separator (names inside Vivado files, never node ids)."""
    return re.split(r"[\\/]", str(path))[-1]


def write_atomic(path, text, retries=5):
    """Temp file + os.replace. Windows refuses to replace a file another process has open: retry briefly."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
