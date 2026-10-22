"""Fail when the docs drift from the code: API routes, config sections, CLI options and links.

Run from the repository root: python tools/check_docs.py
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def read(rel):
    return (ROOT / rel).read_text()


def api_routes():
    return sorted(set(re.findall(r"/api/[a-z_]+", read("vmon/server.py"))))


def config_sections():
    with open(ROOT / "vmon/flows.toml", "rb") as fh:
        return sorted(tomllib.load(fh))


def cli_options():
    out = "".join(subprocess.run([sys.executable, "-m", "vmon", *args, "--help"], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout
                  for args in ([], ["status"]))
    return sorted(set(re.findall(r"--[a-z][a-z-]*", out)) - {"--help"})


def broken_links():
    broken = []
    for doc in DOC_FILES:
        for target in re.findall(r"\]\(([^)\s]+)\)", doc.read_text()):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if not (doc.parent / path).exists():
                broken.append("%s -> %s" % (doc.relative_to(ROOT), target))
    return broken


def main():
    errors = []
    architecture = read("docs/architecture.md")
    errors += ["docs/architecture.md: API route %s is not documented" % r
               for r in api_routes() if r not in architecture]
    configuration = read("docs/configuration.md")
    errors += ["docs/configuration.md: config section [%s] is not documented" % s
               for s in config_sections()
               if "[%s]" % s not in configuration and "[%s." % s not in configuration]
    readme = read("README.md")
    errors += ["README.md: CLI option %s is not documented" % o
               for o in cli_options() if "`%s" % o not in readme]
    errors += ["broken link: %s" % b for b in broken_links()]
    for err in errors:
        print("::error::%s" % err)
    print("docs check: %d problem(s)" % len(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
