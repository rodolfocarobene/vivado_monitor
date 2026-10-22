"""Where the terminal views get their state: a running vmon (its /api/state), else a local monitor.

A local monitor is read-only here: it never updates the recent-paths list. A tick still writes what a normal
tick writes (baselines, durations, history, clock history under the cache dir).
"""
import json
import os
import sys
import threading
import urllib.request

from .config import load_config
from .monitor import Monitor, resolve_path

TICK_TIMEOUT = 120.0
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # no proxies for localhost/tunnels


def fetch_state(host, port, timeout=2.0):
    """The state dict of the vmon on host:port, or None when nothing (or something else) answers."""
    try:
        with _OPENER.open("http://%s:%d/api/state" % (host, port), timeout=timeout) as resp:
            state = json.load(resp)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and "firmwares" in state else None


def path_keys(paths):
    """Normalised watched locations for the given user paths (None entries are unusable ones)."""
    return [resolved and os.path.normcase(resolved[1]) for resolved in (resolve_path(p) for p in paths)]


def filter_state(state, paths):
    """Keep the firmwares at or under any of `paths` (a running vmon already knows its own); returns a new state."""
    keys = [k for k in path_keys(paths) if k]
    if not keys:
        return state

    def wanted(fw):
        p = os.path.normcase(fw.get("path") or "")
        return any(p == k or p.startswith(k + os.sep) or k.startswith(p + os.sep) for k in keys)

    return {**state, "firmwares": [fw for fw in state.get("firmwares") or [] if wanted(fw)]}


class Source:
    """`state()` -> state dict or None. mode is 'running' (a vmon answered) or 'local'."""

    def __init__(self, host, port, paths=(), config=None, interval=1.0, live=False, timeout=TICK_TIMEOUT):
        self.host, self.port, self.paths, self.live, self.timeout = host, port, list(paths), live, timeout
        self.monitor = None
        self.warnings = []
        if fetch_state(host, port, 1.0) is not None:
            self.mode = "running"
            return
        self.mode = "local"
        self.monitor = Monitor(load_config(config), interval=interval, read_only=True)
        for path in self.paths:
            if self.monitor.add_path(path) is None:
                self.warnings.append("ignoring %s (not a .runs dir, .xpr or log file)" % path)
        if live:
            self.monitor.start()

    @property
    def label(self):
        return ("vmon on %s:%d" % (self.host, self.port)) if self.mode == "running" else "local (no vmon running)"

    def state(self):
        if self.mode == "running":
            state = fetch_state(self.host, self.port)
            return state and filter_state(state, self.paths)
        if not self.live and not self._tick_once():
            return None
        return json.loads(self.monitor.state_json())

    def _tick_once(self):
        worker = threading.Thread(target=self.monitor.tick, name="vmon-oneshot", daemon=True)
        worker.start()
        worker.join(self.timeout)
        if worker.is_alive():
            print("vmon: no snapshot after %gs, giving up" % self.timeout, file=sys.stderr)
            return False
        return True

    def refresh(self):
        if self.monitor and self.live:
            self.monitor._wake.set()

    def close(self):
        if self.monitor and self.live:
            self.monitor.stop()
