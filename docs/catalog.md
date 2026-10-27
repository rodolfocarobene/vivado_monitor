# Phase catalog

Declarative description of every step, phase and task a Vivado run can go through, so the UI can show what is still to come, not just what has run. One file per Vivado version: `vivado_<major>.<minor>.toml`. Mined from real 2023.2 logs (UltraScale+ RFSoC, plus a few tiny 7-series builds), the install's `strategies/VDI2023.psg`, and generated run tcl files. Nothing here is code.

## Schema (schema = 1)

`[catalog]`: `vivado`, `families_seen`, `logs_mined`, `family_map` (see Device families).

`[[step]]` (one per run step, in flow order; `synth_design` is the synth run, the rest are impl):

| key | meaning |
|---|---|
| `id` | step id; equals the `start_step` name in the run tcl (`synth_design` for synth) |
| `run` | `synth` or `impl` |
| `command` | text after `Command: ` in the log that opens the step (note `link_design` is `init_design`, and both power steps use `power_opt_design`, `post_route_phys_opt_design` uses `phys_opt_design`: disambiguate with the planned step order from the run tcl) |
| `label`, `description` | UI label and tooltip |
| `optional`, `enable`, `default_enabled`, `enabled_by_strategies` | whether the step may be absent, the run property that toggles it (`STEPS.<X>.IS_ENABLED`) and its default. Only steps with `start_step` in the run tcl are really planned |
| `device_families` | optional list; the step only applies to these families (`write_bitstream` is not planned on Versal, `write_device_image` only there). Matters only when vmon has to guess the step list; a run tcl or script that names its steps wins |
| `plan_mode` | `static`: show unseen phases as pending. `dynamic`: phase list depends on directive/timing (phys_opt, power opt); show only phases as they appear |
| `weight`, `weight_src` | share of the run time (`measured` from log medians, `guess` otherwise). Renormalise over the enabled steps |
| `reports` | files produced, `{top}` is the top module name; `report=false` for checkpoints/bitstreams. `metrics` lists what is worth surfacing |
| `tasks` | `Starting/Ending <name> Task` blocks (opt_design, place_design, phys_opt) |
| `phases` | `Phase <n> <name>` blocks. `level` is nesting depth, `parent` the parent name |
| `sections` | synth only: `Start/Finished <name>` markers (`marker` = `both`, `starting` or `finish_only`) |
| `stages` | write_bitstream: plain lines identified by a `match` regex |
| `events` | repeatable sub-events shown as a counter (XDC file parsing) |

Phase/task keys: `name` (the matching key), `n` (typical number, informational), `optional` (true = may be missing, do not flag a run as incomplete), `weight` (share of the parent step, siblings sum to about 100), `repeat`/`repeat_max` (pass can occur several times), `alt_numbers` (number when an optional earlier phase shifts numbering), `occurrence` (n-th time the same name appears), `pattern` (regex on name for numbered families like `Global Iteration N`), `families` (optional list: the entry is only expected on these device families), `evidence`, `desc`.

Note: match phases by NAME, not number. Numbers shift with directive and device (opt_design Phase 8 is `Remap` or `Post Processing Netlist`; place_design 2.2 changes meaning).

`[[pattern]]`: log-line regexes in Python `re` syntax with named groups. `kind` is `timing`, `metric`, `flag`, `info`, `block_start` or `structure`; `applies_to` lists step ids; `example` is a real line (all examples are tested). `final = true` marks the timing line that is the step's end result. `N/A` in a captured value means not available yet. Note `Time (s): ... elapsed` after a phase is cumulative since the step start, so subtract the previous value to get a phase duration.

## Device families

`[catalog] family_map` is an ordered list of `{ match = <regex on the lower-case part name>, family = <name> }`, first match wins: `7series` (xc7a/k/v/s/z), `ultrascale+` (xczu, xcau, xck24/26, xcku\d+p, xcvu\d+p), `ultrascale` (xcku/xcvu with three digits), `versal` (xcvc/ve/vm/vp/vh). The part comes from the first `Command: ... -part <part>` line of the log (`synth_design` or `link_design`).

A phase, task or section with `families = [...]` is only shown as a pending placeholder on those families. Anything actually seen in a log is always shown, whatever its family. When the part is unknown or matches no entry, nothing is filtered (as before the families existed). Only mark an entry when it was seen on one family and absent in a fully run step of the other; when unsure use `optional = true` instead.

What the 7-series logs (Vivado 2023.2, xc7a35t and xc7z020, a tiny counter/multiplier design) showed against the UltraScale+ logs:

- place_design: `Partition Driven Placement` (and its PBP children), `Small Shape DP` (with its children) and `Fast Optimization` only on UltraScale(+); 7-series has `Area Swap Optimization` and `Small Shape Detail Placement` instead, and runs `Pipeline Register Optimization` twice.
- route_design: `Global Clock Net Routing`, `Update Timing for Bus Skew`, `Resolve XTalk` and the second `Route finalize` only on UltraScale(+). 7-series adds a `Update Timing` inside `Hold Fix Iter`.
- opt_design, synth_design and the phase lists of phys_opt_design (no violations, no phases) did not differ.
- Entries restricted to `ultrascale` and `ultrascale+` are not restricted for Versal by evidence: they are simply hidden there, because there is no Versal log to say they occur.

## Vivado versions

The loader reads every `vivado_<ver>.toml` and picks the one for the `# Vivado v<ver>` header of the log: the exact version, else the closest older one, else the oldest. So 2024.x and 2025.x logs use the 2023.2 catalog, and 2022.x too. When that differs from the log's version, `Firmware.info.catalog_version` holds the version used and the info panel shows it next to the Vivado version.

Verified (against real logs, checked in CI): Vivado 2023.2 on UltraScale+ (RFSoC) and on 7-series (Artix-7, Zynq-7000; fixtures under `tests/fixtures/sevenseries/`). Not verified, no log was available: Vivado 2024.x/2025.x (no catalog file exists for them; phase names may have changed), all Versal devices (`write_device_image` is from documentation), plain UltraScale (family map only), SLR-specific phases, power-opt steps.

## Adding a version or override

- New version: copy `vivado_2023.2.toml` to `vivado_<ver>.toml`, change `[catalog] vivado`, run real logs of that version through the checks below, and edit only what differs (new or renamed names, `families`, `evidence = "log"`, `families_seen`). Do not add one from memory: an unverified file hides the working fallback. Put the new logs, trimmed and anonymised, next to `tests/fixtures/sevenseries/` and extend `tests/test_catalog_families.py`. The loader picks the file by the `# Vivado v<ver>` header of the log, falling back to the nearest older one (else the oldest).
- User override: put a file with the same name in the user config dir (`~/.config/vmon/catalog/`). Merge rule: `[[step]]` entries merge by `id`, `phases`/`tasks`/`sections`/`stages`/`reports` entries merge by `name` (or `file`), `[[pattern]]` by `id`; scalar keys in the override win. To remove an entry set `disabled = true` on it.
- Checking a catalog: parse it with `tomllib`, compile every `regex`, apply them to real logs, and diff the set of `Phase`/`Task` names found in the logs against the catalog (unknown names should be shown in the UI anyway, just as unplanned).

## Caveats

- UltraScale+ RFSoC logs and a tiny 7-series design (which only exercises the common phases) were available. Versal (`write_device_image`), plain UltraScale, 2024.x/2025.x, SLR-specific phases and the power-opt steps are from the install files or general knowledge (`evidence = "install"`/`"doc"`), not logs.
- Synth section timers cover only ~20% of synth_design wall time; use synth weights for ordering, not for a time estimate.
- phys_opt phase lists are the longest sequence seen (AggressiveExplore); the default directive runs a subset, and with no violations it runs none.

The same text lives next to the data in `vmon/catalog/README.md`.
