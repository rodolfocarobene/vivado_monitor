"""Notifications outside the browser: desktop (notify-send), ntfy, Slack, Matrix, generic webhook.

Settings come from [notify] in flows.toml. Delivery runs on its own thread so a slow or dead
endpoint never stalls the monitor tick. URLs and tokens never appear in logs, errors or API
output: only scheme://host is shown, and error texts are built from the failure kind, not from
the exception text.
"""
import collections
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote, urlparse

LEVELS = {"info": 0, "warning": 1, "error": 2}
CODE_ALIAS = {"utilization": "util_high"}
QUEUE_MAX = 200
SEEN_MAX = 1000
WINDOW_S = 60
TAGS = {"info": "white_check_mark", "warning": "warning", "error": "rotating_light"}


def _latin1(text):
    """HTTP header values must be latin-1 and single-line."""
    return " ".join(text.split()).encode("latin-1", "replace").decode("latin-1")


def redact_url(url):
    """scheme://host[:port] only: paths, queries and credentials can carry the secret."""
    try:
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return "invalid URL"
        host = "[%s]" % parts.hostname if ":" in parts.hostname else parts.hostname
        return "%s://%s%s" % (parts.scheme, host, ":%d" % parts.port if parts.port else "")
    except ValueError:
        return "invalid URL"


def describe_error(exc):
    """A short, secret-free reason for a failed delivery."""
    if isinstance(exc, urllib.error.HTTPError):
        return "HTTP %d" % exc.code
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "timed out"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "timed out"
        return "connection failed (%s)" % (reason.strerror or "error") if isinstance(reason, OSError) else "invalid URL"
    if isinstance(exc, FileNotFoundError):
        return "command not found"
    if isinstance(exc, PermissionError):
        return "command not executable"
    if isinstance(exc, ValueError):
        return "invalid URL"
    if isinstance(exc, OSError):
        return "connection failed (%s)" % (exc.strerror or "error")
    return type(exc).__name__


class Channel:
    name = ""
    label = ""

    def __init__(self, spec, notifier):
        self.spec = spec if isinstance(spec, dict) else {}
        self.n = notifier
        self.enabled = bool(self.spec.get("enabled", False))

    def value(self, key):
        """A setting that may come from an environment variable (`<key>_env`)."""
        direct = self.spec.get(key)
        if direct:
            return str(direct)
        var = self.spec.get(key + "_env")
        return self.n.env.get(var, "") if var else ""

    def secrets(self):
        return []

    def configured(self):
        return False

    def target(self):
        return ""

    def send(self, msg):
        raise NotImplementedError


class HttpChannel(Channel):
    def request(self, msg):
        """(method, url, headers, body bytes)."""
        raise NotImplementedError

    def send(self, msg):
        method, url, headers, body = self.request(msg)
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        with self.n.opener(req, timeout=self.n.timeout) as resp:
            resp.read(1024)


def _text(msg):
    return "\n".join(x for x in (msg["head"], msg["body"], msg["project"]) if x)


class Desktop(Channel):
    name, label = "desktop", "Desktop"

    def argv(self):
        cmd = self.spec.get("command") or "notify-send"
        return [str(c) for c in cmd] if isinstance(cmd, list) else [str(cmd)]

    def configured(self):
        argv = self.argv()
        return bool(argv) and shutil.which(argv[0]) is not None

    def target(self):
        return os.path.basename(self.argv()[0]) if self.argv() else ""

    def send(self, msg):
        urgency = self.spec.get("urgency_error", "critical") if msg["level"] == "error" else "normal"
        body = "\n".join(x for x in (msg["body"], msg["project"]) if x)
        argv = self.argv() + ["-u", urgency, "-a", "vmon", "--", msg["head"], body]
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=self.n.timeout, shell=False)
        if done.returncode:
            raise RuntimeError("exit %d" % done.returncode)


class Ntfy(HttpChannel):
    name, label = "ntfy", "ntfy"

    def secrets(self):
        return [self.value("url"), self.value("token")]

    def configured(self):
        return bool(self.value("url"))

    def target(self):
        return redact_url(self.value("url")) if self.value("url") else ""

    def request(self, msg):
        priority = self.spec.get("priority_" + msg["level"]) or "default"
        headers = {"Title": _latin1(msg["head"]), "Priority": str(priority), "Tags": TAGS.get(msg["level"], "bell"),
                   "Content-Type": "text/plain; charset=utf-8"}
        if self.value("token"):
            headers["Authorization"] = "Bearer " + self.value("token")
        body = "\n".join(x for x in (msg["body"], msg["project"]) if x) or msg["head"]
        return "POST", self.value("url"), headers, body.encode()


class Slack(HttpChannel):
    name, label = "slack", "Slack"

    def secrets(self):
        return [self.value("webhook_url")]

    def configured(self):
        return bool(self.value("webhook_url"))

    def target(self):
        return redact_url(self.value("webhook_url")) if self.value("webhook_url") else ""

    def request(self, msg):
        text = "*%s*\n%s" % (msg["head"], "\n".join(x for x in (msg["body"], msg["project"]) if x))
        return "POST", self.value("webhook_url"), {"Content-Type": "application/json"}, json.dumps({"text": text.strip()}).encode()


class Matrix(HttpChannel):
    name, label = "matrix", "Matrix"

    def secrets(self):
        return [self.value("access_token")]

    def configured(self):
        return bool(self.value("homeserver") and self.value("room_id") and self.value("access_token"))

    def target(self):
        return redact_url(self.value("homeserver")) if self.value("homeserver") else ""

    def request(self, msg):
        room = quote(self.value("room_id"), safe="")
        url = "%s/_matrix/client/v3/rooms/%s/send/m.room.message/%s" % (
            self.value("homeserver").rstrip("/"), room, "vmon-%s" % uuid.uuid4().hex)
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.value("access_token")}
        return "PUT", url, headers, json.dumps({"msgtype": "m.text", "body": _text(msg)}).encode()


class Webhook(HttpChannel):
    name, label = "webhook", "Webhook"
    FIELDS = ("firmware", "fw_id", "kind", "code", "level", "title", "body", "t", "project")

    def secrets(self):
        return [self.value("url")]

    def configured(self):
        return bool(self.value("url"))

    def target(self):
        return redact_url(self.value("url")) if self.value("url") else ""

    def request(self, msg):
        payload = {k: msg[k] for k in self.FIELDS}
        return "POST", self.value("url"), {"Content-Type": "application/json"}, json.dumps(payload).encode()


CHANNELS = (Desktop, Ntfy, Slack, Matrix, Webhook)


def step_label(fw, node_id):
    """Label of the step that owns `node_id` (the browser's eventBody does the same)."""
    stack = [(n, None) for flow in fw.flows for n in flow.stages]
    while stack:
        node, step = stack.pop()
        step = node.label if node.kind == "step" else step
        if node.id == node_id:
            return step or node.label
        stack.extend((c, step) for c in node.children)
    return ""


def event_body(fw, event):
    step = step_label(fw, event.get("node_id")) if event.get("node_id") else ""
    text = event.get("message") or ""
    return "%s: %s" % (step, text) if step and not text.startswith(step) else text


class Notifier:
    def __init__(self, spec, env=None, opener=None, clock=time.time):
        spec = spec if isinstance(spec, dict) else {}
        self.env = os.environ if env is None else env
        self.opener = opener or urllib.request.urlopen
        self.clock = clock
        self.enabled = bool(spec.get("enabled", False))
        self.kinds = set(spec.get("kinds") or [])
        self.codes = set(spec.get("codes") or [])
        self.min_level = LEVELS.get(spec.get("min_level", "warning"), 1)
        self.timeout = float(spec.get("timeout_s", 5))
        self.max_per_minute = int(spec.get("max_per_minute", 20))
        self.prefix = str(spec.get("title_prefix", "vmon"))
        self.channels = [cls(spec.get(cls.name), self) for cls in CHANNELS]
        self.t0 = clock()
        self._seen = collections.OrderedDict()
        self._sent = collections.deque()       # delivery times inside the rate window
        self._overflow = 0
        self._errors = {}                      # channel -> last error text, cleared by a success
        self._last_error = None
        self._queue = queue.Queue(QUEUE_MAX)
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ filtering
    def wanted(self, event):
        kind = event.get("kind")
        if kind == "alert":
            code = CODE_ALIAS.get(event.get("code"), event.get("code"))
            return code in self.codes and LEVELS.get(event.get("level"), 0) >= self.min_level
        return kind in self.kinds

    def active(self):
        return [c for c in self.channels if self.enabled and c.enabled]

    def submit(self, fw, event):
        """Queue a new monitor event; never raises and never blocks."""
        try:
            if not self.enabled or not self.active() or event["t"] < self.t0 or not self.wanted(event):
                return False
            key = (fw.id, event["t"], event["kind"], event.get("node_id"), event.get("code"), event.get("title"))
            with self._lock:
                if key in self._seen:
                    return False
                self._seen[key] = None
                while len(self._seen) > SEEN_MAX:
                    self._seen.popitem(last=False)
            msg = self._message(fw.name, fw.id, event, event_body(fw, event), fw.path)
            self._start()
            try:
                self._queue.put_nowait(msg)
            except queue.Full:
                with self._lock:
                    self._overflow += 1
            return True
        except Exception as exc:
            print("vmon: notify submit failed: %s" % type(exc).__name__, file=sys.stderr)
            return False

    def _message(self, firmware, fw_id, event, body, project):
        title = event.get("title") or ""
        head = "%s \u00b7 %s" % (self.prefix, title) if self.prefix else title
        return {"firmware": firmware, "fw_id": fw_id, "kind": event.get("kind"), "code": event.get("code"),
                "level": event.get("level") or "info", "title": title, "head": head, "body": body,
                "t": event.get("t"), "project": project or ""}

    # ------------------------------------------------------------------ delivery
    def _start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="vmon-notify", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=1.0)
            except queue.Empty:
                self._flush_overflow()
                continue
            try:
                self.handle(msg)
            except Exception as exc:       # the worker must outlive any single message
                print("vmon: notify failed: %s" % type(exc).__name__, file=sys.stderr)
            finally:
                self._queue.task_done()

    def wait_idle(self, timeout=5.0):
        end = time.time() + timeout
        while self._queue.unfinished_tasks and time.time() < end:
            time.sleep(0.01)
        return not self._queue.unfinished_tasks

    def _allow(self):
        now = self.clock()
        while self._sent and now - self._sent[0] >= WINDOW_S:
            self._sent.popleft()
        if self.max_per_minute > 0 and len(self._sent) >= self.max_per_minute:
            return False
        self._sent.append(now)
        return True

    def handle(self, msg):
        if not self._allow():
            self._overflow += 1
            return
        self._flush_overflow()
        self._deliver(msg)

    def _flush_overflow(self):
        if not self._overflow or not self._allow():
            return
        count, self._overflow = self._overflow, 0
        note = {"title": "%d more events" % count, "kind": "summary", "level": "info", "t": self.clock()}
        msg = self._message("vmon", "", note, "Rate limit of %d per minute reached; open vmon for details." % self.max_per_minute, "")
        self._deliver(msg)

    def _deliver(self, msg):
        return [self._send_one(ch, msg) for ch in self.active()]

    def _send_one(self, channel, msg):
        if not channel.configured():
            self._fail(channel, "not configured")
            return {"name": channel.name, "ok": False, "error": "not configured"}
        try:
            channel.send(msg)
        except Exception as exc:
            text = self._scrub(channel, describe_error(exc) if not isinstance(exc, RuntimeError) else str(exc))
            self._fail(channel, text)
            return {"name": channel.name, "ok": False, "error": text}
        self._errors.pop(channel.name, None)
        return {"name": channel.name, "ok": True}

    def _scrub(self, channel, text):
        for secret in channel.secrets():
            if secret:
                text = text.replace(secret, "***")
        return text

    def _fail(self, channel, text):
        if self._errors.get(channel.name) != text:      # once per distinct failure, not per event
            print("vmon: notify %s failed: %s" % (channel.name, text), file=sys.stderr)
        self._errors[channel.name] = text
        self._last_error = {"channel": channel.name, "error": text, "t": self.clock()}

    def test(self):
        """Send a test message to every active channel, synchronously."""
        note = {"title": "Test notification", "kind": "test", "level": "info", "t": self.clock()}
        msg = self._message("vmon", "", note, "If you can read this, notifications work.", "")
        return self._deliver(msg)

    # ------------------------------------------------------------------ API
    def status(self):
        channels = [{"name": c.name, "label": c.label, "enabled": self.enabled and c.enabled,
                     "configured": c.configured(), "target": c.target(), "error": self._errors.get(c.name)}
                    for c in self.channels]
        return {"enabled": self.enabled, "channels": channels, "kinds": sorted(self.kinds), "codes": sorted(self.codes),
                "min_level": next(k for k, v in LEVELS.items() if v == self.min_level), "last_error": self._last_error}

    def stop(self):
        self._stop.set()
