# Configuration

vmon ships with `vmon/flows.toml`. To change anything, create `~/.config/vmon/flows.toml` (or pass `--config FILE`). Your file is deep-merged over the defaults: tables merge key by key, lists and scalars are replaced. Tables with an `order` key are sorted by it, so you can add entries without touching Python.

Other files:

| Path | Purpose |
|---|---|
| `~/.config/vmon/flows.toml` | Overrides for `flows.toml` |
| `~/.config/vmon/catalog/` | Overrides for the phase catalog ([catalog.md](catalog.md)) |
| `~/.config/vmon/message_rules.json` | Your per-message priority overrides (written by the UI star/mute buttons) |
| `~/.cache/vmon/` | Recent paths, previous-build message baselines, step durations for ETA |

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
| `[timing_paths]` | Worst paths kept per timing report (`max_paths`) and how many go in the state JSON (`summary_paths`) |
| `[convergence]` | Router convergence: iteration phases, trend window and threshold, `route_not_converging` alert |
| `[eta]` | ETA: history size, band quantiles, small-sample margin, floor for a running step/phase, builds needed for high confidence |
| `[congestion]` | Congestion levels: warn and high thresholds, `congestion` alert, size/percent cell patterns |
| `[history]` | Build history: builds kept per firmware, messages kept per build, report kinds recorded, bitstream |
| `[notify]`, `[notify.desktop]`, `[notify.ntfy]`, `[notify.slack]`, `[notify.matrix]`, `[notify.webhook]` | Notifications outside the browser (all off by default) |
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

Because lists replace, copy the whole `[[messages.rules]]` list into your override file if you add rules there. The scoring weights live in `[messages.scoring]`. Individual messages can also be starred or muted in the UI; those overrides go to `~/.config/vmon/message_rules.json`, e.g. `{"Synth 8-327": "high", "Synth 8-7080": "mute"}`.

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

vmon can notify you with no browser open: desktop (`notify-send`), ntfy, Slack, Matrix or a generic webhook. Everything is off by default. Put it in `~/.config/vmon/flows.toml`; the UI only shows the status (bell, "Outside the browser").

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
command = "notify-send"    # or an argv list; "-u <urgency> -a vmon -- <title> <body>" is appended
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
| `desktop` | `command`, `urgency_error` | runs the program with an argv list, no shell |
| `ntfy` | `url`/`url_env`, `token`/`token_env`, `priority_*` | `POST` of the text, headers `Title`, `Priority`, `Tags`, optional `Authorization: Bearer` |
| `slack` | `webhook_url`/`webhook_url_env` | `POST` `{"text": "*title*\nbody"}` |
| `matrix` | `homeserver`, `room_id`, `access_token`/`access_token_env` | `PUT /_matrix/client/v3/rooms/<room>/send/m.room.message/<unique txn>` with `{"msgtype": "m.text", "body": ...}` |
| `webhook` | `url`/`url_env` | `POST` JSON `{firmware, fw_id, kind, code, level, title, body, t, project}` (see `SPEC.md`) |

Only events that happen while vmon runs are sent; builds already finished at startup are not. Logs and the API show only `scheme://host` of a URL, never its path, query or token. `POST /api/notify/test` (the "Send test" button) tests every enabled channel.
