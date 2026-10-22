"""`vmon status`: one-shot (or --watch) text summary of the builds, for quick checks over SSH."""
import argparse
import json
import shutil
import sys
import time

from . import term
from .source import Source

CLEAR = "\x1b[H\x1b[2J"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="vmon status", description="Print the state of the builds in the terminal",
        epilog="exit codes: 0 nothing failed, 1 a build failed or finished with final timing not met, "
               "2 usage or config error, 3 nothing to show")
    parser.add_argument("paths", nargs="*", help=".runs dir, .xpr, run dir or log file (also filters a running vmon)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--config", help="extra flows.toml merged over the defaults (local mode)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the table")
    parser.add_argument("--watch", type=float, metavar="SECONDS", help="refresh every SECONDS until Ctrl-C")
    parser.add_argument("--no-color", action="store_true", help="never use ANSI colors")
    return parser


def render(state, as_json, color, width, now=None):
    if as_json:
        return json.dumps(term.json_state(state), indent=2)
    return "\n".join(term.to_text(line, color) for line in term.status_lines(state, width, now))


def run(argv, stdout=None):
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    if args.watch is not None and args.watch <= 0:
        print("vmon status: --watch must be positive", file=sys.stderr)
        return 2
    color = term.color_enabled(stdout, args.no_color) and term.enable_vt() and not args.json
    try:
        source = Source(args.host, args.port, args.paths, args.config, live=False)
    except (ValueError, OSError) as exc:
        print("vmon status: %s" % exc, file=sys.stderr)
        return 2
    for warning in source.warnings:
        print("vmon: %s" % warning, file=sys.stderr)
    code = 3
    try:
        while True:
            state = source.state()
            if state is None:
                print("vmon status: %s did not answer" % source.label, file=sys.stderr)
                state = {"firmwares": []}
            code = term.exit_code(state)
            text = render(state, args.json, color, shutil.get_terminal_size((100, 24)).columns)
            if args.watch is not None and stdout.isatty() and not args.json:
                stdout.write(CLEAR)
            print(text, file=stdout, flush=True)
            if code == 3 and not args.json:
                print("vmon status: nothing found (%s, no Vivado process, no path watched)" % source.label,
                      file=sys.stderr)
            if args.watch is None:
                return code
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return code
    finally:
        source.close()
