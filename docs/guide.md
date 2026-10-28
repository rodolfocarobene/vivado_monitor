# User guide

You are here: the task-oriented guide. Start with the [README](../README.md) for install and a first look. For settings and extending vmon see [configuration.md](configuration.md); for internals see [architecture.md](architecture.md).

Each section answers one question. Jump to the one you need.

- [Requirements](#requirements)
- [Command line](#command-line)
- [How do I watch a running build?](#how-do-i-watch-a-running-build)
- [How do I open a finished or old run?](#how-do-i-open-a-finished-or-old-run)
- [How do I read the hero and Needs attention?](#how-do-i-read-the-hero-and-needs-attention)
- [How do I use the phase timeline and inspector?](#how-do-i-use-the-phase-timeline-and-inspector)
- [How do I triage messages?](#how-do-i-triage-messages)
- [How do I compare two builds, or a build against the live one?](#how-do-i-compare-two-builds-or-a-build-against-the-live-one)
- [How do I use history and trends?](#how-do-i-use-history-and-trends)
- [How do I get notified?](#how-do-i-get-notified)
- [How do I watch builds on another machine?](#how-do-i-watch-builds-on-another-machine)
- [How do I monitor non-project Tcl builds and Vitis HLS?](#how-do-i-monitor-non-project-tcl-builds-and-vitis-hls)
- [How do I check a build from the terminal?](#how-do-i-check-a-build-from-the-terminal)
- [How do I use it on a phone?](#how-do-i-use-it-on-a-phone)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Troubleshooting and FAQ](#troubleshooting-and-faq)

## Requirements

- Linux, or Windows (experimental, see the testing note in the [README](../README.md#testing-is-limited)). macOS runs, but without process discovery (see [macOS](#does-it-run-on-macos)).
- Python 3.11 or newer, unless you use a prebuilt executable: those bundle their own Python.
- Vivado project-mode or non-project logs.
- Vitis HLS 2023.2 `vitis_hls.log`: the project and solution are read from the log, the planned steps from the `-f` Tcl script.
- For a scripted non-project build (`vivado -mode batch -source build.tcl`) the steps are planned from the script (`source`d files are followed). Only the steps the script calls show as pending. The reports it writes with `report_xxx -file <path>` (timing, utilization, ...) are shown on the step that wrote them.

## Command line

```sh
vmon                          # watch all running Vivado builds, open the browser
vmon path/to/proj.runs        # also watch a .runs dir, .xpr or log file
vmon --port 9000 --no-browser
vmon status                   # one-shot text summary, no browser (quick check over SSH)
vmon --tui                    # live full-screen terminal view
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
| `--tui` | | Full-screen terminal view instead of the web UI (curses; on Windows a refreshing text view) |
| `--version` | | Print `vmon <version>` and exit (next to `--help`) |
| `--ssh USER@HOST[:PORT]` | | Start `ssh -N -L` to the vmon on that host (default remote port 8765) and aggregate it; the tunnel ends with vmon |

If a vmon is already running on the port, the new command hands it your paths and opens the browser on it instead of starting a second server.

`vmon status` has its own options, listed in [the terminal section](#how-do-i-check-a-build-from-the-terminal).

## How do I watch a running build?

1. Start `vmon` (it can run before or after you launch Vivado) and open http://localhost:8765. The browser opens by itself unless you pass `--no-browser`.
2. vmon finds running Vivado processes on its own. Each firmware gets one tab. A tab shows a status dot, the name, an alert count and a host marker; the step and elapsed time are in the tooltip. Tabs that do not fit move into a **+N** menu.
3. Read the hero at the top of the tab (see [below](#how-do-i-read-the-hero-and-needs-attention)): it says what is running and when it should finish.
4. The left rail pins the stages: synth, opt, place, phys_opt, route, bitstream. Turn on *follow live* in the top bar and the view stays on the stage that is running.
5. Upcoming steps and phases come from a per-version phase catalog, with predicted phase numbers. They appear dashed, so you can see what is still to come.
6. Leave the tab open on a second monitor. The *All builds* home (click the logo, press `0`, or open `#home`) shows every build as a card, grouped Running / Needs attention / Finished. Each card has its step and ETA, a compact stage strip, elapsed time, WNS, worst utilization, error counts and the build's CPU/RAM. A card opens that firmware. The logo badge counts the builds that need attention. *Wall display* shows the same cards fullscreen and larger, for a screen across the room (Esc leaves).

Other things in the window: system CPU / RAM / swap meters, a sticky summary, build info (part, board, strategies, directives, with links to AMD documentation) and an in-app event log.

How the numbers behave:

- **Timing you can trust.** Intermediate and estimated values are shown as "not final". Red appears only when the final result fails. Missing hold metrics are carried forward and marked stale.
- **ETA with a confidence band.** Per-step and per-phase durations are learned from the last 20 builds of the same firmware (medians, p10-p90 range). Steps never seen are sized from the catalog. The same history (else the catalog weights) gives each pending or running phase its expected duration, drawn as a dashed bar in the timeline. The settings are in `[eta]`, see [configuration.md](configuration.md#eta).

## How do I open a finished or old run?

- Finished runs stay visible as tabs while vmon runs, and the last 20 watched paths are remembered across restarts.
- Pass a path: `vmon /path/to/proj.runs`. A `.runs` dir, `.xpr`, run dir or log file all work.
- Or use the folder explorer in the UI (the *Explore* button) to add runs.
- Older builds of a firmware are in the [history page](#how-do-i-use-history-and-trends). Click one to open its project in the standard view (it is loaded again if its tab was closed).

You can also export any build as a summary: Markdown, a self-contained HTML page (timing, utilization, top warnings, attempts, reports), or copy it to the clipboard.

## How do I read the hero and Needs attention?

The **hero** at the top of each firmware has:

- a one-line verdict, for example "Placing · expected to finish ~16:42 (in 1h 19m) · timing failing by 0.184 ns (estimate)". Finished, failed, stopped, queued, HLS and log-only builds have their own wording;
- a build progress strip, one segment per stage, sized by real or expected time (history medians);
- four metric tiles: WNS (estimate or final, with a sparkline, TNS and WHS), worst utilization, elapsed time, and messages by severity.

Vmon also parses intermediate reports (timing, DRC, power, route status, ...), so the tiles fill in as the run goes.

**Needs attention** is one list. It merges alerts, the top message groups and the suggested actions, with no duplicates, worst first. It shows three rows, then "Show N more".

- Each row names its step and jumps to it.
- Dismiss a row with its button. The counts stay.
- A *Fix* fold-out on a row shows the suggested action: the evidence that fired it and commands you can copy. The stage detail links to it.
- Alerts also raise browser notifications and go to the in-app event log.

Suggested actions are rule-based hints from `[[hints]]` in `flows.toml`: hold violated after route, route- or logic-dominated setup paths, high fanout, congestion, router stalled, out of memory, lost license, latches, and more. Timing hints need final timing, so an estimate never produces advice. You can add your own or disable built-ins, see [configuration.md](configuration.md#recommended-actions).

Congestion for place and route is summarized too: placer and router congestion levels per direction, final max congestion, router overlaps per iteration. A chip and an alert appear from level 5.

## How do I use the phase timeline and inspector?

Click a stage in the left rail. It opens on the right as a **phase timeline**:

- one flat outline of task, phase and sub-phase rows, each with status, message counts, elapsed time and peak memory;
- a Gantt bar per row on the step's shared time axis: striped and animated while running, dashed for what is still expected.

Below the outline is one **inspector** with tabs: Messages, Log, Reports, Timing, Congestion, Convergence. It is scoped to the selected row. The running or failed row is selected for you; picking one pins it.

What the tabs answer:

- **Timing**: the worst timing paths (setup/hold, logic vs route). Expand one to see it as a chain of blocks: launch register, each cell and net with its delay and fanout, capture register. A per-clock history across stages and builds highlights regressions.
- **Convergence**: the router convergence chart (overlaps and slack per iteration, live). vmon alerts when the router stalls or diverges (`[convergence]`, see [configuration.md](configuration.md#router-convergence)).
- **Congestion**: levels per direction (see the hero section above; `[congestion]` in [configuration.md](configuration.md#congestion)).
- **Reports**: the parsed reports of that step.

On narrow windows the list becomes one tree, with the stage opening in place. Below 700 px see [phone](#how-do-i-use-it-on-a-phone). Keys for the outline are in the [shortcuts](#keyboard-shortcuts) table.

## How do I triage messages?

Open the Messages view (`m`). Messages are scored by severity, rules, keywords, rarity and "new since last build". The scoring weights, rules and keywords are in `[messages.*]`, see [configuration.md](configuration.md#message-rules-and-keywords).

- **Star or mute** any message id. Your choices are written to `message_rules.json` in the config dir.
- **Export rules** downloads your star/mute rules as a file. **Import rules...** previews what changes first, then merges or replaces. Details, including how to share rules in a team, are in [configuration.md](configuration.md#sharing-message-rules).
- Messages that are new compared with the previous build are scored higher, so a fresh critical warning stands out.

## How do I compare two builds, or a build against the live one?

- **Two finished builds**: open the history (`h`), tick any two (even of different firmwares, for example a copied project folder), and compare. Or pick "vs previous". You get timing and utilization deltas, step durations, and new, removed and changed warnings.
- A comparison opens as its own tab after the firmware tabs. Close it with its x, or Delete. It stays open while you switch tabs and after a reload.
- **A build in progress**: unfinished firmwares appear as pinned *Live* rows in the history, and the firmware header has a *Compare* button. The live side is the current state: provisional, refreshed every 5 s while its tab is shown, and never stored in the history.

## How do I use history and trends?

Press `h` (or use the history button; `h` or Esc leaves). The page lists every finished build with date, duration, outcome, final WNS/WHS and utilization.

- A *Reports* menu per row: the report links, the `.bit` with a copy-path item, and the Markdown summary. They are available only while the files still belong to that build. Next to it a *Summary* button gives the printable HTML.
- With one firmware selected, a **trend strip** of three small charts (WNS, duration, worst utilization) runs across its builds: one evenly spaced slot per build with dates at the ends, so bursts of builds stay clickable. A point scrolls to its row.
- Each row shows the project path. A *Finished only* switch hides failed and stopped builds.
- Click a build to open its project in the standard view. Tick two to compare.

The size of the history is set in `[history]`, see [configuration.md](configuration.md#build-history).

## How do I get notified?

Two layers:

- **In the browser**: alerts raise browser notifications and go to the in-app event log (the bell).
- **Outside the browser**, with no browser open: `notify-send` (a toast on Windows), ntfy, Slack, Matrix or a JSON webhook, for crashes, step and run results and timing failures. This is off by default. Set it up in `[notify]` and keep secrets in environment variables. The full setup, with examples for each channel, is in [configuration.md](configuration.md#notifications-outside-the-browser). The "Send test" button tests every enabled channel.

Only events that happen while vmon runs are sent; builds already finished at startup are not.

## How do I watch builds on another machine?

Run a normal vmon on the build server (it binds to `127.0.0.1` there), forward its port, and aggregate it locally:

```sh
ssh -N -L 9001:127.0.0.1:8765 user@server &          # or let vmon do it: vmon --ssh user@server
vmon --remote buildsrv=http://127.0.0.1:9001
```

- Remote firmwares appear as tabs with a host badge. The top bar shows one dot per remote (hover for the address and last update). An unreachable host leaves its tabs visible but marked stale.
- Messages, logs, reports, timing paths, history, comparisons, summaries and downloads are fetched from the server on demand through your local vmon, which only ever talks to the hosts you configured. You can also aggregate several machines in one UI.
- `Explore` still acts on this machine.
- Message rules are per machine: import them on the machine that builds.

Details and the `[remote]` section: [configuration.md](configuration.md#remote-vmon-instances).

## How do I monitor non-project Tcl builds and Vitis HLS?

**Non-project Tcl**: a build started with `vivado -mode batch -source build.tcl` shows up as a log-only firmware. The steps are planned from the script, so only the commands it calls show as pending, and reports it writes with `report_xxx -file <path>` appear on the step that wrote them. How the script is read is set in `[nonproject]`.

**Vitis HLS**: a `vitis_hls` (or `vitis-run`) run is an `hls` firmware. It shows:

- its steps: `csynth_design` with compile, transformation, scheduling, binding and RTL phases, `export_design` with its packaging Vivado log, `csim_design` and `cosim_design`;
- message counts;
- the estimated clock against the target, as "estimated" timing;
- the `csynth.xml` latency, interval and resource summary.

Open one by hand with `vmon /path/to/vitis_hls.log` (or the directory, the HLS project or the solution dir). A `v++` build is only tied to the Vivado it runs (unverified, see the [testing note](../README.md#testing-is-limited)).

## How do I check a build from the terminal?

`vmon status [paths...]` prints one line per firmware: name (`name@host` for remotes), outcome (the web UI's words, e.g. `Finished, timing not met`), current step or failure reason, progress (`~42%` is an estimate), elapsed, expected end with its range, WNS/WHS (a leading `~` marks a non-final estimate), message counts E/CW/W and the alert count. Firmwares with alerts or hints get up to three indented lines below. Colors (green met/done, red only final failures, amber warnings, estimates and stale remotes, blue running) are used only on a terminal, never with `--no-color` or `NO_COLOR`.

```sh
vmon status                                # whatever is running or remembered
vmon status path/to/proj.runs --json       # for scripts
vmon status --watch 5                      # refresh every 5 s, Ctrl-C to stop
ssh user@server vmon status                # over SSH, nothing to forward
```

Data source: if a vmon answers on `--host`/`--port` it is used (with its remotes; `paths` then only filter its firmwares). Otherwise vmon computes one snapshot locally from the running Vivado processes, the remembered paths and the given paths, without a server or browser. Local mode never updates the remembered (recent) paths; its tick writes only the usual cache files (message baselines, step durations, history), and `[remote]` entries of `flows.toml` are not polled.

`vmon status` is the subcommand only when it is the first argument and no file or directory called `status` exists in the current directory (then it is a path, as before).

| Exit code | Meaning |
|---|---|
| 0 | nothing failed (running, done, stopped, queued) |
| 1 | a firmware failed, or finished with final timing not met |
| 2 | usage or configuration error |
| 3 | nothing to show: no vmon reachable and no firmware found or watched |

`vmon --tui [paths...]` is the same data in a live screen: firmware list on top, the selected firmware's stages (status markers, durations, running phase, WNS chip) and its alerts and hints below. Keys: up/down or `j`/`k` move, `Enter`/right expand (alerts under a firmware, children of a stage), left collapses, `Tab` switches between the two panes, `r` refreshes, `h` help, `q` quits. It connects to a running vmon or starts its own monitor in a background thread; the terminal is restored on exit. It needs `curses`, which Windows lacks: there (or without a TTY) `--tui` shows the refreshing text view of `vmon status --watch` instead.

`vmon status` takes `paths`, `--port`, `--host` and `--config` like `vmon`, plus:

| Option | Meaning |
|---|---|
| `--json` | Print JSON (firmware subset, remotes, exit code) instead of the table |
| `--watch SECONDS` | Reprint every SECONDS until Ctrl-C (clears the screen on a terminal) |
| `--no-color` | No ANSI colors (also `NO_COLOR`, or output that is not a terminal) |

## How do I use it on a phone?

Open the address of the machine running vmon on the phone, for example through an SSH tunnel or after you start vmon with `--host` set to a reachable address. By default vmon binds to `127.0.0.1` only, so nothing outside your machine can see it.

Below 700 px the UI becomes drill-in navigation:

- a compact top bar with a firmware switcher (it has an *All builds* entry; the logo opens it too);
- a hero with the attention list;
- one full-width screen per level (stage, task, phase), with a back button and a breadcrumb. The phone's Back button pops a level;
- Messages, Log, Reports and Timing in a bottom sheet;
- a Build / Messages / History tab bar;
- a *Jump to running* chip that follows the running node until you navigate yourself.

## Keyboard shortcuts

Press `?` in the UI for the same list.

| Key | Action |
|---|---|
| `0` | All builds (home) |
| `1`-`9` | Switch to firmware tab 1-9 |
| `f` / `m` / `t` | Flow / Messages / Timing view (timing when available) |
| `j` / `k` | Next / previous stage |
| `n` | Jump to the next alert |
| `c` | Collapse all expanded rows |
| `h` | Build history (press again, or Esc, to leave; Esc also closes a comparison) |
| up / down / left / right, Enter | Move, collapse/expand and select in the phase outline |
| left / right on the tab strip | Move between firmware tabs |
| Esc | Close dialog or popover |
| `?` | Show this list |

## Troubleshooting and FAQ

### vmon does not see my build

- vmon finds Vivado by looking for a running `vivado` process (`vivado.exe` on Windows). If the build runs on another machine, see [remote](#how-do-i-watch-builds-on-another-machine).
- A process belongs to a project when it runs inside `<X>.runs/<run>/`, or when its log (`-log <file>`, or `vivado.log` in its working directory) shows `open_project <path>.xpr` or `create_project`. With no project found, it becomes a standalone log firmware (non-project flow).
- On Windows, protected processes or ones owned by another user lack the command line and working directory, so vmon cannot place them.
- Add the run by hand: `vmon /path/to/proj.runs`, or the *Explore* button. Finished runs always need this unless they were watched before (the last 20 paths are remembered).
- vmon reads `runme.log`, `*.vds`, `*.vdi` and the reports, so a finished run needs no process once the files exist.

### I see old or wrong warnings after I relaunched the run

A relaunch (`reset_runs` then `launch_runs`) starts the run again in the same folder. Vivado runs project steps with `-applog`, so the new session is appended to the same `.vdi`/`.vds` log (the old one is also copied to `*.backup.vdi`). vmon reads the log as separate sessions: each new session replaces the earlier data from the step it starts at onward, so after a full rerun the steps it has not reached yet show nothing from the previous run, while a relaunch from a later step (`-from_step route_design`) keeps the steps it builds on. Report files older than the new run are marked stale and ignored. If you still see stale data, wait for the next poll (1 s by default) or reload the page.

### My run resumed from a checkpoint

A Vivado session that runs `open_checkpoint` on a run's checkpoint is shown as a new attempt of that run. Which step a checkpoint stands for is set in `[resume.checkpoints]`. If a run failed and no session log explains the later results, files newer than the failure (the `.bit`, a routed `.dcp`) are used as proof that steps finished outside the project flow (`[artifacts]`). See [configuration.md](configuration.md#failures-resumes-and-artifacts).

### My build uses a Tcl hook script

A section in the log that no step claims, such as a timing-closure loop in `STEPS.*.TCL.POST`, is shown as a `<cmd> (script)` command node inside the step that precedes it. Its messages count there, and its latest log timing wins over the step's own reports, because post-hooks run after them.

### Does it run on macOS?

Partly. There is no process discovery and no system stats on macOS. vmon prints a one-line notice, and paths you add by hand (`vmon /path/to/proj.runs`) work.

### The port is busy, or a firewall blocks it

- If something already uses port 8765, vmon tries the next 10 ports; the address it picked is printed on start (`vmon serving on http://127.0.0.1:8766`). Use `--port` to choose another.
- If a vmon is already running on the port, a new `vmon` command hands it your paths and opens the browser on it.
- vmon binds to `127.0.0.1`, so a local firewall normally does not matter. To reach it from another device use `--host`, or better an SSH tunnel. Remote builds need no extra open port either: vmon on the server stays on `127.0.0.1`.

### Can I try it without Vivado?

Yes. Serve `vmon/static/` with any static server and open `index.html?mock=1`, for example `python -m http.server 8798 --bind 127.0.0.1 --directory vmon/static`.

### Where does vmon keep its data?

Config in `~/.config/vmon/` (Windows: `%APPDATA%\vmon\`), cache in `~/.cache/vmon/` (Windows: `%LOCALAPPDATA%\vmon\`). The full list is in [configuration.md](configuration.md). vmon is read-only on your build directories.
