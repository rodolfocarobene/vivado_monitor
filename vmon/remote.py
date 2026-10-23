"""Remote vmon instances (usually reached through an SSH tunnel): poll their state, merge it, proxy requests.

Only hosts from the config are ever contacted; the request never chooses the host. Redirects are refused and
environment proxies ignored, so a remote cannot send us anywhere else.
"""
import http.client
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlparse

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
SEP = "~"                              # fw id on the wire: <host>~<remote fw id>
MAX_STATE_BYTES = 64_000_000
CHUNK = 1 << 16
DEFAULTS = {"interval_s": 3.0, "timeout_s": 5.0}
PROXY_GET = frozenset((
    "/api/messages", "/api/triage", "/api/log", "/api/report", "/api/paths", "/api/history",
    "/api/history/report", "/api/history/artifact", "/api/history/build", "/api/history/compare",
    "/api/history/summary"))
NET_ERRORS = (OSError, ValueError, KeyError, TypeError, http.client.HTTPException)
PASS_HEADERS = ("Content-Type", "Content-Disposition", "Content-Length")


def check_name(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError("remote name must match [A-Za-z0-9_-]{1,32}: %r" % (name,))
    return name


def check_url(url):
    """Normalised scheme://host[:port]; http(s) only, no credentials, no path."""
    parts = urlparse(url) if isinstance(url, str) else None
    try:
        port = parts and parts.port
    except ValueError:
        port = None
        parts = None
    if (parts is None or parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError("remote url must be http(s)://host[:port] without credentials or path: %r" % (url,))
    host = "[%s]" % parts.hostname if ":" in parts.hostname else parts.hostname
    return "%s://%s%s" % (parts.scheme, host, ":%d" % port if port else "")


def redact(url):
    """scheme://host:port only (check_url already refused credentials, paths and queries)."""
    return check_url(url)


def parse_spec(text):
    """'name=url' from the command line -> (name, url)."""
    name, sep, url = str(text).partition("=")
    if not sep:
        raise ValueError("expected NAME=URL, got %r" % text)
    return check_name(name), check_url(url)


def settings(config):
    """(hosts [(name, url)], interval_s, timeout_s) from [remote]; ValueError on a bad entry."""
    section = (config.data.get("remote") if config is not None else None) or {}
    hosts = []
    for entry in section.get("hosts", ()):
        if not isinstance(entry, dict):
            raise ValueError("[remote] hosts entries must be tables with name and url")
        hosts.append((check_name(entry.get("name")), check_url(entry.get("url"))))
    return hosts, _positive(section, "interval_s"), _positive(section, "timeout_s")


def _positive(section, key):
    value = section.get(key, DEFAULTS[key])
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("[remote] %s must be a positive number" % key)
    return float(value)


def split_id(fw_id):
    """'<host>~<id>' -> (host, id); (None, fw_id) for a local id."""
    host, sep, local = (fw_id or "").partition(SEP)
    return (host, local) if sep else (None, fw_id)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _reason(exc):
    """Short error text that never contains a URL."""
    if isinstance(exc, urllib.error.HTTPError):
        return "HTTP %d" % exc.code
    if isinstance(exc, urllib.error.URLError):
        exc = exc.reason if isinstance(exc.reason, Exception) else exc
    if isinstance(exc, TimeoutError):
        return "timed out"
    if isinstance(exc, ConnectionRefusedError):
        return "connection refused"
    return (getattr(exc, "strerror", None) or exc.__class__.__name__)[:80]


class Remote:
    def __init__(self, name, url, timeout):
        self.name, self.url, self.timeout = name, url, timeout
        self.online = False
        self.last_ok = None
        self.error = "not contacted yet"
        self.version = None
        self.system = None
        self.firmwares = []            # last good snapshot, ids already namespaced
        self.fw_json = ""              # the same, as the inner part of a JSON array

    def status(self):
        return {"name": self.name, "url": redact(self.url), "online": self.online, "last_ok": self.last_ok,
                "error": self.error, "version": self.version, "system": self.system,
                "firmwares": len(self.firmwares)}

    def open(self, path, query=None, method="GET", timeout=None):
        """Raw response of the remote (an HTTPError for non-2xx); caller closes it."""
        url = self.url + path + ("?" + urlencode(query) if query else "")
        return _OPENER.open(urllib.request.Request(url, method=method), timeout=timeout or self.timeout)

    def get_json(self, path, query=None, limit=MAX_STATE_BYTES):
        with self.open(path, query) as resp:
            data = resp.read(limit + 1)
        if len(data) > limit:
            raise ValueError("response too large")
        return json.loads(data)

    def namespaced(self, fw):
        return {**fw, "id": self.name + SEP + fw["id"], "host": self.name}


class Remotes:
    """The configured remotes, one poller thread each so a slow host never delays another or the local tick."""

    def __init__(self, hosts, interval=DEFAULTS["interval_s"], timeout=DEFAULTS["timeout_s"], on_change=None):
        self.remotes = {name: Remote(name, url, timeout) for name, url in hosts}
        if len(self.remotes) != len(hosts):
            raise ValueError("duplicate remote name")
        self.interval, self.timeout = interval, timeout
        self.on_change = on_change or (lambda: None)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.threads = []

    def __bool__(self):
        return bool(self.remotes)

    def add(self, name, url):
        """Register a remote before start() (the --ssh tunnels know their port only at launch)."""
        if name in self.remotes:
            raise ValueError("duplicate remote name %r" % name)
        self.remotes[name] = Remote(check_name(name), check_url(url), self.timeout)

    def get(self, name):
        return self.remotes.get(name)

    def start(self):
        for remote in self.remotes.values():
            thread = threading.Thread(target=self._loop, args=(remote,), name="vmon-remote-" + remote.name, daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self):
        self.stop_event.set()

    def _loop(self, remote):
        while not self.stop_event.is_set():
            self.poll(remote)
            self.stop_event.wait(self.interval)

    def poll(self, remote):
        """One fetch; publishes (on_change) only when the merged view changed."""
        try:
            state = remote.get_json("/api/state")
            fws = state["firmwares"]
            if not isinstance(fws, list):
                raise ValueError("no firmwares list")
            namespaced = [remote.namespaced(f) for f in fws if isinstance(f, dict) and isinstance(f.get("id"), str)
                          and not f.get("host")]          # an aggregated firmware of that remote: no chains, no loops
            body = json.dumps(namespaced, separators=(",", ":"))[1:-1]
            error = None
        except NET_ERRORS as exc:     # URLError, timeouts, truncated or bad JSON, wrong shape
            namespaced, body, state, error = None, None, None, _reason(exc) if isinstance(exc, (OSError, http.client.HTTPException)) else "not a vmon state"
        with self.lock:
            before = (remote.online, remote.error, remote.fw_json)
            if error is None:
                remote.online, remote.error, remote.last_ok = True, None, time.time()
                remote.firmwares, remote.fw_json = namespaced, body
                remote.version, remote.system = state.get("version"), state.get("system")
            else:
                remote.online, remote.error = False, error      # keep the last snapshot, shown as stale
            changed = before != (remote.online, remote.error, remote.fw_json)
        if changed:
            self.on_change()

    def firmwares_json(self):
        with self.lock:
            return ",".join(r.fw_json for r in self.remotes.values() if r.fw_json)

    def statuses(self):
        with self.lock:
            return [r.status() for r in self.remotes.values()]

    # ---- request forwarding
    def forward(self, handler, route, query, method="GET"):
        """Answer `handler` from the remote named in the fw id (sent on with its own id); True when handled."""
        host, local = split_id(query.get("fw", [""])[0])
        remote = self.remotes.get(host)
        if remote is None:
            handler._error(404, "unknown firmware")
            return True
        params = [(k, split_id(v)[1]) if k in ("fw", "fw_b") else (k, v) for k, v in _pairs(query)]
        if route in REWRITTEN:
            status, data = self.fetch_json(host, route, params)
            handler._json(rewrite(route, data, host) if status == 200 else data, status)
            return True
        try:
            resp = remote.open(route, params, method)
        except urllib.error.HTTPError as err:          # the remote's own answer (404, 403...) is relayed
            if 300 <= err.code < 400:
                handler._error(502, "remote %s answered with a redirect" % remote.name)
                return True
            resp = err
        except NET_ERRORS as exc:
            handler._error(502, "remote %s unreachable: %s" % (remote.name, _reason(exc)))
            return True
        with resp:
            self._relay(handler, resp)
        return True

    @staticmethod
    def _relay(handler, resp):
        handler.send_response(resp.status)
        length = resp.headers.get("Content-Length")
        for name in PASS_HEADERS:
            if resp.headers.get(name):
                handler.send_header(name, resp.headers[name])
        handler.send_header("Cache-Control", "no-store")
        if length is None:
            handler.send_header("Connection", "close")
            handler.close_connection = True
        handler.end_headers()
        try:
            while chunk := resp.read(CHUNK):
                handler.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            handler.close_connection = True

    def fetch_json(self, host, path, query):
        """(status, parsed body) of a JSON route on one remote, for routes whose ids must be rewritten."""
        remote = self.remotes[host]
        try:
            return 200, remote.get_json(path, query)
        except urllib.error.HTTPError as err:
            if 300 <= err.code < 400:
                return 502, {"error": "remote %s answered with a redirect" % host}
            try:
                return err.code, json.loads(err.read(1 << 16))
            except ValueError:
                return err.code, {"error": "HTTP %d" % err.code}
        except NET_ERRORS as exc:
            return 502, {"error": "remote %s unreachable: %s" % (host, _reason(exc))}

    def history(self, limit):
        """Builds and firmwares of every remote, ids namespaced; plus the names that did not answer."""
        names = [n for n, r in self.remotes.items() if r.online]
        down = [n for n in self.remotes if n not in names]
        with ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
            results = list(pool.map(lambda n: self.fetch_json(n, "/api/history", [("limit", limit)]), names))
        builds, firmwares = [], []
        for name, (status, data) in zip(names, results):
            if status != 200 or not isinstance(data, dict):
                down.append(name)
                continue
            builds += [qualify_build(b, name) for b in data.get("builds", ())]
            firmwares += [qualify_firmware(f, name) for f in data.get("firmwares", ())]
        return builds, firmwares, down


REWRITTEN = frozenset(("/api/history", "/api/history/build", "/api/history/compare"))   # JSON that carries fw ids


def rewrite(route, data, host):
    """Namespace the firmware ids in a remote's history answer so the UI keeps addressing that host."""
    if route == "/api/history/compare" and isinstance(data, dict):
        return {**qualify_record(data, host), **{k: qualify_record(data[k], host) for k in ("a", "b") if k in data}}
    if route != "/api/history":
        return qualify_record(data, host)
    return {**data, "builds": [qualify_build(b, host) for b in data.get("builds", ())],
            "firmwares": [qualify_firmware(f, host) for f in data.get("firmwares", ())]}


def qualify_firmware(fw, host):
    return {**fw, "id": host + SEP + fw["id"], "host": host}


def qualify_build(build, host):
    return {**build, "fw_id": host + SEP + build["fw_id"], "host": host}


def qualify_record(data, host):
    """History build/compare result with its fw_id namespaced."""
    if isinstance(data, dict) and isinstance(data.get("fw_id"), str):
        return qualify_build(data, host)
    return data


def _pairs(query):
    return [(k, v) for k, vs in query.items() for v in vs]


def ssh_argv(target, local_port):
    """argv of `ssh -N -L <local_port>:127.0.0.1:<remote_port> user@host` for `user@host[:remote_port]`."""
    user_host, _, port = target.rpartition(":") if re.search(r":\d+$", target) else (target, "", "")
    if not re.fullmatch(r"[A-Za-z0-9._@-]+", user_host) or user_host.startswith("-"):
        raise ValueError("--ssh expects user@host[:port], got %r" % target)
    remote_port = int(port) if port else 8765
    if not 0 < remote_port < 65536:
        raise ValueError("bad remote port in %r" % target)
    return ["ssh.exe" if sys.platform == "win32" else "ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
            "-L", "%d:127.0.0.1:%d" % (local_port, remote_port), "--", user_host]
