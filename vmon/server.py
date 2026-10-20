"""HTTP server: static files + JSON API + SSE. Binds to localhost by default."""
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import browse as browse_mod

STATIC_DIR = Path(__file__).parent / "static"
HEARTBEAT_S = 15
MAX_REPORT_BYTES = 8_000_000


def make_server(monitor, host, port):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        # ---- helpers
        def _send(self, status, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, status=200):
            self._send(status, json.dumps(obj), "application/json")

        def _error(self, status, message):
            self._json({"error": message}, status)

        def _source(self, query):
            source = monitor.source_for(query.get("fw", [""])[0])
            if source is None:
                self._error(404, "unknown firmware")
            return source

        # ---- routes
        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            route = url.path
            if route == "/api/state":
                return self._send(200, monitor.state_json())
            if route == "/api/events":
                return self._events()
            if route == "/api/browse":
                with monitor.lock:
                    live = browse_mod.live_paths(monitor.firmwares.values())
                    recent = [p for _, p in monitor.watched.values()]
                try:
                    return self._json(browse_mod.browse(query.get("path", [""])[0], str(Path.home()), live, recent))
                except browse_mod.BrowseError as exc:
                    return self._error(exc.status, str(exc))
            if route in ("/api/messages", "/api/log", "/api/report", "/api/triage"):
                source = self._source(query)
                if source is None:
                    return
                node = query.get("node", [""])[0]
                sev = [s for s in query.get("sev", [""])[0].split(",") if s] or None
                with monitor.lock:
                    if route == "/api/messages":
                        msg_id = query.get("id", [None])[0]
                        result = source.messages(node, sev, _int(query, "limit", 500), msg_id)
                    elif route == "/api/triage":
                        result = monitor.triage(
                            query["fw"][0], node, sev, query.get("q", [""])[0] or None,
                            query.get("include_muted", ["0"])[0] in ("1", "true", "yes"),
                            _int(query, "limit", 500))
                    elif route == "/api/log":
                        around = query.get("around", [None])[0]
                        if around is not None:
                            result = self._around(source, query, node, around)
                        else:
                            result = source.log_excerpt(node, _int(query, "tail", 200))
                    else:
                        return self._report(source, query.get("path", [""])[0])
                if result is None:
                    return self._error(404, "unknown node or log")
                return self._json(result)
            return self._static(route)

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return None
            return data if isinstance(data, dict) else None

        def _around(self, source, query, node, around):
            try:
                line = int(around)
            except ValueError:
                return None
            path = query.get("log", [""])[0]
            if not path and node:
                path = source._log_of(node) or ""
            return source.log_around(path, line, _int(query, "context", 30))

        def do_POST(self):
            route = urlparse(self.path).path
            body = self._body()
            if route not in ("/api/watch", "/api/msgrule", "/api/settings"):
                return self._error(404, "not found")
            if body is None:
                return self._error(400, "bad body")
            if route == "/api/settings":
                try:
                    monitor.set_interval(body.get("interval"))
                except ValueError as exc:
                    return self._error(400, str(exc))
                return self._json({"interval": monitor.interval})
            if route == "/api/msgrule":
                try:
                    monitor.set_msgrule(body.get("id"), body.get("priority"))
                except ValueError as exc:
                    return self._error(400, str(exc))
                return self._json({"ok": True})
            path = body.get("path", "")
            fw_id = monitor.add_path(path) if isinstance(path, str) and path else None
            if fw_id is None:
                return self._error(400, "not a .runs dir, .xpr or log file")
            monitor.tick()
            self._json({"id": fw_id})

        def do_DELETE(self):
            url = urlparse(self.path)
            if url.path != "/api/firmware":
                return self._error(404, "not found")
            fw_id = parse_qs(url.query).get("fw", [""])[0]
            if monitor.forget(fw_id):
                monitor.tick()
                return self._json({"ok": True})
            self._error(409, "unknown or still running")

        def _report(self, source, path):
            real = os.path.realpath(path)
            if not (source.allowed_report(path) or source.allowed_report(real)):
                return self._error(403, "not a known report of this firmware")
            try:
                with open(real, "rb") as fh:
                    data = fh.read(MAX_REPORT_BYTES)
            except OSError:
                return self._error(404, "unreadable")
            self._send(200, data, "text/plain; charset=utf-8")

        def _static(self, route):
            rel = "index.html" if route in ("/", "") else route.lstrip("/")
            if rel.startswith("static/"):
                rel = rel[len("static/"):]
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() not in target.parents or not target.is_file():
                return self._send(404, "not found", "text/plain")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype)

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last = -1
            try:
                while not monitor._stop.is_set():
                    version = monitor.wait_for_change(last, HEARTBEAT_S)
                    if version != last:
                        last = version
                        self.wfile.write(("event: state\ndata: %s\n\n" % monitor.state_json()).encode())
                    else:
                        self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    return Server((host, port), Handler)


def _int(query, name, default):
    try:
        return int(query.get(name, [default])[0])
    except ValueError:
        return default
