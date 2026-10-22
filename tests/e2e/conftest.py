"""Headless-browser fixtures. Skipped without playwright or its browser (VMON_E2E_REQUIRE=1 makes that an error)."""
import functools
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import FIXTURES, ROOT, build_runs, redirect_profile
from vmon.config import load_config
from vmon.expected import CatalogSet
from vmon.monitor import Monitor
from vmon.server import make_server

STATIC = ROOT / "vmon" / "static"
ARTIFACTS = Path(os.environ.get("VMON_E2E_ARTIFACTS", ROOT / ".tmp" / "e2e-artifacts"))
VIEWPORT = {"width": 1440, "height": 1000}
BROWSER = os.environ.get("VMON_E2E_BROWSER", "chromium")
REQUIRED = os.environ.get("VMON_E2E_REQUIRE") == "1"


def unavailable(reason):
    if REQUIRED:
        pytest.fail(reason)
    pytest.skip(reason)


def serve(handler, host_port=("127.0.0.1", 0)):
    server = ThreadingHTTPServer(host_port, handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture(scope="session")
def browser():
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        unavailable("playwright is not installed")
    with sync_playwright() as pw:
        try:
            instance = getattr(pw, BROWSER).launch()
        except (Error, AttributeError) as exc:
            unavailable("%s is not available: %s" % (BROWSER, str(exc).splitlines()[0]))
        yield instance
        instance.close()


@pytest.fixture(scope="session")
def mock_url():
    class Handler(SimpleHTTPRequestHandler):
        log_message = lambda *args: None            # noqa: E731
    server = serve(functools.partial(Handler, directory=str(STATIC)))
    yield "http://127.0.0.1:%d/index.html?mock=1" % server.server_address[1]
    server.shutdown()


@pytest.fixture(scope="session")
def real_url(tmp_path_factory):
    """The real server on a throw-away copy of the qick fixture (a finished build with reports)."""
    root = tmp_path_factory.mktemp("real")
    with pytest.MonkeyPatch.context() as patch:
        redirect_profile(patch, root / "home")
        qick = FIXTURES / "qick"
        steps = ["init_design", "opt_design", "place_design", "phys_opt_design", "route_design", "write_bitstream"]
        runs = build_runs(root, "top", "d_1_wrapper", qick / "d_1_wrapper.vdi", qick / "d_1_wrapper.tcl",
                          FIXTURES / "lockin" / "main_wrapper.vds", [(s, k) for s in steps for k in ("begin", "end")],
                          vivado_end=True)
        for rpt in qick.glob("*.rpt"):
            (runs / "impl_1" / rpt.name).write_bytes(rpt.read_bytes())
        config = load_config()
        CatalogSet().apply_to_config(config)
        monitor = Monitor(config, recent_file=root / "recent.json")
        monitor.discovery.discover = lambda: []        # ignore real Vivado processes
        monitor.add_path(str(runs))
        monitor.tick()
        server = make_server(monitor, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield "http://127.0.0.1:%d/" % server.server_address[1]
        server.shutdown()
        monitor.stop()


def is_noise(tab, msg):
    # the mock falls back to *_default.json after a 404 on purpose (a console message carries no URL to match)
    return "mock=1" in tab.url and msg.text.startswith("Failed to load resource") and "404" in msg.text


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    setattr(item, "rep_" + report.when, report)
    return report


@pytest.fixture()
def page(browser, request):
    """Fresh context per test; any JS error, page error or unhandled rejection fails the test."""
    context = browser.new_context(viewport=VIEWPORT)
    context.tracing.start(screenshots=True, snapshots=True)
    context.add_init_script("addEventListener('unhandledrejection', e => console.error('unhandled rejection: ' + e.reason))")
    context.set_default_timeout(10_000)       # shared CI runners are slow
    tab = context.new_page()
    errors = []
    tab.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" and not is_noise(tab, m) else None)
    tab.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
    yield tab
    failed = getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed
    if failed:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        name = request.node.name.replace("/", "_")
        tab.screenshot(path=str(ARTIFACTS / (name + ".png")))
        context.tracing.stop(path=str(ARTIFACTS / (name + ".zip")))
    else:
        context.tracing.stop()
    context.close()
    assert not errors, "JavaScript errors in the page:\n" + "\n".join(errors)
