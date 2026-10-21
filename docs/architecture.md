# Architecture

vmon is a stdlib-only Python backend that reads Vivado logs and marker files, builds a JSON model, and serves it with a vanilla JS single-page UI. It never writes to build directories and never signals processes.

## Modules

| Module | Role |
|---|---|
| `cli.py` | argparse entry point. Picks a free port, or hands paths to an already running vmon. |
| `config.py` | Loads `flows.toml` plus the optional `~/.config/vmon/flows.toml` (deep merge, user wins) and compiles regexes. |
| `flows.toml` | All Vivado-specific knowledge: line rules, timing patterns, steps, report registry, alerts, docs links, message triage rules. |
| `catalog/` | One TOML per Vivado version describing every step, phase and task (see [catalog.md](catalog.md)). |
| `discovery.py` | Finds Vivado processes via `/proc` and groups them into firmwares. |
| `logtail.py` | Incremental file reader (offset + inode, handles truncation and rotation). |
| `logparse.py` | Streaming parser: log lines to sections, phases, tasks, messages and timing. |
| `project.py` | Builds a firmware's flow from a `.runs` directory (marker files, run tcl, logs, reports). |
| `expected.py` | Merges catalog placeholders (upcoming steps/phases, predicted numbers, weights) into the seen nodes. |
| `timing_paths.py`, `clocks.py`, `convergence.py` | Worst-path parser for timing reports (streamed), per-clock history across stages and builds, router overlap trend. |
| `reports.py` | Parses utilization, timing summary, DRC/methodology, power, route status and other reports. |
| `alerts.py`, `triage.py`, `eta.py`, `info.py`, `docs.py` | Alerts, message scoring and baselines, ETA, build info, documentation links. |
| `sysstats.py`, `browse.py` | System CPU/RAM/swap from `/proc`; read-only directory listing for the folder explorer. |
| `monitor.py` | Background thread: each tick discover, update parsers, publish state. |
| `server.py` | `ThreadingHTTPServer`: static files, JSON API and Server-Sent Events. |
| `static/` | `index.html`, `app.js`, `style.css` (no build step). `static/mock/` holds the demo data used by `?mock=1`. |

## Data flow

```
/proc  ->  discovery  ->  Group (project .runs dir or standalone log)
                              |
 .runs dir markers, run tcl,  v
 *.vds / *.vdi logs, reports -> project + logparse + reports -> expected (catalog) -> model
                                                                   |
                          alerts / triage / eta / info  <----------+
                                                                   v
                                      monitor tick -> State JSON -> server -> SSE -> UI
```

Everything read is read-only. The only files vmon writes are under `~/.cache/vmon/` and `~/.config/vmon/message_rules.json` (your message priority overrides).

## Discovery

- Scans `/proc/*/comm` for `vivado`, then reads `cmdline`, `cwd` and the parent pid.
- If the cwd is `<X>.runs/<run>/`, the process belongs to project `<X>.runs`.
- Otherwise it looks for `-log <file>` (or `vivado.log` in the cwd) and scans it for `open_project <path>.xpr`. A launcher process is tied to a project through its Vivado descendants.
- With no project found, the log becomes a standalone "log" firmware (non-project flow).
- Paths given on the command line or through the UI are watched too, and the last 20 are remembered in `~/.cache/vmon/recent.json` so finished runs reappear after a restart.

## Project-mode sources

For a run directory `R`:

- `R/.<step>.begin.rst`, `.end.rst`, `.error.rst`: step status and start/end time (mtime).
- `R/<top>.tcl`: `start_step <name>` lines give the planned step list (only enabled steps).
- `R/gen_run.xml`, `runme.log`; main log is `<top>.vds` (synth) or `<top>.vdi` (impl).
- `<X>.runs/.jobs/vrs_config_<N>.xml` with the highest N lists the runs of the current launch.
- Reports such as `<top>_timing_summary_routed.rpt`; a report older than its step's begin marker is flagged stale and never raises alerts.

Flow layout: a "Synthesis" stage (out-of-context IP runs collapsed into a sub-group, then the top synth run), followed by each implementation step in tcl order. Steps not yet started are shown as pending placeholders from the catalog.

## Incremental parsing

Each log is parsed once; later ticks read only the appended bytes. A changed inode or a shrinking file restarts from offset 0 (run reset). Logs of 100k+ lines are never re-read per tick. The state JSON excludes message lists, which are served on demand.

Parsing is driven by regex rules in `flows.toml` (`[rules.*]`), with cheap prefix/substring pre-filters. Phases are matched to the catalog by name, not number, because numbers shift with directive and device.

## Timing

Timing lines are matched by `[timing.patterns.*]`. A value of `N/A` becomes null. Missing hold metrics (WHS/THS) are carried forward from the previous known value and listed in `Timing.carried`. A result is `final` only for the route/post-route report or any timing once route is done; only a final violation is an error, earlier ones are warnings.

## JSON API

| Endpoint | Returns |
|---|---|
| `GET /api/state` | Full state: system stats, settings, firmwares (flow tree, counts, timing, utilization, ETA, info, alerts, events). |
| `GET /api/events` | SSE stream; a `state` event whenever anything changes, heartbeat every 15 s. |
| `GET /api/messages?fw=&node=&id=&sev=&limit=` | Message groups and instances for a step/phase (or whole firmware). |
| `GET /api/triage?fw=&node=&sev=&q=&include_muted=&limit=` | Scored message groups, with `new`/`delta` against the previous build. |
| `GET /api/log?fw=&node=&tail=` or `&log=&around=&context=` | Raw log excerpt for a node, or around a line. |
| `GET /api/report?fw=&path=` | Raw text of a report (only paths listed in the model). |
| `GET /api/paths?fw=&path=&type=&only_failing=` | Worst setup/hold paths (max 200, worst first) of a timing_summary report: `{path, paths, counts}`. `type=setup\|hold`, `only_failing=1`; same path validation as `/api/report`. |
| `GET /api/browse?path=` | Read-only directory listing for the explorer (skips `/proc`, `/sys`, `/dev`). |
| `POST /api/watch` `{"path": ...}` | Add a `.runs` dir, `.xpr` or log to watch. |
| `POST /api/msgrule` `{"id": ..., "priority": ...}` | Set or clear a message priority override. |
| `POST /api/settings` `{"interval": 0.5..60}` | Change the poll interval. |
| `DELETE /api/firmware?fw=` | Forget a finished firmware (nothing is deleted on disk). |

Top-level model: `State` contains `Firmware` objects; each has `flows` of `Node` trees (`group`, `run`, `step`, `command`, `phase`, `task`) with `status`, `counts`, `timing`, `reports`, `alerts`, `expected`/`optional` flags and predicted phase numbers. The full field-level contract is in [`SPEC.md`](../SPEC.md).

## Message triage

`score = severity base + priority bonus + keyword bonus + rarity bonus + novelty bonus` (weights in `[messages.scoring]`). Rules and keywords come from `flows.toml`; per-id overrides from `~/.config/vmon/message_rules.json`. When a build finishes, its `{id: count}` map is stored in `~/.cache/vmon/msgs/<fw_id>.json` and becomes the baseline for the next build's "new since last build".

## ETA

For a running build, per-step durations of the last completed build of the same firmware (`~/.cache/vmon/durations/`) are summed for pending steps, plus the remainder of the current step. Without a previous build it falls back to catalog weights scaled by progress (low confidence).

## Timing insights

- **Worst paths**: the path sections of a `timing_summary` report are streamed line by line once per (mtime, size) change; only the worst 100 setup + 100 hold paths are kept (`[timing_paths]`). The report summary carries the 8 worst plus `path_counts`; the full list comes from `/api/paths`.
- **Per-clock history**: per-clock values come from the Intra Clock Table of each timing report (`Firmware.clock_history.stages`). When a build finishes, its final values are stored in `~/.cache/vmon/timing/<fw_id>.json` (last 20 builds, keyed by start time; finished builds not yet stored are recorded at startup).
- **Router convergence**: the parser records every `Number of Nodes with overlaps` value and the following Intermediate Timing Summary per router iteration (`Node.convergence`). The trend (converging / stalled / diverging) and the `route_not_converging` alert use `[convergence]`; the alert is raised for live attempts only.
