# vmon — Vivado live run monitor: architecture contract

Project root: the repository root (`vivado-monitor/`)
Python 3.11+ (stdlib only at runtime — NO third-party runtime deps; pytest only for tests, in `.venv`).
Linux only (reads /proc directly).

## Layout
```
vivado-monitor/
  pyproject.toml            # entry point: vmon = "vmon.cli:main"
  requirements-dev.txt      # pytest==<pinned>
  vmon/
    __init__.py
    __main__.py             # python -m vmon
    cli.py                  # argparse: [paths...] --port 8765 --host 127.0.0.1 --interval 1.0 --no-browser --config FILE
    config.py               # loads vmon/flows.toml + optional ~/.config/vmon/flows.toml (deep-merge, user wins)
    flows.toml              # ALL Vivado-specific knowledge lives here (steps, regexes, labels)
    discovery.py            # find vivado processes, group them into Firmwares
    logtail.py              # incremental file reader (keeps offset+inode; handles truncation/rotation)
    logparse.py             # streaming parser: lines -> sections/phases/messages/timing
    model.py                # dataclasses + to_dict() producing the JSON below
    project.py              # builds a Firmware's flow from a .runs dir (markers, run tcl, logs, reports)
    reports.py              # parse *_timing_summary_*.rpt (Design Timing Summary table)
    server.py               # http.server ThreadingHTTPServer: static files + JSON API + SSE
    monitor.py              # background thread: every interval -> discover, update parsers, publish state
    static/                 # index.html, app.js, style.css (frontend, no build step)
  tests/
    fixtures/               # small log/report snippets copied (read-only!) from real runs
    test_*.py
```

## Data sources (all READ-ONLY)
- Processes: scan /proc/*/comm == "vivado" (the unwrapped binary). Read /proc/PID/cmdline, /proc/PID/cwd, ppid from /proc/PID/stat.
  - If cwd is `<X>.runs/<run>/` → belongs to project `<X>.runs` (firmware name = X), run = `<run>`.
  - Else (launcher / non-project batch): look for `-log <file>` in cmdline (else cwd/vivado.log). Scan that log for
    `open_project <path>.xpr` → project `<dir of xpr>/<stem>.runs`. Also: any vivado descendant whose cwd is in a .runs dir
    ties the launcher to that project. If nothing found → standalone "log" firmware (non-project flow), parsed from that log.
  - Launcher info (pid, log path, script from `-source`) is kept as `launcher` on the firmware.
- Run dir files (project mode), for run dir R:
  - `R/.<step>.begin.rst`, `.<step>.end.rst`, `.<step>.error.rst` → step status + start/end time (mtime). `vivado` step = whole run.
  - `R/.Vivado_Implementation.queue.rst` / `.Vivado_Synthesis.queue.rst` → run queued.
  - `R/__synthesis_is_complete__` → synth done.
  - `R/<top>.tcl`: lines `start_step <name>` give the PLANNED step list for impl runs (only enabled steps appear!).
  - `R/gen_run.xml` (GenRun Id, LaunchTime) ; `R/runme.log` ; main log = `<top>.vds` (synth) or `<top>.vdi` (impl).
  - `<X>.runs/.jobs/vrs_config_<N>.xml` with highest N (by mtime) = the runs of the CURRENT launch (Run Id, FlowId
    Vivado_Synthesis/Vivado_Implementation, Parent ids). If missing: use synth_1/impl_1-like dirs present.
  - Reports: `R/<top>_timing_summary_routed.rpt`, `_postroute_physopted.rpt`, `_physopted.rpt`, `_placed`... → table under
    "| Design Timing Summary": columns WNS TNS TNSfail TNStotal WHS THS THSfail THStotal WPWS TPWS ...
- The current live example: ~/projects/lockin/lockin.runs (impl_1 running place_design;
  synth_1 done; ~90 OOC IP runs most from older launches, only lockin_iq_multiplier_0_0_synth_1 in the current launch).
  Finished example: ~/projects/qick_firmwares/top/top.runs (full impl with timing report).

## Log grammar (handled by regexes in flows.toml)
- Messages: `^(INFO|WARNING|CRITICAL WARNING|ERROR): \[(<Tool> <id>)\] text` ; also bare `^ERROR:` / `^WARNING:` lines.
  Count per section; keep per-ID aggregation {id, severity, count, first_text, first_line, last_line}; keep the last 200
  message instances per section (severity>=WARNING always kept up to 2000 per section).
- Command sections: `^Command: (\S+)` starts a section. flows.toml maps command → step id:
  synth_design→synth_design, link_design→init_design, opt_design→opt_design, place_design→place_design,
  phys_opt_design→phys_opt_design, route_design→route_design, write_bitstream→write_bitstream.
  Other commands (report_*, write_checkpoint, ...) become child "command" nodes of the current step.
- Phases: `^Phase (\d+(?:\.\d+)*) (.+?)( \| Checksum: \w+)?$` — opening line without Checksum starts phase; same number with
  Checksum ends it. Nesting by dotted number depth. Also `^Starting (.+) Task$` / `^Ending (.+) Task` (task nodes),
  and synth `^Start (.+?)\s*$` / `^Finished (.+?)( : Time.*)?$` pairs.
- Resources: `Time \(s\): cpu = (\S+) ; elapsed = (\S+) \. Memory \(MB\): peak = ([\d.]+)` → attach elapsed/peak mem
  to the innermost open node.
- Step end summary: `^(\d+) Infos, (\d+) Warnings, (\d+) Critical Warnings and (\d+) Errors encountered.`
  and `^<cmd> completed successfully` / `^<cmd> failed`.
- Timing (each match appended to the current step's timing.history with label = pattern name):
  - `Estimated Timing Summary \| WNS=(\S+) \| TNS=(\S+) \|`
  - `Post Placement Timing Summary WNS=([-\d.]+)`
  - `Intermediate Timing Summary \| WNS=(\S+)\s*\| TNS=(\S+)\s*\| WHS=(\S+)\s*\| THS=(\S+)\s*\|`
  - `Post Routing Timing Summary \| WNS=...` (same groups)  → "final" for route
  - `Post Physical Optimization Timing Summary \| WNS=(\S+) \| TNS=(\S+) \|`
  - values "N/A" → null. met = (wns>=0 and (tns==0 or null)) and (whs is null or whs>=0).
  - When a timing_summary report exists for a step it overrides log-derived latest (source="report").
- Wall-clock times: `^\[(\w{3} \w{3} +\d+ [\d:]+ \d{4})\]` lines and marker-file mtimes.

## JSON API (contract between backend and frontend)
- `GET /` → static/index.html ; `/static/*`
- `GET /api/state` → State
- `GET /api/events` → SSE; event `state` with full State JSON whenever it changes (check every interval; send
  heartbeat comment every 15 s). Frontend reconnects automatically.
- `GET /api/messages?fw=<fw_id>&node=<node_id>&sev=error,critical,warning,info&limit=500` → {node_id, groups:[MsgGroup], items:[Msg]}
  (node may be a step or a phase; messages of a node include its descendants)
- `GET /api/log?fw=<fw_id>&node=<node_id>&tail=200` → {path, start_line, end_line, lines:[str]} (raw log excerpt for that node;
  for a running node, its last `tail` lines)
- `GET /api/report?fw=<id>&path=<report path>` → text/plain raw report (only paths listed in some node's `reports`; 403 otherwise)
- `POST /api/watch` body {"path": "..."} → add a .runs dir / .xpr / log file to watch (also via CLI args).
- `DELETE /api/firmware?fw=<id>` → forget a finished firmware from the UI list (does not touch disk).

```
State = {
  "generated_at": float epoch,
  "version": 1,
  "firmwares": [Firmware]            # sorted: running first, then most recently updated
}
Firmware = {
  "id": str (stable short hash of project/log path),
  "name": str ("lockin"),
  "kind": "project" | "log",
  "path": str (.runs dir or log path),
  "status": "queued"|"running"|"done"|"failed"|"stopped"|"idle",   # stopped = process gone but not finished
  "live": bool,                      # any vivado process alive for it
  "pids": [int],
  "launcher": {"pid": int|null, "log": str|null, "script": str|null} | null,
  "started_at": float|null, "updated_at": float|null, "elapsed_s": float|null,
  "current": {"node_id": str, "label": str} | null,   # deepest currently running node, for tab/header display
  "counts": Counts,                  # whole firmware (current launch)
  "timing": Timing|null,             # latest known timing for the firmware
  "flows": [Flow],                   # normally 1; >1 if several impl runs in the launch
  "alerts": [Alert], "health": "ok"|"warning"|"error",
  "progress_estimate": float|null,   # 0..1 from catalog weights
  "vivado_version": str|null
}
Flow = { "id": str, "label": str ("impl_1"), "stages": [Node] }
Node = {
  "id": str (unique within firmware, path-like e.g. "impl_1/place_design/p2/p2.1"),
  "label": str, "kind": "group"|"run"|"step"|"command"|"phase"|"task",
  "status": "pending"|"queued"|"running"|"done"|"failed"|"skipped"|"stopped",   # stopped = process gone mid-run
  "started_at": float|null, "ended_at": float|null, "elapsed_s": float|null,
  "peak_mem_mb": float|null,
  "counts": Counts,
  "timing": Timing|null,
  "run": str|null, "log": str|null, "line_start": int|null, "line_end": int|null,
  "progress": {"done": int, "total": int} | null,     # e.g. OOC group: 1/1 runs; step: phases done
  "expected": bool, "optional": bool, "description": str|null,   # expected=true: catalog placeholder not seen yet
  "estimate": {"weight": float}|null,                            # catalog weight (share of parent)
  "reports": [Report], "alerts": [Alert],
  "children": [Node]
}
Counts = {"error": int, "critical": int, "warning": int, "info": int}
Timing = {"wns": float|null, "tns": float|null, "whs": float|null, "ths": float|null,
          "tns_fail": int|null, "ths_fail": int|null, "met": bool|null,
          "source": "log"|"report", "label": str, "history": [{"t": float|null, "line": int, "label": str,
          "wns":..., "tns":..., "whs":..., "ths":...}] }
Alert = {"level": "error"|"warning", "code": "timing_fail"|"critical_warning"|"error"|"drc"|"unrouted"|"stalled"|
         "step_failed"|"process_gone"|"utilization", "message": str, "node_id": str}
Report = {"name": str, "kind": str, "path": str, "mtime": float, "stale": bool,   # stale = older than the step's begin marker
          "summary": {...}, "alerts": [{"level","code","message"}]}   # stale reports never alert
  summary by kind:
    utilization:      {rows:[{name, label, used, available, pct}]}          (LUT FF BRAM URAM DSP IO BUFG)
    drc|methodology:  {counts:{error,critical,warning,info}, rules:[{id,severity,count,message}], rule_count}
    timing_summary:   {wns,tns,whs,ths,tns_fail,ths_fail,wpws,..., clocks:[{name,period,wns,tns,tns_fail,whs,ths}]}
    power:            {total_w, dynamic_w, static_w, junction_c, confidence}
    route_status:     {routable, fully_routed, unrouted, routing_errors, ...flat counts}
    control_sets:     {control_sets}; clock_utilization: flat {primitive: "used / available"}; others: {}
MsgGroup = {"id": "Timing 38-35", "severity": "info"|"warning"|"critical"|"error", "count": int, "text": str, "first_line": int, "last_line": int}
Msg = {"severity": str, "id": str|null, "text": str, "line": int}
```

Project-mode flow layout (default; configured in flows.toml so it is not hard-coded):
1. stage "Synthesis" (kind group): children = one "run" node per synthesis run in the current launch (OOC IP runs first,
   collapsed into a sub-group "IP out-of-context (n)" when n>0, then synth_1). Each synth run node children = synth phases.
2. then each impl step (kind step) of the impl run, in `start_step` order: init_design, opt_design, place_design,
   phys_opt_design, route_design, (post_route_phys_opt_design), write_bitstream. Steps not yet begun = pending.
   Children = command nodes / phase / task nodes parsed from the .vdi section.
Log-mode (non-project): stages = steps found by command mapping (synth_design, opt_design, ...) in log order; planned
list from flows.toml default_order with not-seen ones pending only if the process is still alive.

## Performance
- Incremental parsing: each log parsed once; subsequent ticks read only appended bytes. Restart from 0 if inode changes
  or size shrinks (run reset). Logs can be 100k+ lines — never re-read whole files per tick.
- Discovery scan of /proc each tick is fine (cheap). Stat marker files each tick.
- State JSON excludes message lists (served on demand).
- Forgotten firmwares persisted in ~/.cache/vmon/state.json? -> just keep a list of known paths in
  ~/.cache/vmon/recent.json so finished runs re-appear after restart (last 20, ignore missing paths).

## Safety (must follow)
- NEVER write/delete/move anything under firmware dirs or Vivado dirs; NEVER signal/kill processes. Read-only.
- Only write inside the project dir, the scratchpad, and ~/.cache/vmon/.
- No git operations. No secrets in output. No global pip installs (use the project .venv).
- Server binds 127.0.0.1 by default.


## Backend notes (added with the implementation)
- Config split: `vmon/flows.toml` = engine regexes (line rules, timing patterns), run classification, report
  registry (`[reports.types]`: filename pattern -> parser -> step), alert thresholds. `vmon/catalog/vivado_<ver>.toml`
  (schema in its README) = source of truth for steps (label/command/flow), expected phases/tasks/stages, descriptions
  and weights; it is overlaid onto flows.toml steps at start-up. User overrides: `~/.config/vmon/flows.toml`,
  `~/.config/vmon/catalog/`. Catalog is picked by the log's "Vivado vX.Y" header (nearest older, else oldest).
- Expected nodes: matched to seen nodes by NAME (numbers ignored). Unseen => `status:"pending"`, `expected:true`
  (finished step: optional ones dropped, others `skipped`). `plan_mode=dynamic` steps and finished/cached-IP synth runs
  only get annotations (description/optional/estimate), no placeholders.
- Phase `elapsed_s` is the difference of the log's cumulative "Time (s)" readings (reset per task/step).
- Alerts: `[alerts]` in flows.toml (stall_minutes, utilization_pct, timing_error_steps). Negative WNS/WHS is an error once
  a step in `timing_error_steps` is done, a warning for earlier/estimated values.
- Firmware.health = worst alert level. progress_estimate = catalog-weighted step fractions (synth weight capped at 25% of impl).
- Large launches: done OOC synth runs omit their phase children when more than `ooc_collapse_children_above` runs exist.

## v2 additions (2026-10-20) — contract for this round

### State additions
```
State.system = {"cpu_pct": float, "cpu_count": int, "load1": float,
                "mem_used_mb": float, "mem_total_mb": float, "swap_used_mb": float, "swap_total_mb": float}
                # from /proc/stat (delta between ticks), /proc/loadavg, /proc/meminfo (used = MemTotal - MemAvailable)
State.settings = {"interval": float}            # current monitor tick period, seconds
State.tick = int; State.generated_at = epoch    # SSE also pushes when only `system` changed (at most every interval)
Firmware.resources = {"cpu_pct": float, "rss_mb": float} | null   # summed over Firmware.pids (+ descendants)
Firmware.utilization = {"step": str, "label": str, "report": str (name), "path": str,
                        "rows": [{"name","used","available","pct"}]} | null
     # latest NON-stale utilization report (routed > placed > synth); rows limited to headline resources
     # listed in flows.toml [ui] headline_resources = ["LUT","FF","BRAM","URAM","DSP","IO","BUFG"]
Firmware.top_messages = [TriageGroup] (top 5 non-muted, severity >= warning)
Firmware.events = [{"t": epoch, "kind": "step_started"|"step_done"|"step_failed"|"run_done"|"run_failed"|"alert",
                    "level": "info"|"warning"|"error", "code": str|null, "node_id": str|null,
                    "title": str, "message": str}]   # last 100, newest last; drives browser notifications + in-app log
```

### Message triage
- Rules in `vmon/flows.toml` `[[messages.rules]]`: `{match_id = regex on "Tool N-M" id, match_text = regex (optional),
  priority = "critical"|"high"|"medium"|"low"|"mute", reason = str}`; `[messages.keywords]` list of `{pattern, bonus, reason}`;
  `[messages.scoring]` weights. User overrides: `~/.config/vmon/message_rules.json` = {"<id>": "high"|"mute"|...}
  written via API (the ONLY file the tool writes besides ~/.cache/vmon/).
- score = severity_base + priority_bonus + keyword_bonus + rarity_bonus + novelty_bonus (weights in TOML).
- Novelty: when a run of a firmware finishes (done/failed), store {id: count} to `~/.cache/vmon/msgs/<fw_id>.json`
  as the "previous build" baseline (rotate: keep previous + current). A group is `new` if its id was absent from the
  baseline; `delta` = count - baseline count. No baseline → new=false for all (`baseline: false` in response).
```
TriageGroup = {"id": str, "severity": str, "count": int, "text": str (first instance), "score": float,
               "priority": str|null, "user_priority": str|null, "reasons": [str], "new": bool, "delta": int|null,
               "nodes": [{"node_id","label"}] (steps where it occurs), "first_line": int, "last_line": int, "log": str}
GET  /api/triage?fw=&node=(optional)&sev=error,critical,warning,info&q=text&include_muted=0&limit=500
     -> {"baseline": bool, "groups": [TriageGroup] sorted by score desc}
GET  /api/messages?fw=&node=&id=<msg id>&limit=   (new optional `id` filter; node optional = whole firmware)
GET  /api/log?fw=&log=<path>&around=<line>&context=30   (log excerpt around a line; path must be a known log)
POST /api/msgrule {"id": "Synth 8-327", "priority": "high"|"mute"|null(=remove)}
POST /api/settings {"interval": 0.5..60}
```

### v2 implementation notes (deviations / detail)
- `[messages.keywords]` is an array of tables: `[[messages.keywords]]` (TOML cannot mix table and array under one name).
  Rules also accept an optional `severity = [..]` list (e.g. DRC warnings are medium, DRC critical/error are high);
  first matching rule wins. INFO messages are never promoted (priority/keyword/rarity/novelty bonuses ignored, only demotions).
- Default `sev` for /api/triage and top_messages is `error,critical,warning`. TriageGroup also carries `muted`.
- Utilization rows also carry `label` (original table row name); step = label of the node owning the report.
- State also has `tick`; `system`/`settings` are in State root. SSE is pushed on every tick where anything changed
  (system stats change nearly every tick). POST /api/settings wakes the monitor loop immediately (tick now, new period after).
- Message items from /api/messages carry `log` (path); node is optional (whole firmware). /api/log `around` needs `log=` (or `node=`).
- Baseline file `~/.cache/vmon/msgs/<fw_id>.json` = {"current": {"build","counts"}, "previous": {...}}; build key = int(started_at).
  A finished build is also stored at start-up when not yet recorded (so the next build has a baseline); the build key makes this idempotent.
- Events: nodes tracked = steps and non-OOC synth runs; alerts are de-duplicated by (node, code, message with numbers masked).
- `~/.config/vmon/message_rules.json` is only created on the first override; removing the last override leaves `{}`.

## v3 additions (2026-10-20) — contract for this round
```
Timing.final: bool        # true only for: timing_summary report of route_design / post_route_phys_opt_design,
                          # "Post Routing Timing Summary", or any timing once route_design is done.
                          # Estimates/intermediate (place, phys_opt, route Intermediate) -> false.
Timing.stage: str         # human label of where it comes from, e.g. "Route · intermediate", "Place · estimate", "Route · final report"
Alerts: timing_fail is level "error" ONLY when Timing.final and not met; otherwise level "warning" with message
        stating it is an intermediate/estimated value (e.g. "WHS -0.135 ns (intermediate, route not finished — hold
        fixing usually comes later)"). Firmware.health must follow the same logic.
Firmware.eta = {"expected_end": epoch|null, "remaining_s": float|null,
                "method": "previous build"|"catalog weights"|null, "confidence": "low"|"medium"|"high"} | null
     # previous build: per-step durations of the last completed build of the same firmware, stored in
     #   ~/.cache/vmon/durations/<fw_id>.json when a build finishes (also recorded at startup for finished builds);
     #   remaining = sum(durations of pending steps) + max(prev_dur(current) - elapsed(current), 10% of prev_dur).
     # fallback: catalog weights scaled by elapsed / progress_estimate (confidence low).
Firmware.info = {"part": str|null, "board": str|null, "top": str|null, "vivado_version": str|null,
                 "host": str|null, "strategy_synth": str|null, "strategy_impl": str|null,
                 "directives": {"<step>": "<directive>"}, "jobs": int|null, "project": str|null (xpr path)}
     # part from gen_run.xml LaunchPart / "-part" in Command lines; board from .xpr <Option Name="BoardPart" Val=...>;
     # strategies from .xpr <Run Id=... Strategy=...> ; directives from "Command: <cmd> -directive X"; host from .vivado.begin.rst.
Docs links (configurable URL templates in flows.toml [docs]):
  Node.doc_url: str|null      # e.g. AMD UG904/UG901 page for the step command / UG835 Tcl command page
  TriageGroup.doc_url, MsgGroup.doc_url: str|null   # search URL for the message id on AMD docs/support
  Report.doc_url: str|null    # UG906 page for that report command
```

### v3 implementation notes (deviations / detail)
- Finality: `[alerts] timing_final_steps = [route_design, post_route_phys_opt_design]` (their timing_summary reports are final; log
  timing there is final too, except route_design before it is done unless the label is "Post Routing"); `timing_error_steps` still means
  "any timing is final once that step is done". Stage text: "<Step> · estimate|intermediate|final|report|final report".
  Final violation message ends with "(final)"; non-final: "WHS -0.135 ns - intermediate value during Route Design, not final
  (hold fixing usually comes later in route)" ("estimated" instead of "intermediate" for place/phys_opt estimates).
- ETA: only for running builds. Durations file = {"build","total_s","steps":{step_id: s}} of the last completed build (synth under
  "synth_design"; stored beside recent.json in `durations/`). Confidence "medium" with a previous build ("low" if a pending step has no
  recorded duration), "low" for catalog weights. Never computed for finished builds (eta null).
- Info: `jobs` from the impl Run `LaunchOptions` in the .xpr, else `set_param runs.launchOptions` in the run tcl (the launcher log is not
  used). `directives` come from `Command:` lines in the impl log (second phys_opt/power_opt command maps to the post-route/post-place step).
  Files parsed by mtime/size (log incrementally). Log-mode firmwares get only part/top/version/directives.
- Docs: `[docs]` in flows.toml (`tcl_command`, `message_search`, `[docs.steps]`, `[docs.reports]`); a value without "://" is a Tcl command
  name expanded with `tcl_command`. Nodes inherit their step's URL (report-command children get their UG835 page). Verified (page title
  checked): UG835 `/<command>` for all listed commands; UG904 `/opt_design`, `/power_opt_design`, `/phys_opt_design`, `/route_design`,
  `/place_design-for-UltraScale-and-7-Series`; UG901 `/Running-Synthesis` (UG901 `/synth_design` is 404, so synth uses Running-Synthesis).
  `docs.amd.com` search URLs could not be found (all candidates 404), so `message_search` is a Google `site:docs.amd.com "<id>"` query.

## v4 additions (2026-10-20) — contract for this round
```
Timing carry-forward: when the newest timing line/report lacks a metric (e.g. Estimated Timing Summary has only
  WNS/TNS, Intermediate has WHS=N/A), keep the previous known value of that metric (within the same firmware build,
  newest first: same step, then earlier steps) instead of null, and list it in
  Timing.carried = {"whs": {"label": "Route · intermediate", "line": int|null, "t": epoch|null}, ...}   # {} if none
  met/alerts use carried values too (a carried negative WHS still counts but message says "(from <label>)").
  Applies to Firmware.timing and every Node.timing. History entries stay raw (no carry).
Expected-phase numbering: when merging catalog children, predict numbers: walking siblings in catalog order, keep the
  last seen number; each non-optional expected sibling gets last+1 (dotted under the parent number, e.g. "2.3"),
  label formatted like real ones ("3 Detail Placement"); optional expected siblings get no number and do not advance
  the counter. Node.number: str|null, Node.number_predicted: bool.
GET /api/browse?path=<dir>   (default: $HOME)  -> {"path": abs, "parent": abs|null, "home": abs,
    "entries": [{"name","path","type":"dir"|"file","kind": "runs"|"run"|"xpr"|"log"|"project_dir"|null,
                 "mtime": epoch, "live": bool}], "recent": [abs paths from recent.json]}
    # read-only listing; hidden entries skipped except none; dirs + only relevant files (*.xpr, *.log, *.vdi, *.vds,
    # runme.log); kind detection: "<X>.runs" dir → runs; dir containing runme.log/gen_run.xml → run; dir containing
    # a *.xpr → project_dir; sorted dirs first by name; max 2000 entries; 403 for unreadable; never follows into
    # special filesystems (/proc, /sys, /dev).
```

### v4 implementation notes (deviations)
- Carry-forward applies only to `whs`/`ths` (not `wns`/`tns`: a setup value from another pass would contradict the
  new WNS). Order: earlier lines of the same step, then earlier steps/flows (pool is newest-first); report-sourced
  timing is never carried (it only feeds the pool). Carried alerts are warnings: "WHS -0.135 ns during Route (...) (from Route · intermediate)".
- Predicted numbers only for `phase` entries of unfinished steps (placeholders of done/failed/stopped steps are
  "skipped" and stay unnumbered); real numbers come from the log (`number_predicted=false`).
- /api/browse: `live` also marks a live firmware's project dir, run dirs and `.xpr`; kind detection peeks one level
  (max 300 dirs x 200 entries per request); 404 if not a directory; `recent` = currently watched paths.
