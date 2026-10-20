# vmon catalog

Declarative description of every step, phase and task a Vivado run can go through, so the UI can show what is still to come, not just what has run. One file per Vivado version: `vivado_<major>.<minor>.toml`. Mined from real 2023.2 logs (UltraScale+ RFSoC only), the install's `strategies/VDI2023.psg`, and generated run tcl files. Nothing here is code.

## Schema (schema = 1)

`[catalog]`: `vivado`, `families_seen`, `logs_mined`.

`[[step]]` (one per run step, in flow order; `synth_design` is the synth run, the rest are impl):

| key | meaning |
|---|---|
| `id` | step id; equals the `start_step` name in the run tcl (`synth_design` for synth) |
| `run` | `synth` or `impl` |
| `command` | text after `Command: ` in the log that opens the step (note `link_design` is `init_design`, and both power steps use `power_opt_design`, `post_route_phys_opt_design` uses `phys_opt_design`: disambiguate with the planned step order from the run tcl) |
| `label`, `description` | UI label and tooltip |
| `optional`, `enable`, `default_enabled`, `enabled_by_strategies` | whether the step may be absent, the run property that toggles it (`STEPS.<X>.IS_ENABLED`) and its default. Only steps with `start_step` in the run tcl are really planned |
| `plan_mode` | `static`: show unseen phases as pending. `dynamic`: phase list depends on directive/timing (phys_opt, power opt); show only phases as they appear |
| `weight`, `weight_src` | share of the run time (`measured` from log medians, `guess` otherwise). Renormalise over the enabled steps |
| `reports` | files produced, `{top}` is the top module name; `report=false` for checkpoints/bitstreams. `metrics` lists what is worth surfacing |
| `tasks` | `Starting/Ending <name> Task` blocks (opt_design, place_design, phys_opt) |
| `phases` | `Phase <n> <name>` blocks. `level` is nesting depth, `parent` the parent name |
| `sections` | synth only: `Start/Finished <name>` markers (`marker` = `both`, `starting` or `finish_only`) |
| `stages` | write_bitstream: plain lines identified by a `match` regex |
| `events` | repeatable sub-events shown as a counter (XDC file parsing) |

Phase/task keys: `name` (the matching key), `n` (typical number, informational), `optional` (true = may be missing, do not flag a run as incomplete), `weight` (share of the parent step, siblings sum to about 100), `repeat`/`repeat_max` (pass can occur several times), `alt_numbers` (number when an optional earlier phase shifts numbering), `occurrence` (n-th time the same name appears), `pattern` (regex on name for numbered families like `Global Iteration N`), `desc`.

IMPORTANT: match phases by NAME, not number. Numbers shift with directive and device (opt_design Phase 8 is `Remap` or `Post Processing Netlist`; place_design 2.2 changes meaning).

`[[pattern]]`: log-line regexes in Python `re` syntax with named groups. `kind` is `timing`, `metric`, `flag`, `info`, `block_start` or `structure`; `applies_to` lists step ids; `example` is a real line (all examples are tested). `final = true` marks the timing line that is the step's end result. `N/A` in a captured value means not available yet. Note `Time (s): ... elapsed` after a phase is cumulative since the step start, so subtract the previous value to get a phase duration.

## Adding a version or override

- New version: copy `vivado_2023.2.toml` to `vivado_<ver>.toml`, change `[catalog] vivado`, run a few logs through the validation idea below, and edit only what differs. The loader should pick the file by the `# Vivado v<ver>` header of the log, falling back to the closest older one.
- User override: put a file with the same name in the user config dir (proposed `~/.config/vmon/catalog/`). Merge rule: `[[step]]` entries merge by `id`, `phases`/`tasks`/`sections`/`stages`/`reports` entries merge by `name` (or `file`), `[[pattern]]` by `id`; scalar keys in the override win. To remove an entry set `disabled = true` on it.
- Checking a catalog: parse it with `tomllib`, compile every `regex`, apply them to real logs, and diff the set of `Phase`/`Task` names found in the logs against the catalog (unknown names should be shown in the UI anyway, just as unplanned).

## Caveats

- Only UltraScale+ RFSoC logs were available. Versal (`write_device_image`), 7-series, SLR-specific phases and the power-opt steps are from the install files or general knowledge (`evidence = "install"`/`"doc"`), not logs.
- Synth section timers cover only ~20% of synth_design wall time; use synth weights for ordering, not for a time estimate.
- phys_opt phase lists are the longest sequence seen (AggressiveExplore); the default directive runs a subset, and with no violations it runs none.
