# vmon

Live web monitor for Xilinx Vivado builds: see which step and phase is running, what is still to come, timing, utilization and the warnings that matter, without opening a log file.

![Flow overview](docs/img/overview.png)

## Features

- **Auto-discovery** of running Vivado processes; one tab per firmware, finished runs stay visible.
- **Master-detail drill-down flow**: synth, opt, place, phys_opt, route, bitstream. Upcoming steps and phases come from a per-version phase catalog, with predicted phase numbers.
- **Timing you can trust**: intermediate and estimated values are shown as "not final"; red only when the final result fails. Missing hold metrics are carried forward and marked stale.
- **Utilization card**, parsing of intermediate reports (timing, DRC, power, route status, ...).
- **Alerts** with browser notifications, and an in-app event log.
- **Message triage**: severity, rules, keywords, rarity and "new since last build" scoring; pin or mute any message id.
- **ETA** from the previous build of the same firmware.
- **Build info**: part, board, strategies, directives; links to AMD documentation.
- **System CPU / RAM / swap** meters, sticky summary, folder explorer to add runs.
- No AI: pure log parsing. Read-only. Python standard library only.

| Messages triage | Light theme, finished build |
|---|---|
| ![Messages](docs/img/messages.png) | ![Light theme](docs/img/light-theme.png) |

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

If a vmon is already running on the port, the new command hands it your paths and opens the browser on it instead of starting a second server.

Demo without Vivado: serve `vmon/static/` with any static server and open `index.html?mock=1`, for example `python -m http.server 8798 --bind 127.0.0.1 --directory vmon/static`.

## Configuration and extending

All Vivado-specific knowledge is data, not code.

- `vmon/flows.toml`: line rules, timing patterns, steps, report parsers, alert thresholds, docs links, message triage rules. Override with `~/.config/vmon/flows.toml`.
- `vmon/catalog/vivado_<ver>.toml`: steps, phases and tasks per Vivado version. Override or add under `~/.config/vmon/catalog/`.
- `~/.config/vmon/message_rules.json`: your message priorities (written by the UI).
- `~/.cache/vmon/`: recent paths, previous-build baselines, step durations.

See [docs/configuration.md](docs/configuration.md), [docs/catalog.md](docs/catalog.md) and [docs/architecture.md](docs/architecture.md).

## Safety

vmon is read-only on your build directories and never signals or kills processes. It binds to `127.0.0.1` by default. It writes only to `~/.cache/vmon/` and `~/.config/vmon/message_rules.json`.

## Development

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The architecture contract is in [SPEC.md](SPEC.md).

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Rodolfo Carobene.
