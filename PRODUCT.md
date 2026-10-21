# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One primary user: the author, an FPGA firmware developer (university research group) running
long Vivado builds (UltraScale+ RFSoC, Vivado 2023.2) on their own Linux machine. Others may find
the tool on GitHub, but they are not a design target.

## Product Purpose

vmon replaces reading Vivado log files during a build. It shows which step and phase is running,
what is still to come, timing, utilization and the warnings that matter. Success means the user
knows the state of every build without opening a log, and finds out quickly when something
goes wrong.

## Positioning

A local, read-only monitor that relies only on log parsing. It auto-discovers running Vivado processes
and predicts upcoming steps and phases from a per-version catalog. It labels intermediate timing as
"not final" and shows red only when the final result fails. It triages messages by novelty against
the previous build.

## Operating Context

- Two modes of use: (1) left open on a second monitor and read at a glance while other work
  happens; (2) ignored until a browser notification or alert fires, then used to dig into
  warnings, timing paths and messages.
- Builds last tens of minutes to hours, and several firmwares may run at once (one tab each).
  Finished runs stay visible.
- Served on 127.0.0.1 and opened in a desktop browser.

## Capabilities and Constraints

- Drill-down flow: synth → opt → place → phys_opt → route → bitstream, with phases. Also message
  counts by severity, WNS/TNS/WHS/THS, worst paths, per-clock history, router convergence, utilization,
  ETA, build info, CPU/RAM/swap and an event log.
- No build step and no dependencies: plain HTML/CSS/JS frontend; Python standard library backend.
- Must work offline. No CDN fonts or scripts, so it runs on air-gapped lab machines.
- Light and dark themes must both stay supported.
- Read-only on firmware/Vivado directories; never signals Vivado processes.
- Vivado-specific knowledge lives in declarative config (`vmon/flows.toml`, `vmon/catalog/`), not in UI code.

## Evidence on Hand

- Screenshots: `docs/img/overview.png`, `docs/img/messages.png`, `docs/img/light-theme.png`.
- Mock data: `vmon/static/mock/` (open `index.html?mock=1`).
- No users, testimonials or benchmarks beyond the author's own use; do not invent any.

## Product Principles

1. Glanceable first: the state of every build must be readable from across the desk.
2. Never cry wolf: intermediate or estimated values must not look like failures.
3. Loud when it matters: real failures, stalls and new critical warnings must stand out and trigger alerts.
4. Depth on demand: details stay one click away and don't crowd the overview.
5. Self-contained and trustworthy: offline, read-only, no hidden dependencies.
