# Releasing

vmon is released from GitHub. Publishing a release builds the executables and attaches them to it.

## Cut a release

1. Bump the version in **both** `pyproject.toml` (`version`) and `vmon/__init__.py` (`__version__`).
2. Merge that to `main`.
3. Tag it `vX.Y.Z` (for example `v0.2.0`) and publish a GitHub release for that tag.
4. The `Release` workflow runs. It first checks that the tag, `pyproject.toml` and `vmon.__version__` agree, and fails with a message naming the mismatch if not. Fix the version, move the tag and publish again.

The workflow attaches to the release:

- `vmon-<version>-linux-x86_64`: single-file executable, built on Ubuntu 22.04 (older glibc, so it runs on most current distributions).
- `vmon-<version>-windows-x86_64.exe`: single-file executable for Windows.
- the wheel and the sdist (`vmon-<version>-py3-none-any.whl`, `vmon-<version>.tar.gz`).
- `SHA256SUMS`: checksums of all of the above.

`<version>` is the tag without the leading `v`.

Each executable is smoke-tested before it is uploaded: `--help`, `--version`, then it serves a copy of the test fixtures on a free port and `/api/state` and `/` must answer. Pull requests that touch the workflow, `tools/vmon.spec`, `tools/vmon_entry.py`, `tools/smoke_binary.py`, `requirements-release.txt` or `pyproject.toml` run the same build and tests without uploading anything, and the workflow can also be started by hand (build only).

PyInstaller is pinned in `requirements-release.txt`; bump it there on purpose and let the PR build prove it works.

## Run the binaries

Linux:

```
chmod +x vmon-<version>-linux-x86_64
./vmon-<version>-linux-x86_64 /path/to/proj.runs
```

Windows: run `vmon-<version>-windows-x86_64.exe` from a terminal. The executable is not code-signed, so SmartScreen may show "Windows protected your PC": choose *More info*, then *Run anyway*. Compare the file with `SHA256SUMS` first if you want to be sure it is the released one.

Then open http://localhost:8765. The first start of a one-file executable takes a moment because it unpacks itself to a temporary folder.

## Why there is no macOS binary

vmon finds running Vivado processes through a platform backend (`/proc` on Linux, the Windows API on Windows). There is no macOS backend, so a macOS build would not discover builds, and it is not published.
