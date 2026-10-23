# Architecture

vmon is a stdlib-only Python backend that reads Vivado logs and marker files, builds a JSON model, and serves it with a vanilla JS single-page UI. It never writes to build directories and never signals processes.

## Modules

| Module | Role |
|---|---|
| `cli.py` | argparse entry point. Picks a free port, or hands paths to an already running vmon. |
| `config.py` | Loads `flows.toml` plus the optional user `flows.toml` in the config dir (`~/.config/vmon/` on Linux, `%APPDATA%\vmon\` on Windows; deep merge, user wins) and compiles regexes. |
| `flows.toml` | All Vivado-specific knowledge: line rules, timing patterns, steps, report registry, alerts, docs links, message triage rules. |
| `catalog/` | One TOML per Vivado version describing every step, phase and task (see [catalog.md](catalog.md)). |
| `paths.py` | Per-platform data directories, the path contract (`canon`, `path_key`) and atomic JSON writes. |
| `textio.py` | Decoding of Vivado text files (UTF-8, CRLF folded to LF). |
| `discovery.py` | Finds Vivado processes through the platform backend and groups them into firmwares. |
| `logtail.py` | Incremental file reader (byte offset + file identity, handles truncation and replacement). |
| `logparse.py` | Streaming parser: log lines to sections, phases, tasks, messages and timing. |
| `project.py` | Builds a firmware's flow from a `.runs` directory (marker files, run tcl, logs, reports). |
| `expected.py` | Merges catalog placeholders (upcoming steps/phases, predicted numbers, weights) into the seen nodes. |
| `timing_paths.py`, `path_table.py`, `clocks.py`, `convergence.py`, `congestion.py` | Worst-path parser for timing reports (streamed), per-clock history across stages and builds, router overlap trend, congestion level summary. |
| `reports.py` | Parses utilization, timing summary, DRC/methodology, power, route status and other reports. |
| `summary.py` | Renders a recorded build to Markdown or a self-contained HTML page. |
| `history.py` | Build history store and records (`<cache dir>/history/`), artifact validation for the history API. |
| `alerts.py`, `triage.py`, `eta.py`, `info.py`, `docs.py` | Alerts, message scoring and baselines, ETA, build info, documentation links. |
| `sysstats.py`, `browse.py` | System CPU/RAM/swap through the platform backend; read-only directory listing for the folder explorer. |
| `remote.py` | Remote vmon instances: config/CLI validation, one poller thread per remote, id namespacing, request forwarding. |
| `monitor.py` | Background thread: each tick discover, update parsers, publish state. |
| `term.py`, `source.py`, `status.py`, `tui.py` | Terminal mode: pure formatting over the state dict (`term`), the data source (`source`), `vmon status` and the curses `--tui`. |
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

Everything read is read-only. The only files vmon writes are under the cache dir and `message_rules.json` in the config dir (your message priority overrides). The dirs are `~/.cache/vmon/` and `~/.config/vmon/` on Linux, `%LOCALAPPDATA%\vmon\` and `%APPDATA%\vmon\` on Windows (fallbacks `~\AppData\Local\vmon` and `~\AppData\Roaming\vmon`); `paths.py` is the only place that knows them. Every JSON store is written to a temp file and moved over with `os.replace`, retried briefly because Windows refuses to replace a file another process has open.

## Discovery

- Process access goes through a read-only platform backend (`vmon/procinfo.py` picks it from `sys.platform`; Python standard library and `ctypes` only):
  - Linux (`procinfo_linux.py`): scans `/proc/*/comm` for `vivado`, then reads `cmdline`, `cwd` and the parent pid; system and per-process stats come from `/proc/stat`, `meminfo`, `loadavg`, `PID/stat` and `PID/status`.
  - Windows (`procinfo_windows.py`, bindings in `winapi.py`): a Toolhelp snapshot lists pids, parent pids and image names; Vivado is any `vivado.exe` (case-insensitive; `vivado.bat`, the loader and `cmd.exe` parents are not Vivado processes but stay in the process tree, so launcher detection through descendants works unchanged). Command line and current directory are read from the target's PEB (`NtQueryInformationProcess` + `ReadProcessMemory`, opened with query/read rights only) and split like `CommandLineToArgvW`. Protected or other users' processes simply lack those fields. CPU comes from `GetSystemTimes`/`GetProcessTimes`, memory from `GlobalMemoryStatusEx` and the working set. Swap is approximated as commit limit minus physical RAM; there is no load average (`load1` is `null`, the UI omits it). Reading another process's PEB needs a 64-bit Python.
  - Other systems (macOS): a null backend with no discovery and no stats; a one-line notice is printed and manually added paths still work.
- If the cwd is `<X>.runs/<run>/` (matched case-insensitively, with either slash style on Windows), the process belongs to project `<X>.runs`.
- Otherwise it looks for `-log <file>` (or `vivado.log` in the cwd) and scans it for `open_project <path>.xpr` and `create_project <name> [dir]` (the last one wins). Vivado echoes a sourced script with its variables unexpanded, so simple `set var value`, `set var [file normalize x]` and `set var [pwd]` lines are substituted first; anything still unresolved is ignored (patterns in `[parse]`). A launcher process is also tied to a project through its Vivado descendants, and a log first seen on its own is merged into the project once it turns out to be that project's launcher.
- With no project found, the log becomes a standalone "log" firmware (non-project flow).
- Paths given on the command line or through the UI are watched too, and the last 20 are remembered in `<cache dir>/recent.json` so finished runs reappear after a restart.

## Windows notes

- **Browser tests**: `tests/e2e/` (marker `e2e`, Playwright, dev-only) has two session fixtures: `mock_url` serves `vmon/static` from a `ThreadingHTTPServer` for `index.html?mock=1`, and `real_url` runs the real `Monitor` and HTTP server in-process on a temporary copy of the qick fixture `.runs` tree (with its reports) and a redirected profile. One browser per session, one context per test (1440x1000, 820 for the narrow test); a JS console error, page error or unhandled rejection fails the test. Mock tests pause the page clock (`page.clock`) once the UI is up and advance it explicitly, so follow-live checks are deterministic. Tests skip when playwright or the browser is missing.
- **Data dirs**: see above; tests redirect `HOME`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA` and `XDG_*` to a temp dir, so nothing touches a real profile on any OS.
- **Path contract**: parsing keeps the syntax of its input (Vivado writes both `C:/work/x.runs` and `C:\work\x.runs`). `discovery.runs_location` is purely syntactic: drive/UNC input comes back with backslashes, anything else as POSIX, on every OS. What becomes a key or is shown (group paths, watched and recent paths, `/api/*` paths) goes through `paths.canon`: native form on Windows (backslashes, upper-case drive letter), untouched on Linux. Firmware ids and group keys use `paths.path_key`, which is case-insensitive on Windows, so `c:/W/x.runs` and `C:\w\X.runs` are one firmware. Node ids such as `impl_1/route_design` always use `/`.
- **CRLF**: Vivado on Windows writes `\r\n`. Binary readers decode with `textio.decode` (CRLF folded to LF) and `LogTail` strips the `\r` of every complete line; a `\r\n` split across two reads stays in the partial buffer until the `\n` arrives. Text-mode readers already fold it.
- **Paths inside Vivado files**: `open_project`, `cd` and `open_checkpoint` lines, `-log` arguments and checkpoint names are split with either separator; `ntpath` is used for drive/UNC paths even when vmon runs elsewhere (tests).
- **Explorer**: the UI breadcrumb understands `C:\`, `\\server\share` and a "This PC" root that lists the drives.
- **Desktop notifications**: the default is a PowerShell toast (`powershell.exe -NoProfile -NonInteractive -EncodedCommand ...`); an explicit `command` replaces it.
- **Not available**: no load average (`load1` is `null`), and no POSIX signal handling anywhere (`Ctrl-C` is the only stop signal used, and the tool never signals other processes).

## Project-mode sources

For a run directory `R`:

- `R/.<step>.begin.rst`, `.end.rst`, `.error.rst`: step status and start/end time (mtime).
- `R/<top>.tcl`: `start_step <name>` lines give the planned step list (only enabled steps).
- `R/gen_run.xml`, `runme.log`; main log is `<top>.vds` (synth) or `<top>.vdi` (impl).
- `<X>.runs/.jobs/vrs_config_<N>.xml` with the highest N lists the runs of the current launch. When it has no
  synthesis run (a script that calls `launch_runs impl_1` after synthesis), the latest earlier launch that has one
  adds its synthesis and OOC runs.
- Reports such as `<top>_timing_summary_routed.rpt`; a report older than its step's begin marker is flagged stale and never raises alerts.

Flow layout: a "Synthesis" stage (out-of-context IP runs collapsed into a sub-group, then the top synth run), followed by each implementation step in tcl order. Steps not yet started are shown as pending placeholders from the catalog.

## Incremental parsing

Each log is parsed once; later ticks read only the appended bytes. A changed file identity or a shrinking file restarts from offset 0 (run reset). The identity is the inode, or the creation time on Windows filesystems that report inode 0. Offsets are byte offsets of the raw file, so `\r\n` files index and re-read exactly; the reader opens read-only and never keeps the file open between ticks, and a transient `PermissionError` (Vivado writing) just means "nothing new yet". Logs of 100k+ lines are never re-read per tick. The state JSON excludes message lists, which are served on demand.

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
| `GET /api/history/compare?fw=&a=&b=[&fw_b=]` | Diff of build `a` of `fw` and build `b` of `fw_b` (default `fw`; `a` base/older, `b` newer): timing, utilization, step durations, messages; the `a`/`b` headers carry each side's `fw_id`, `firmware` and `project`. 404 for an unknown firmware or build, 400 when both sides are the same build or (remote ids) on different hosts. |
| `GET /api/history/summary?fw=&build=&format=md\|html&download=1` | Printable summary of one recorded build: `text/markdown` (default) or `text/html`; `download=1` adds `Content-Disposition: attachment; filename="<firmware>_<YYYY-MM-DD_HHMM>_summary.<ext>"`. 404 for an unknown firmware or build, 400 for another format. |
| `GET /api/history/report?fw=&build=&path=` | Text of a recorded report. `path` must be an artifact of that build and still current (same mtime and size); else 404 (not listed) or 410 (replaced by a later build). |
| `GET /api/history/artifact?fw=&build=&path=` | Streams a recorded artifact (the bitstream) as `application/octet-stream` with `Content-Disposition: attachment`; same validation as the report route. |
| `GET /api/notify` | Server-side notification status: `{enabled, channels: [{name, label, enabled, configured, target, error}], kinds, codes, min_level, last_error}`. `target` is scheme://host only; errors never contain URLs or tokens. |
| `POST /api/notify/test` | Sends a test message to every enabled channel (synchronously) and returns `{"results": [{name, ok, error?}]}`; `[]` when nothing is enabled. |
| `GET /api/browse?path=` | Read-only directory listing for the explorer. Refuses `/proc`, `/sys`, `/dev` on Linux and `\\.\` / `\\?\` device paths on Windows, where `path=::drives` lists the drive roots (the parent of a drive root) and `C:\` or `C:/` are both accepted. |
| `POST /api/watch` `{"path": ...}` | Add a `.runs` dir, `.xpr` or log to watch. |
| `POST /api/msgrule` `{"id": ..., "priority": ...}` | Set or clear a message priority override. |
| `GET /api/msgrules/export?by=` | Your message rules as a `vmon-message-rules` v1 file (attachment `vmon_message_rules_<YYYY-MM-DD>.json`); `exported_by` is empty unless `by` is given. |
| `POST /api/msgrules/import` `{"mode": "merge"\|"replace", "dry_run": true, "keep_mine": false, "data": <file>}` | Preview (default) or apply a rules file; returns `{added, changed, removed, unchanged, kept_mine, invalid, applied}`. 400 bad file or options, 413 over 2 MB, 422 when applying a file with invalid entries (nothing is imported). Format in [`SPEC.md`](../SPEC.md). |
| `POST /api/settings` `{"interval": 0.5..60}` | Change the poll interval. |
| `DELETE /api/firmware?fw=` | Forget a finished firmware (nothing is deleted on disk). |

Routes that take `fw=` accept `<host>~<id>` for a firmware of a [remote](#remote-vmon-instances) and are forwarded to that host; the table above describes them as the remote answers.

Top-level model: `State` contains `Firmware` objects; each has `flows` of `Node` trees (`group`, `run`, `step`, `command`, `phase`, `task`) with `status`, `counts`, `timing`, `reports`, `alerts`, `expected`/`optional` flags and predicted phase numbers. The full field-level contract is in [`SPEC.md`](../SPEC.md).

## Terminal mode

`vmon status` and `vmon --tui` consume the same state dict as the web UI. `source.Source` first asks `GET /api/state` on `--host:--port`; a vmon that answers is the source (remotes included, `paths` only filter its firmwares). Otherwise it builds a `Monitor(read_only=True)` with the normal config, adds the given paths (the remembered ones load as usual) and ticks once synchronously in a worker thread with a 120 s bound; `--tui` starts the monitor thread instead and a poller thread hands snapshots to the UI, so rendering never blocks a tick. `read_only` only suppresses writes to `recent.json`; a tick still writes its normal cache files. No server is started and no browser opened.

`term.py` is pure: a rendered line is a list of `(text, tone)` segments painted as ANSI (status) or curses attributes (tui). Outcome words and tones follow the UI (red only for failed or final timing not met; stale, non-final and estimated values are amber). `tui.Model` holds selection, expansion and scroll and renders to a list of lines for a given size, so it is tested without a terminal; `curses` is imported optionally and Windows falls back to `status --watch`. Exit codes of `status` are in the README.

## Remote vmon instances

On each build server a normal vmon runs (bound to `127.0.0.1`); its port is forwarded by SSH (`ssh -N -L 9001:127.0.0.1:8765 user@server`) and the local vmon aggregates it (`[remote]`, `--remote`, `--ssh`; see [configuration.md](configuration.md#remote-vmon-instances)). `remote.py` holds the logic; the local monitor tick never waits for the network.

- **Polling**: one daemon thread per remote fetches `GET /api/state` every `interval_s` (timeout `timeout_s`). It keeps the last good snapshot and a status `{name, url (scheme://host:port), online, last_ok, error, version, system, firmwares}`. A failed poll keeps the snapshot and flips `online` to false; `error` is a short reason that never contains a URL. The merged state (and so SSE) is published only when a snapshot or online/error changes.
- **Merge**: `state.firmwares` is the local list (ids unchanged, `host: null`) followed by each remote's firmwares with `id = "<host>~<remote id>"` and `host = "<host>"`; `state.remotes` holds the statuses. Events and alerts travel inside the firmware objects, so browser notifications cover remote builds. A firmware that already has a `host` (a remote that itself aggregates) is skipped, so chains and loops cannot form. `system` stays local; a remote's last meters are in its status.
- **Proxy**: for `/api/messages`, `/api/triage`, `/api/log`, `/api/report`, `/api/paths` and every `/api/history/*` route, and `DELETE /api/firmware`, a `fw` of the form `<host>~<id>` is sent to that remote with the original id and all other parameters untouched (the remote validates paths and builds). The status, `Content-Type`, `Content-Length` and `Content-Disposition` are relayed and the body is streamed in 64 KiB chunks, so artifact downloads work. `fw_b` of a compare is stripped the same way, and both ids must name the same host (otherwise 400, nothing is forwarded). History answers that carry firmware ids (`/api/history`, `/build`, `/compare`, including the `a`/`b` headers) are rewritten to the namespaced id and builds get a `host` field. An unreachable or timed-out remote gives `502 {"error": "remote <host> unreachable: <reason>"}`, a redirect from a remote gives 502, an unknown host prefix gives 404 without any network access.
- **Global history**: `GET /api/history` without `fw` also lists the builds and firmwares of every online remote (ids namespaced, newest first, same `limit`); `unreachable` lists the remotes that were skipped.
- **Local only**: `POST /api/watch`, `GET /api/browse`, `/api/msgrule`, `/api/msgrules/*`, `/api/notify` and `/api/settings` act on the machine the UI is served from.
- **UI**: remote tabs carry the host badge and the header says "on <host>". When a remote is offline its firmwares stay, marked stale ("<host> unreachable · last update HH:MM", hollow ochre dot, frozen clocks), never red. The top bar shows one dot per remote (only when remotes are configured).

## Message triage

`score = severity base + priority bonus + keyword bonus + rarity bonus + novelty bonus` (weights in `[messages.scoring]`). Rules and keywords come from `flows.toml`; per-id overrides from `<config dir>/message_rules.json`. When a build finishes, its `{id: count}` map is stored in `<cache dir>/msgs/<fw_id>.json` and becomes the baseline for the next build's "new since last build".

## ETA

Each completed build is stored (last `[eta] history_builds`, default 20, per firmware) in `<cache dir>/durations/<fw_id>.json` as `{"builds": [{"build", "total_s", "steps": {step: s}, "phases": {step: {phase name without number: s}}}]}`; the older single-build file is read as one build and upgraded on the next write. For a running build the remaining time is the sum of the median duration of each pending step plus the current step: the medians of its phases not yet finished (the running phase keeps `max(median - elapsed, current_floor * median)`), or the step median minus elapsed when no phase history exists. The same sum is computed per past build; its p10/p90 (min/max widened by `small_sample_margin` with fewer than 3 builds) give the band. Confidence: at least 5 builds with every remaining step known is high, at least 2 medium, else low; a step never seen in history lowers it one level. When the running step is unknown, or there is no history, it falls back to catalog weights scaled by progress (low confidence, wide band).

## Timing insights

- **Worst paths**: the path sections of a `timing_summary` report are streamed line by line once per (mtime, size) change; only the worst 100 setup + 100 hold paths are kept (`[timing_paths]`). The report summary carries the 8 worst plus `path_counts`; the full list comes from `/api/paths`. Each kept path also carries its parsed "Location / Delay type" table (`launch`, data-path `steps`, `capture`; `path_table.py`, max 200 steps) which the UI draws as a block chain; the summary omits it.
- **Per-clock history**: per-clock values come from the Intra Clock Table of each timing report (`Firmware.clock_history.stages`). When a build finishes, its final values are stored in `<cache dir>/timing/<fw_id>.json` (last 20 builds, keyed by start time; finished builds not yet stored are recorded at startup).
- **Router convergence**: the parser records every `Number of Nodes with overlaps` value and the following Intermediate Timing Summary per router iteration (`Node.convergence`). The trend (converging / stalled / diverging) and the `route_not_converging` alert use `[convergence]`; the alert is raised for live attempts only.
- **Congestion**: the parser reads the placer's `Post-Placement Estimated Congestion` table, the router's `Initial Estimated Congestion` table (with or without `% Tiles`) and the final `Congestion Report` (max % and effective level per direction) into `Node.congestion` as it streams (rules `congestion_*`). Region size `NxN` becomes level log2(N). `congestion.summarize` adds the worst level and `ok`/`warn`/`crit` from `[congestion]`; the amber `congestion` alert fires from `warn_level` and is never an error. The UI shows it in a Congestion tab and a `CONG Ln` chip on the stage card.

## Recommended actions

`hints.py` compiles `[[hints]]` at config load (`config.load_config` merges hint lists by id and applies `[hints_config] disabled`; a bad rule raises `ConfigError`, a `ValueError`, naming the hint). `Monitor._hints` evaluates them every tick after the firmware snapshot and stores the result in `Firmware.hints`. A `Facts` object flattens the last flow once (step and run nodes, IP out-of-context runs excluded); conditions only read model fields: alerts, step timing, congestion, convergence, failures, utilization, the compact worst paths of the latest timing report and the aggregated warning-or-worse message groups. Nothing is parsed per tick: paths (including each path's largest net fanout) are produced once per report (mtime, size) by `ReportCache`, and message groups are cached per source message generation. Each hint yields `{id, title, severity, text, evidence, actions, node_id}`; `evidence` is built by the conditions that matched. See [configuration.md](configuration.md#recommended-actions).

## Build history

When a build ends (`done`, `failed` or `stopped`) the monitor stores one record in `<cache dir>/history/<fw_id>.json` (`{"firmware": {id, name}, "builds": [...]}`, oldest first, last `[history] max_builds` kept). Records are keyed by the same build key as the baselines (start time), so a build is stored once; builds already finished at startup are backfilled on the first tick, and a stored build is replaced only when its result changed (for example `stopped` then `done` after a resume).

Result: `met` / `timing_not_met` (final timing only), `failed`, `stopped`, or `done` when there is no final timing. Artifacts are the non-stale reports of the last flow whose kind is in `[history] kinds`, plus `<runs>/<impl run>/<top>.bit` when it was written by this build (mtime not older than the build start). Vivado overwrites report files on every run, so an artifact is served only while its current mtime and size equal the recorded ones; `current` is computed on every read and never stored. The history routes only ever open a path found in the recorded artifacts of the requested build (firmware ids must match `[A-Za-z0-9_-]+`), never a path taken from the query. Nothing is written outside the cache dir.

### Comparing builds

A record also stores `steps` and `phases` (the durations `eta.py` keeps, same normalisation), `messages` (`{id: {count, severity, text}}` for warnings and worse, worst first, at most `[history] max_messages`, text cut at 160 characters) and `timing_clocks` (final WNS/WHS per clock). The list route strips the heavy fields; `/api/history/build` returns them. Records written before this release lack the fields and still load: their sides of a comparison are `null` and `messages.available` says the message detail is missing. `/api/history/compare` is computed on read by `history.compare_records` (new = in `b` only, removed = in `a` only, changed = count differs, top 200 per list by severity/count or `|delta|`; severity totals come from the recorded `counts`, so they stay exact when the id list was capped). The History page picks `a` and `b` by start time; any two builds may be picked, also of different firmwares. Hash params: `hcmp=<fwA>:<buildA>,<fwB>:<buildB>` (or the older `hcmp=<buildA>,<buildB>`), `hdone=1` for the *Finished only* filter (hides `failed` and `stopped` results; also remembered in localStorage).

### Build summary export

`summary.py` turns a full history record (the same one `/api/history/build` returns) into neutral blocks, then draws them as GitHub Markdown or as one HTML file with inline CSS only (light, print-friendly, no external assets). Sections without data are left out, so records written by older versions still export. Order: title with date, duration and outcome, build info, timing (plus the 10 worst clocks), utilization, step durations, messages (every error and critical warning, then warnings by count, 15 rows at least), attempts, reports and bitstream (marked "replaced by a later build" when no longer current). Records also store `host`, `directives` and `attempts` (one row per attempt number when a resume or restart happened, from `Node.attempts`).

## Notifications outside the browser

`notify.py` delivers events with no browser open. `Monitor._observe` hands every event it logs to `Notifier.submit`; because `_observe` returns on the first observation of a firmware, builds that were already finished or running at startup (and history backfill) never notify, and `submit` also ignores events older than the notifier. Events are filtered like the browser does: `kinds` for step/run events, `codes` plus `min_level` for alerts. A key of (firmware, time, kind, node, code, title) dedupes. Accepted events go to a bounded queue (200) served by one daemon thread, so a slow endpoint never delays the tick. At most `max_per_minute` messages are sent per rolling minute; the rest are counted and sent as one "N more events" message once the window frees. Channels: desktop (`notify-send` argv with no shell, or on Windows a fixed PowerShell toast script passed as `-EncodedCommand`, with title and body in environment variables, never in the code), ntfy, Slack, Matrix (a unique transaction id per message) and a generic JSON webhook, all with `timeout_s`. A failing channel is logged once per distinct error with scheme://host only and never raises into the monitor. Configuration is in [`docs/configuration.md`](configuration.md#notifications-outside-the-browser).
