import argparse
import json
import os
import sys
import urllib.request
import threading
import webbrowser

from .config import load_config
from .monitor import Monitor
from .server import make_server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="vmon", description="Live monitor for Vivado builds")
    parser.add_argument("paths", nargs="*", help=".runs dir, .xpr, run dir or log file to watch")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--config", help="extra flows.toml merged over the defaults")
    args = parser.parse_args(argv)

    if _is_vmon(args.host, args.port):
        return _reuse_running(args)

    monitor = Monitor(load_config(args.config), interval=args.interval)
    for path in args.paths:
        if monitor.add_path(path) is None:
            print("vmon: ignoring %s (not a .runs dir, .xpr or log file)" % path, file=sys.stderr)
    server = None
    for port in range(args.port, args.port + PORT_TRIES):
        try:
            server = make_server(monitor, args.host, port)
            break
        except OSError as exc:
            print("vmon: port %d busy (%s), trying %d" % (port, exc.strerror, port + 1), file=sys.stderr)
    if server is None:
        print("vmon: no free port in %d-%d" % (args.port, args.port + PORT_TRIES - 1), file=sys.stderr)
        return 1
    monitor.start()
    url = "http://%s:%d" % (args.host, server.server_address[1])
    print("vmon serving on %s  (Ctrl-C to stop)" % url, flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nvmon: stopping")
    finally:
        monitor.stop()
        server.server_close()
    return 0


PORT_TRIES = 10


def _is_vmon(host, port):
    try:
        with urllib.request.urlopen("http://%s:%d/api/state" % (host, port), timeout=1) as resp:
            return "firmwares" in json.load(resp)
    except (OSError, ValueError):
        return False


def _reuse_running(args):
    """Another vmon already owns the port: hand it our paths and open the browser on it."""
    url = "http://%s:%d" % (args.host, args.port)
    for path in args.paths:
        body = json.dumps({"path": os.path.abspath(path)}).encode()
        req = urllib.request.Request(url + "/api/watch", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=3).close()
        except OSError as exc:
            print("vmon: could not add %s: %s" % (path, exc), file=sys.stderr)
    print("vmon already running on %s" % url)
    if not args.no_browser:
        webbrowser.open(url)
    return 0
