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
| `timing_paths.py`, `path_table.py`, `clocks.py`, `convergence.py`, `congestion.py` | Worst-path parser for timing reports (streamed), per-clock history across stages and builds, router overlap trend, congestion level summary. |
| `reports.py` | Parses utilization, timing summary, DRC/methodology, power, route status and other reports. |
| `summary.py` | Renders a recorded build to Markdown or a self-contained HTML page. |
| `history.py` | Build history store and records (`~/.cache/vmon/history/`), artifact validation for the history API. |
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
| `GET /api/history?fw=&limit=` | Finished builds, newest first: `{"builds": [record], "firmwares": [{id, name}]}`. Without `fw`, all firmwares in the history dir (also ones not currently loaded). Each artifact carries `current`. |
| `GET /api/history/build?fw=&build=` | The full record of one build (the list omits `messages`, `phases`, `timing_clocks`); 404 for an unknown firmware or build. |
| `GET /api/history/compare?fw=&a=&b=` | Diff of two builds of one firmware (`a` base/older, `b` newer): timing, utilization, step durations, messages. 404 for an unknown firmware or build, 400 when `a` equals `b`. |
| `GET /api/history/summary?fw=&build=&format=md\|html&download=1` | Printable summary of one recorded build: `text/markdown` (default) or `text/html`; `download=1` adds `Content-Disposition: attachment; filename="<firmware>_<YYYY-MM-DD_HHMM>_summary.<ext>"`. 404 for an unknown firmware or build, 400 for another format. |
| `GET /api/history/report?fw=&build=&path=` | Text of a recorded report. `path` must be an artifact of that build and still current (same mtime and size); else 404 (not listed) or 410 (replaced by a later build). |
| `GET /api/history/artifact?fw=&build=&path=` | Streams a recorded artifact (the bitstream) as `application/octet-stream` with `Content-Disposition: attachment`; same validation as the report route. |
| `GET /api/notify` | Server-side notification status: `{enabled, channels: [{name, label, enabled, configured, target, error}], kinds, codes, min_level, last_error}`. `target` is scheme://host only; errors never contain URLs or tokens. |
| `POST /api/notify/test` | Sends a test message to every enabled channel (synchronously) and returns `{"results": [{name, ok, error?}]}`; `[]` when nothing is enabled. |
| `GET /api/browse?path=` | Read-only directory listing for the explorer (skips `/proc`, `/sys`, `/dev`). |
| `POST /api/watch` `{"path": ...}` | Add a `.runs` dir, `.xpr` or log to watch. |
| `POST /api/msgrule` `{"id": ..., "priority": ...}` | Set or clear a message priority override. |
| `POST /api/settings` `{"interval": 0.5..60}` | Change the poll interval. |
| `DELETE /api/firmware?fw=` | Forget a finished firmware (nothing is deleted on disk). |

Top-level model: `State` contains `Firmware` objects; each has `flows` of `Node` trees (`group`, `run`, `step`, `command`, `phase`, `task`) with `status`, `counts`, `timing`, `reports`, `alerts`, `expected`/`optional` flags and predicted phase numbers. The full field-level contract is in [`SPEC.md`](../SPEC.md).

## Message triage

`score = severity base + priority bonus + keyword bonus + rarity bonus + novelty bonus` (weights in `[messages.scoring]`). Rules and keywords come from `flows.toml`; per-id overrides from `~/.config/vmon/message_rules.json`. When a build finishes, its `{id: count}` map is stored in `~/.cache/vmon/msgs/<fw_id>.json` and becomes the baseline for the next build's "new since last build".

## ETA

Each completed build is stored (last `[eta] history_builds`, default 20, per firmware) in `~/.cache/vmon/durations/<fw_id>.json` as `{"builds": [{"build", "total_s", "steps": {step: s}, "phases": {step: {phase name without number: s}}}]}`; the older single-build file is read as one build and upgraded on the next write. For a running build the remaining time is the sum of the median duration of each pending step plus the current step: the medians of its phases not yet finished (the running phase keeps `max(median - elapsed, current_floor * median)`), or the step median minus elapsed when no phase history exists. The same sum is computed per past build; its p10/p90 (min/max widened by `small_sample_margin` with fewer than 3 builds) give the band. Confidence: at least 5 builds with every remaining step known is high, at least 2 medium, else low; a step never seen in history lowers it one level. When the running step is unknown, or there is no history, it falls back to catalog weights scaled by progress (low confidence, wide band).

## Timing insights

- **Worst paths**: the path sections of a `timing_summary` report are streamed line by line once per (mtime, size) change; only the worst 100 setup + 100 hold paths are kept (`[timing_paths]`). The report summary carries the 8 worst plus `path_counts`; the full list comes from `/api/paths`. Each kept path also carries its parsed "Location / Delay type" table (`launch`, data-path `steps`, `capture`; `path_table.py`, max 200 steps) which the UI draws as a block chain; the summary omits it.
- **Per-clock history**: per-clock values come from the Intra Clock Table of each timing report (`Firmware.clock_history.stages`). When a build finishes, its final values are stored in `~/.cache/vmon/timing/<fw_id>.json` (last 20 builds, keyed by start time; finished builds not yet stored are recorded at startup).
- **Router convergence**: the parser records every `Number of Nodes with overlaps` value and the following Intermediate Timing Summary per router iteration (`Node.convergence`). The trend (converging / stalled / diverging) and the `route_not_converging` alert use `[convergence]`; the alert is raised for live attempts only.
- **Congestion**: the parser reads the placer's `Post-Placement Estimated Congestion` table, the router's `Initial Estimated Congestion` table (with or without `% Tiles`) and the final `Congestion Report` (max % and effective level per direction) into `Node.congestion` as it streams (rules `congestion_*`). Region size `NxN` becomes level log2(N). `congestion.summarize` adds the worst level and `ok`/`warn`/`crit` from `[congestion]`; the amber `congestion` alert fires from `warn_level` and is never an error. The UI shows it in a Congestion tab and a `CONG Ln` chip on the stage card.

## Build history

When a build ends (`done`, `failed` or `stopped`) the monitor stores one record in `~/.cache/vmon/history/<fw_id>.json` (`{"firmware": {id, name}, "builds": [...]}`, oldest first, last `[history] max_builds` kept). Records are keyed by the same build key as the baselines (start time), so a build is stored once; builds already finished at startup are backfilled on the first tick, and a stored build is replaced only when its result changed (for example `stopped` then `done` after a resume).

Result: `met` / `timing_not_met` (final timing only), `failed`, `stopped`, or `done` when there is no final timing. Artifacts are the non-stale reports of the last flow whose kind is in `[history] kinds`, plus `<runs>/<impl run>/<top>.bit` when it was written by this build (mtime not older than the build start). Vivado overwrites report files on every run, so an artifact is served only while its current mtime and size equal the recorded ones; `current` is computed on every read and never stored. The history routes only ever open a path found in the recorded artifacts of the requested build (firmware ids must match `[A-Za-z0-9_-]+`), never a path taken from the query. Nothing is written outside `~/.cache/vmon/`.

### Comparing builds

A record also stores `steps` and `phases` (the durations `eta.py` keeps, same normalisation), `messages` (`{id: {count, severity, text}}` for warnings and worse, worst first, at most `[history] max_messages`, text cut at 160 characters) and `timing_clocks` (final WNS/WHS per clock). The list route strips the heavy fields; `/api/history/build` returns them. Records written before this release lack the fields and still load: their sides of a comparison are `null` and `messages.available` says the message detail is missing. `/api/history/compare` is computed on read by `history.compare_records` (new = in `b` only, removed = in `a` only, changed = count differs, top 200 per list by severity/count or `|delta|`; severity totals come from the recorded `counts`, so they stay exact when the id list was capped). The History page picks `a` and `b` by start time.

### Build summary export

`summary.py` turns a full history record (the same one `/api/history/build` returns) into neutral blocks, then draws them as GitHub Markdown or as one HTML file with inline CSS only (light, print-friendly, no external assets). Sections without data are left out, so records written by older versions still export. Order: title with date, duration and outcome, build info, timing (plus the 10 worst clocks), utilization, step durations, messages (every error and critical warning, then warnings by count, 15 rows at least), attempts, reports and bitstream (marked "replaced by a later build" when no longer current). Records also store `host`, `directives` and `attempts` (one row per attempt number when a resume or restart happened, from `Node.attempts`).

## Notifications outside the browser

`notify.py` delivers events with no browser open. `Monitor._observe` hands every event it logs to `Notifier.submit`; because `_observe` returns on the first observation of a firmware, builds that were already finished or running at startup (and history backfill) never notify, and `submit` also ignores events older than the notifier. Events are filtered like the browser does: `kinds` for step/run events, `codes` plus `min_level` for alerts. A key of (firmware, time, kind, node, code, title) dedupes. Accepted events go to a bounded queue (200) served by one daemon thread, so a slow endpoint never delays the tick. At most `max_per_minute` messages are sent per rolling minute; the rest are counted and sent as one "N more events" message once the window frees. Channels: `notify-send` (argv, no shell), ntfy, Slack, Matrix (a unique transaction id per message) and a generic JSON webhook, all with `timeout_s`. A failing channel is logged once per distinct error with scheme://host only and never raises into the monitor. Configuration is in [`docs/configuration.md`](configuration.md#notifications-outside-the-browser).
