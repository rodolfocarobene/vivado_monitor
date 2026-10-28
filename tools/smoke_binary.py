"""Smoke-test a built vmon executable: --help, --version, then serve a fixtures runs dir.

Usage: python tools/smoke_binary.py <binary> [expected-version]
Profile/cache dirs are redirected to a temp dir so the run never touches the real ones.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "qick"
TIMEOUT = 90


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fetch(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def wait_for(url, proc, check):
    deadline = time.time() + TIMEOUT
    last = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit("binary exited early with code %s" % proc.returncode)
        try:
            status, body = fetch(url)
            if status == 200 and check(body):
                return body
            last = "status %s, unexpected body" % status
        except OSError as exc:
            last = exc
        time.sleep(0.5)
    raise SystemExit("%s did not answer in %ds (%s)" % (url, TIMEOUT, last))


def main():
    binary = str(Path(sys.argv[1]).resolve())
    expected = sys.argv[2] if len(sys.argv) > 2 else None
    tmp = Path(tempfile.mkdtemp(prefix="vmon-smoke-"))
    env = dict(os.environ, HOME=str(tmp / "home"), USERPROFILE=str(tmp / "home"),
               XDG_CACHE_HOME=str(tmp / "cache"), XDG_CONFIG_HOME=str(tmp / "config"),
               XDG_DATA_HOME=str(tmp / "data"), XDG_STATE_HOME=str(tmp / "state"),
               APPDATA=str(tmp / "appdata"), LOCALAPPDATA=str(tmp / "localappdata"))
    for key in ("home", "cache", "config", "data", "state", "appdata", "localappdata"):
        (tmp / key).mkdir()
    try:
        out = subprocess.run([binary, "--help"], env=env, capture_output=True, text=True, timeout=TIMEOUT, check=True).stdout
        assert "--no-browser" in out, "--help lacks --no-browser"
        print("--help ok")
        out = subprocess.run([binary, "--version"], env=env, capture_output=True, text=True, timeout=TIMEOUT, check=True).stdout.strip()
        if expected:
            assert out == "vmon %s" % expected, "--version printed %r, expected %r" % (out, expected)
        print("--version ok: %s" % out)

        data = tmp / "data" / "proj"
        shutil.copytree(FIXTURE, data)
        port = free_port()
        proc = subprocess.Popen([binary, "--no-browser", "--port", str(port), str(data / "d_1_wrapper.vdi")],
                                env=env, stdin=subprocess.DEVNULL)
        try:
            base = "http://127.0.0.1:%d" % port
            body = wait_for(base + "/api/state", proc, lambda b: "firmwares" in b)
            state = json.loads(body)
            assert state["firmwares"] and state["firmwares"][0]["flows"], "fixture was not parsed"
            wait_for(base + "/", proc, lambda b: "<html" in b.lower())
            _, js = fetch(base + "/app.js")
            assert js.strip(), "app.js is empty"
            _, mock = fetch(base + "/mock/state.json")
            json.loads(mock)
            print("server ok on port %d" % port)
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("smoke test passed")


if __name__ == "__main__":
    main()
