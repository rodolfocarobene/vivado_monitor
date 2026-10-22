# vmon

[![CI](https://github.com/rodolfocarobene/vivado_monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/rodolfocarobene/vivado_monitor/actions/workflows/ci.yml)

Live web monitor for Xilinx Vivado builds: see which step and phase is running, what is still to come, timing, utilization and the warnings that matter, without opening a log file.

![Flow overview](docs/img/overview.png)

## Features

- **Auto-discovery** of running Vivado processes; one tab per firmware, finished runs stay visible.
- **Stage rail + drill-down**: synth, opt, place, phys_opt, route, bitstream stay pinned in a left rail with a *follow live* switch; the selected stage drills down on the right (on narrow windows the list becomes one tree, with the stage opening in place). Upcoming steps and phases come from a per-version phase catalog, with predicted phase numbers.
- **Timing you can trust**: intermediate and estimated values are shown as "not final"; red only when the final result fails. Missing hold metrics are carried forward and marked stale.
- **Utilization card**, parsing of intermediate reports (timing, DRC, power, route status, ...).
- **Worst timing paths** (setup/hold, logic vs route; expand one to see it as a chain of blocks: launch register, each cell and net with its delay and fanout, capture register), **per-clock history** across stages and builds with regressions highlighted.
- **Router convergence chart** (overlaps and slack per iteration, live) and an alert when the router stalls or diverges.
- **Alerts** with browser notifications, and an in-app event log. Optional server-side notifications (`notify-send`, ntfy, Slack, Matrix, JSON webhook) for crashes and timing failures, with no browser open; off by default, set up in `[notify]` (see [docs/configuration.md](docs/configuration.md)).
- **Suggested actions**: rule-based hints from `[[hints]]` in `flows.toml` (hold violated after route, route- or logic-dominated setup paths, high fanout, congestion, router stalled, out of memory, lost license, latches, ...), each with the evidence that fired it and commands you can copy; add your own or disable built-ins in your config (see [docs/configuration.md](docs/configuration.md#recommended-actions)).
- **Message triage**: severity, rules, keywords, rarity and "new since last build" scoring; pin or mute any message id.
- **Share message rules**: export your ★/mute rules to a file and import a teammate's (or your other machine's) with a preview of what changes first (merge or replace).
- **ETA with a confidence band**: per-step and per-phase durations learned from the last 20 builds of the same firmware (medians, p10-p90 range); steps never seen are sized from the catalog.
- **Congestion summary** for place and route: placer and router congestion levels per direction, final max congestion, router overlaps per iteration; a chip and an alert from level 5.
- **Build history page**: every finished build with date, duration, outcome, final WNS/WHS, utilization, and links to its reports and `.bit` (only while the files still belong to that build). Click a build to open its project in the standard view (it is loaded again if its tab was closed).
- **Compare two builds** of a firmware (pick two, or "vs previous"): timing and utilization deltas, step durations, new/removed/changed warnings.
- **Export a build summary** as Markdown or a self-contained HTML page (timing, utilization, top warnings, attempts, reports), or copy it to the clipboard.
- **Remote builds**: watch a build server through an SSH tunnel, or aggregate several machines in one UI; each remote firmware gets a host badge, and an unreachable host leaves its tabs visible but marked stale.
- **Build info**: part, board, strategies, directives; links to AMD documentation.
- **System CPU / RAM / swap** meters, sticky summary, folder explorer to add runs.
- **Keyboard**: `1`-`9` firmware tabs, `f`/`m`/`t` views, `j`/`k` stages, `n` next alert, `c` collapse all, `h` build history, `?` help; arrow keys on the tab strip.
- No AI: pure log parsing. Read-only. Python standard library only.

| Messages triage | Light theme, finished build | Narrow window |
|---|---|---|
| ![Messages](docs/img/messages.png) | ![Light theme](docs/img/light-theme.png) | <img src="docs/img/narrow.png" alt="Narrow window: stages as one tree" width="240"> |

| Build history | Congestion (route) |
|---|---|
| ![Build history](docs/img/history.png) | ![Congestion](docs/img/congestion.png) |

![Compare two builds](docs/img/compare.png)

![Suggested actions](docs/img/hints.png)

## Requirements

- Linux (reads `/proc`)
- Python 3.11 or newer (tests pass on 3.11 and 3.14)
- Vivado project-mode or non-project logs

Tested with Vivado 2023.2 on UltraScale+ RFSoC. Other versions or device families may need catalog entries (see [docs/catalog.md](docs/catalog.md)).

## Install

```sh
git clone <repo-url> vivado-monitor
cd vivado-monitor
python -m venv .venv
.venv/bin/pip install -e .      # provides the `vmon` command
```

Or run without installing: `python -m vmon`.

## Usage

```sh
vmon                          # watch all running Vivado builds, open the browser
vmon path/to/proj.runs        # also watch a .runs dir, .xpr or log file
vmon --port 9000 --no-browser
```

| Option | Default | Meaning |
|---|---|---|
| `paths` | | `.runs` dir, `.xpr`, run dir or log file to watch |
| `--port` | 8765 | Port to serve on; if busy, the next 10 ports are tried |
| `--host` | 127.0.0.1 | Bind address |
| `--interval` | 1.0 | Poll interval in seconds (also changeable in the UI) |
| `--no-browser` | | Do not open the browser |
| `--config FILE` | | Extra `flows.toml` merged over the defaults |
| `--remote NAME=URL` | | Aggregate another vmon, e.g. `buildsrv=http://127.0.0.1:9001` (repeatable; also `[remote]` in `flows.toml`) |
| `--ssh USER@HOST[:PORT]` | | Start `ssh -N -L` to the vmon on that host (default remote port 8765) and aggregate it; the tunnel ends with vmon |

If a vmon is already running on the port, the new command hands it your paths and opens the browser on it instead of starting a second server.

### Watching a build server

Run a normal vmon on the server (it binds to `127.0.0.1` there), forward its port, and aggregate it locally:

```sh
ssh -N -L 9001:127.0.0.1:8765 user@server &          # or let vmon do it: vmon --ssh user@server
vmon --remote buildsrv=http://127.0.0.1:9001
```

Remote firmwares appear as tabs with a host badge; the top bar shows one dot per remote (hover for the address and last update). Messages, logs, reports, timing paths, history, comparisons, summaries and downloads are fetched from the server on demand through your local vmon, which only ever talks to the hosts you configured. `Watch` and `Explore` still act on this machine. See [docs/configuration.md](docs/configuration.md#remote-vmon-instances).

Demo without Vivado: serve `vmon/static/` with any static server and open `index.html?mock=1`, for example `python -m http.server 8798 --bind 127.0.0.1 --directory vmon/static`.

## Configuration and extending

All Vivado-specific knowledge is data, not code.

- `vmon/flows.toml`: line rules, timing patterns, steps, report parsers, alert thresholds, docs links, message triage rules. Override with `~/.config/vmon/flows.toml`.
- `vmon/catalog/vivado_<ver>.toml`: steps, phases and tasks per Vivado version. Override or add under `~/.config/vmon/catalog/`.
- `~/.config/vmon/message_rules.json`: your message priorities (written by the UI).
- `~/.cache/vmon/`: recent paths, previous-build baselines, step durations.

See [docs/configuration.md](docs/configuration.md), [docs/catalog.md](docs/catalog.md) and [docs/architecture.md](docs/architecture.md).

## Safety

vmon is read-only on your build directories and never signals or kills processes. It binds to `127.0.0.1` by default. With remotes it makes HTTP requests to the configured URLs only (no redirects, no proxies). It writes only to `~/.cache/vmon/` and `~/.config/vmon/message_rules.json`.

## Development

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python tools/check_docs.py   # docs cover every API route, config section and CLI option
```

CI (GitHub Actions) runs the tests on Python 3.11–3.14, a server smoke test, frontend checks, a packaging check and the docs check on every push and pull request.

The architecture contract is in [SPEC.md](SPEC.md).

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Rodolfo Carobene.
