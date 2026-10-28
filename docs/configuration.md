# Configuration

You are here: the reference for everything you can change. For how to use vmon day to day see the [user guide](guide.md); for how the pieces fit together see [architecture.md](architecture.md) and [catalog.md](catalog.md).

All Vivado-specific knowledge is data, not code: `vmon/flows.toml` (line rules, timing patterns, steps, report parsers, alert thresholds, docs links, message triage rules) and `vmon/catalog/vivado_<ver>.toml` (steps, phases and tasks per Vivado version).

vmon ships with `vmon/flows.toml`. To change anything, create `flows.toml` in the config dir (`~/.config/vmon/flows.toml` on Linux, `%APPDATA%\vmon\flows.toml` on Windows) or pass `--config FILE`. Your file is deep-merged over the defaults: tables merge key by key, lists and scalars are replaced. Tables with an `order` key are sorted by it, so you can add entries without touching Python.

Other files:

| Path | Purpose |
|---|---|
| `~/.config/vmon/flows.toml` (Windows: `%APPDATA%\vmon\flows.toml`) | Overrides for `flows.toml` |
| `~/.config/vmon/catalog/` (Windows: `%APPDATA%\vmon\catalog\`) | Overrides for the phase catalog ([catalog.md](catalog.md)) |
| `~/.config/vmon/message_rules.json` (Windows: `%APPDATA%\vmon\message_rules.json`) | Your per-message priority overrides (written by the UI star/mute buttons) |
| `~/.cache/vmon/` (Windows: `%LOCALAPPDATA%\vmon\`) | Recent paths, previous-build message baselines, step durations for ETA, history |

On Windows, if `%APPDATA%` or `%LOCALAPPDATA%` is unset vmon uses `~\AppData\Roaming\vmon` and `~\AppData\Local\vmon`. In the rest of this page `~/.config/vmon/` means the config dir of your platform.

## Sections

| Section | What it controls |
|---|---|
| `[severity]` | Log prefix to severity key |
| `[rules.*]` | Line rules: which log lines open commands, phases, tasks, messages |
| `[parse]` | Time/wall-clock/version regexes |
| `[timing.patterns.*]` | Log lines that carry WNS/TNS/WHS/THS |
| `[steps.*]` | Flow steps, their label and the Vivado commands that open them |
| `[runs.*]`, `[layout]` | Run classification and flow layout |
| `[reports.types.*]`, `[reports.utilization]`, `[reports.timing_columns]` | Report registry and table parsing |
| `[alerts]` | Alert thresholds |
| `[docs]`, `[docs.steps]`, `[docs.reports]` | Documentation link templates |
| `[ui]` | Utilization rows shown in the card |
| `[messages.*]` | Message triage scoring, keywords and rules |
| `[failure]`, `[failure.signals]`, `[failure.patterns.*]` | Crash and failure detection (segfault, lost license, out of memory, ...) |
| `[resume]`, `[resume.checkpoints]` | Recognising non-project sessions that resume a run from a checkpoint |
| `[hls]`, `[hls.processes]`, `[hls.parse]`, `[hls.settings]`, `[hls.timing]`, `[hls.steps.*]` | Vitis HLS: which processes are HLS (`vitis_hls`, `vitis-run`; `v++` as a wrapper), how `vitis_hls.log` is read (command, `Finished` and phase patterns), the HLS steps with their phases (`start_re`), the csynth report file and the estimated-timing patterns. New steps and phases are data only |
| `[nonproject]`, `[nonproject.reports]` | Non-project flows: how the `-source` Tcl script is read (size limit, `source` regex, banner patterns) and which `report_xxx` commands name a parsable report |
| `[timing_paths]` | Worst paths kept per timing report (`max_paths`) and how many go in the state JSON (`summary_paths`) |
| `[convergence]` | Router convergence: iteration phases, trend window and threshold, `route_not_converging` alert |
| `[eta]` | ETA: history size, band quantiles, small-sample margin, floor for a running step/phase, builds needed for high confidence |
| `[congestion]` | Congestion levels: warn and high thresholds, `congestion` alert, size/percent cell patterns |
| `[history]` | Build history: builds kept per firmware, messages kept per build, report kinds recorded, bitstream |
| `[[hints]]`, `[hints_config]` | Recommended actions: rule-based hints, built-in set, disabling by id |
| `[notify]`, `[notify.desktop]`, `[notify.ntfy]`, `[notify.slack]`, `[notify.matrix]`, `[notify.webhook]` | Notifications outside the browser (all off by default) |
| `[remote]` | Other vmon instances to aggregate (hosts, poll interval, timeout) |
| `[artifacts]`, `[artifacts.files]` | Files that prove a step finished when no log is available |

## Adding a timing pattern

Groups map positionally to `fields`; `N/A` becomes null.

```toml
[timing.patterns.my_summary]
order = 60
label = "My Summary"
contains = "My Timing Summary"          # cheap pre-filter
re = 'My Timing Summary \| WNS=(\S+) \| TNS=(\S+) \|'
fields = ["wns", "tns"]
```

## Mapping a report to a parser

`pattern` is a regex on the report filename with the `<top>_` prefix removed; `parser` is a built-in parser name (`utilization`, `timing`, `drc`, `power`, `route_status`, `control_sets`, `clock_utilization`, `generic`); `step` is the step that produced it.

```toml
[reports.types.utilization_postroute]
label = "Utilization"
order = 12
pattern = '^utilization_postroute\.rpt$'
kind = "utilization"
parser = "utilization"
step = "route_design"
```

Copy a neighbouring entry in `vmon/flows.toml` to see the exact keys for each parser.

## Message rules and keywords

The first matching rule wins. `match_id` is a regex on `Tool N-M`; `match_text` and `severity` (list) are optional. Priority is one of `critical`, `high`, `medium`, `low`, `mute`. INFO messages are never promoted, only demoted.

```toml
[[messages.rules]]
match_id = '^Synth 8-3332$'
match_text = 'my_debug_core'
priority = "low"
reason = "known: debug core trimmed"

[[messages.keywords]]
pattern = 'clock domain crossing'
bonus = 15
reason = "CDC"
```

Because lists replace, copy the whole `[[messages.rules]]` list into your override file if you add rules there. The scoring weights live in `[messages.scoring]`. Individual messages can also be starred or muted in the UI; those overrides go to `message_rules.json` in the config dir, e.g. `{"Synth 8-327": "high", "Synth 8-7080": "mute"}`.

### Sharing message rules

In the Messages view, **Export rules** downloads your ★/mute rules as a `vmon-message-rules` file (no host or user name is added; `exported_by` stays empty) and **Import rules…** previews a file before touching anything: what is added, changed (old to new priority) and, in replace mode, removed. *Merge* keeps your other rules and lets the file win on conflicts (tick *keep my priority* to reverse that); *replace* discards your current rules. A raw `message_rules.json` from a teammate is accepted as is. Invalid entries are listed and block the import. To share rules in a team, keep one exported file in git or a shared folder and have everyone import it (merge); there is no live shared file. Rules are per machine: with remote firmwares, import on the machine that builds.

## Recommended actions

`[[hints]]` entries are rules that turn the model into advice ("Suggested actions" in the recap card, and in the detail of the stage a hint is anchored to). They are data: add or change them without touching Python. A hint fires when all conditions of `when` hold; the UI shows the hint's static `text` (why it matters) and an `evidence` line vmon computes (for example `WHS -0.034 ns after Route Design (final)`).

```toml
[[hints]]
id = "my_rule"                 # unique; the same id as a built-in replaces that built-in
title = "Retry with explore"
severity = "info"              # "info" (accent) or "warning" (amber); never red
step = "route_design"          # optional: also shown in this stage's detail
text = "Why this matters."
actions = [
  {text = "Try this directive", command = "route_design -directive Explore", doc_url = "route_design"},
  {text = "Advice without a command"},
]
when = {timing = {final = true, wns_lt = 0}}
```

`doc_url` is a full URL, or a bare Tcl command name expanded with `[docs] tcl_command`. `command` gets a copy button.

Conditions (all optional, combined with AND; at least one is required):

| Key | Holds when |
|---|---|
| `alert_codes = [..]` | one of these alert codes is active (`timing_fail`, `congestion`, `route_not_converging`, ...) |
| `message_ids = [..]` | a warning-or-worse message with one of these ids exists; `*` and `?` are wildcards (`"DRC DPIP-*"`) |
| `message_re = "re"` | the text of a warning-or-worse message matches (searched in the aggregated message groups only) |
| `min_severity = "warning"\|"critical"\|"error"` | modifier: the message conditions of this table ignore lower severities |
| `failure_re = "re"` | a failed or stopped step's failure reason or details match |
| `status = [..]` | the build status is one of `idle queued running done failed stopped` |
| `step_done = "route_design"` | these steps are done (string or list) |
| `timing = {...}` | latest matching step timing: `final`, `stage` (step id or list), `wns_lt`, `tns_lt`, `whs_lt`, `ths_lt`. Stale (carried) values never match |
| `worst_path = {...}` | worst violated path(s) of that timing report: `type` (`setup`/`hold`), `top` (how many of the worst, default 1), and `route_pct_ge`, `logic_pct_ge`, `levels_ge`, `fanout_ge` (largest net fanout on the path). Uses the report picked by `timing` in the same table, else the latest (final first) |
| `congestion_level_ge = 5` | a step's worst congestion level is at least this |
| `convergence_trend = [..]` | a router step is `stalled`/`diverging`/`converging` after at least `[convergence] alert_min_iterations` iterations |
| `util_pct_ge = {any = 90}` | any resource in `[hints_config] util_any_resources` is at least 90% used; `{DSP = 85}` names one resource (all named ones must hold) |

`when.any` is a list of condition tables; at least one must hold, in addition to the keys next to it:

```toml
when = {timing = {final = true, wns_lt = 0}, any = [{worst_path = {type = "setup", logic_pct_ge = 60}}, {worst_path = {type = "setup", levels_ge = 10}}]}
```

An unknown condition or key, a bad regex, a bad severity or an empty `when` stops vmon at startup with a message naming the hint (`hint 'my_rule': unknown condition 'wns_below' ...`).

### Merging and disabling

Arrays of tables do not deep-merge like tables. Hints get their own rule so your file can add to the built-ins: hints are merged **by id**. A hint of yours with a new id is appended; one with the id of a built-in replaces that built-in completely (no field-by-field merge). Other arrays of tables, such as `[[messages.rules]]`, are replaced as a whole.

To switch built-ins off, list their ids. The list is united across `~/.config/vmon/flows.toml` and `--config`; an id that does not exist is an error, so typos are caught:

```toml
[hints_config]
disabled = ["oom_jobs", "high_utilization"]
util_any_resources = ["LUT", "FF", "BRAM", "DSP"]
```

Built-in ids: `hold_after_route`, `setup_route_dominated`, `setup_logic_dominated`, `high_fanout_worst_path`, `congestion_high`, `router_not_converging`, `oom_jobs`, `license_lost`, `latch_inferred`, `high_utilization`, `dsp_pipeline_registers`, `constraint_problem`. They follow AMD guidance (UG906, UG949, UG904) and only use documented commands and directives. Timing hints need final timing, so an estimate never produces advice.

## Alert thresholds

```toml
[alerts]
stall_minutes = 20                 # no log activity while running
utilization_pct = 90               # warn above this utilization
timing_error_steps = ["route_design", "post_route_phys_opt_design", "write_bitstream"]
timing_final_steps = ["route_design", "post_route_phys_opt_design"]
```

A negative slack is an error only when the timing is final; earlier values are warnings.

## Documentation links

Templates only. A value without `://` is a Tcl command name expanded with `tcl_command`; `{query}` is URL-encoded.

```toml
[docs]
tcl_command = "https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/{command}"
message_search = "https://www.google.com/search?q=site%3Adocs.amd.com+%22{query}%22"

[docs.steps]
opt_design = "https://docs.amd.com/r/en-US/ug904-vivado-implementation/opt_design"
write_bitstream = "write_bitstream"     # expands via tcl_command

[docs.reports]
utilization = "report_utilization"
```

## Failures, resumes and artifacts

A failed or crashed step gets a reason from the first matching `[failure.patterns.*]` entry (lowest `order`),
searched in the tail of `runme.log` and the main log. `{1}` in `reason` is the first regex group; with
`signal = true` it is translated through `[failure.signals]`.

```toml
[failure.patterns.disk_full]
order = 45
re = 'No space left on device'
reason = "Disk full"
```

A Vivado session that runs `open_checkpoint` on a run's checkpoint is shown as a new attempt of that run.
`[resume.checkpoints]` maps the checkpoint suffix to the step it was written after (longest suffix wins):

```toml
[resume.checkpoints]
"_routed" = "route_design"
```

If a run failed and no session log explains later results, files newer than the failure prove that steps
finished outside the project flow. `{top}` is the run's top module; `tolerance_s` absorbs filesystem timestamp skew:

```toml
[artifacts]
tolerance_s = 1
[artifacts.files]
'^{top}\.bit$' = "write_bitstream"
'^{top}_routed\.dcp$' = "route_design"
```

## ETA

```toml
[eta]
history_builds = 20           # completed builds kept per firmware
low_quantile = 0.10           # band = these quantiles of the per-build remaining time
high_quantile = 0.90
quantile_min_builds = 3       # fewer builds: min/max widened by small_sample_margin
small_sample_margin = 0.15
current_floor = 0.10          # a running step/phase keeps at least this fraction of its median
high_confidence_builds = 5    # with every remaining step known, gives "high" confidence
```

## Build history

```toml
[history]
max_builds = 100      # finished builds kept per firmware in ~/.cache/vmon/history/<fw_id>.json
max_messages = 500    # message ids (warnings and worse, worst first) stored per build for the comparison
bitstream = true      # record <top>.bit of the impl run when this build wrote it
kinds = ["timing_summary", "utilization", "drc", "methodology", "power", "route_status"]   # [] = every report kind
```

`kinds` values are the `kind` of `[reports.types.*]`. Only reports that are not stale are recorded, and they stay linked in the History page only while the file on disk is unchanged.

## Congestion

```toml
[congestion]
warn_level = 5     # worst level at or above this: amber "congestion" alert and CONG chip (Vivado: may impact timing)
crit_level = 7     # at or above this: the chip and bars turn orange (still only a warning alert)
alert = true       # warning "congestion"
```

The table rows and the final report are matched by `[rules.congestion_*]`; a region size `NxN` maps to level log2(N) (1x1 = 0, 8x8 = 3, 32x32 = 5). Estimates are never shown red.

## Router convergence

```toml
[convergence]
window = 3                 # iterations the trend looks at
min_improvement_pct = 20   # stalled = still > 0 and down by less than this over the window
alert = true               # warning "route_not_converging" (live attempts only)
alert_min_iterations = 4   # ...once this many iterations were seen
```

`diverging` means the final overlaps strictly increased over the window. The `Number of Nodes with overlaps` line is matched by `[rules.overlaps]`.

## Notifications outside the browser

vmon can notify you with no browser open: desktop (`notify-send` on Linux, a PowerShell toast on Windows), ntfy, Slack, Matrix or a generic webhook. Everything is off by default. Put it in `~/.config/vmon/flows.toml`; the UI only shows the status (bell, "Outside the browser").

Keep secrets out of files: every secret has an `*_env` twin that names an environment variable read when vmon starts sending (`url_env`, `token_env`, `webhook_url_env`, `access_token_env`). Start vmon with those variables set.

```toml
[notify]
enabled = true
kinds = ["step_failed", "run_failed", "run_done"]   # step_done, step_failed, run_done, run_failed
codes = ["timing_fail", "process_gone", "route_not_converging", "stalled", "congestion", "error"]
min_level = "error"        # alerts below this level (info < warning < error) are skipped; kinds are not affected
timeout_s = 5
max_per_minute = 20        # the excess is sent as one "N more events" message
title_prefix = "vmon"

[notify.desktop]
enabled = true
command = ""               # empty = notify-send (Linux) or a PowerShell toast (Windows); or a program / argv list that gets "-u <urgency> -a vmon -- <title> <body>" appended
urgency_error = "critical"

[notify.ntfy]
enabled = true
url_env = "VMON_NTFY_URL"  # e.g. https://ntfy.sh/my-private-topic, or your own server
token_env = "VMON_NTFY_TOKEN"   # optional, sent as a bearer token
priority_error = "urgent"       # also priority_info (default) and priority_warning (high)

[notify.slack]
enabled = true
webhook_url_env = "VMON_SLACK_WEBHOOK"
```

```sh
export VMON_NTFY_URL=https://ntfy.sh/my-private-topic
export VMON_SLACK_WEBHOOK=https://hooks.slack.com/services/...
vmon
```

| Channel | Settings | Request |
|---|---|---|
| `desktop` | `command`, `urgency_error` | runs the program with an argv list, no shell. Windows default: `powershell.exe -NoProfile -NonInteractive -EncodedCommand <fixed toast script>`; the title and body go in the environment (`VMON_TITLE`, `VMON_BODY`, cut to 256 and 2000 characters), never into the script text. An explicit `command` replaces it and gets the `notify-send`-style arguments |
| `ntfy` | `url`/`url_env`, `token`/`token_env`, `priority_*` | `POST` of the text, headers `Title`, `Priority`, `Tags`, optional `Authorization: Bearer` |
| `slack` | `webhook_url`/`webhook_url_env` | `POST` `{"text": "*title*\nbody"}` |
| `matrix` | `homeserver`, `room_id`, `access_token`/`access_token_env` | `PUT /_matrix/client/v3/rooms/<room>/send/m.room.message/<unique txn>` with `{"msgtype": "m.text", "body": ...}` |
| `webhook` | `url`/`url_env` | `POST` JSON `{firmware, fw_id, kind, code, level, title, body, t, project}` (see `SPEC.md`) |

Only events that happen while vmon runs are sent; builds already finished at startup are not. Logs and the API show only `scheme://host` of a URL, never its path, query or token. `POST /api/notify/test` (the "Send test" button) tests every enabled channel.

## Remote vmon instances

`[remote]` lists other vmons to show in this UI, usually the ones running on build servers, reached through an SSH tunnel. Nothing is contacted unless a host is listed (or `--remote` / `--ssh` is used).

```toml
[remote]
hosts = [
  {name = "buildsrv", url = "http://127.0.0.1:9001"},
  {name = "lab2",     url = "http://127.0.0.1:9002"},
]
interval_s = 3      # seconds between polls of each remote's /api/state
timeout_s = 5       # per request, polls and proxied requests alike
```

```sh
ssh -N -L 9001:127.0.0.1:8765 user@server      # on your machine; vmon on the server stays on 127.0.0.1
vmon                                           # or: vmon --remote buildsrv=http://127.0.0.1:9001
```

- `name`: `[A-Za-z0-9_-]{1,32}`, unique; it becomes the host badge and the prefix of firmware ids (`buildsrv~<id>`).
- `url`: `http://` or `https://`, `host[:port]` only (no credentials, path or query). It is shown in the UI as `scheme://host:port`.
- `--remote NAME=URL` adds to the list (a command-line entry replaces a config entry of the same name). `--ssh USER@HOST[:PORT]` picks a free local port, runs `ssh -N -o ExitOnForwardFailure=yes -L <port>:127.0.0.1:<PORT or 8765> USER@HOST` as a child process, registers it as a remote named after the host and ends it on exit; authentication is whatever your ssh does (keys or agent; a prompt appears in the terminal).
- Redirects are refused and environment proxies (`http_proxy`) are ignored. The remote is always taken from this config, never from a request.
- Notifications outside the browser are sent by each machine's own vmon; the browser notifications of this UI cover remote events too. `/api/msgrule`, `/api/msgrules/*`, `/api/notify`, `/api/watch` and `/api/browse` act on this machine only.
