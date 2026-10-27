---
name: vmon
description: Live monitor for Vivado firmware builds, read like a lab notebook.
colors:
  ink-night: "#0e131a"
  ink-night-deep: "#121a25"
  slate-page: "#151c27"
  slate-page-raised: "#1a2230"
  slate-page-high: "#202a3a"
  graphite-rule: "#263143"
  graphite-rule-soft: "#1e2837"
  rail-dim: "#2d3a50"
  chalk: "#e5eaf2"
  chalk-secondary: "#aab5c6"
  pencil-grey: "#7a879b"
  signal-blue: "#6ea8ff"
  on-signal: "#0d1117"
  on-status: "#0d1117"
  pass-green: "#3fbb7d"
  fail-red: "#fd6274"
  critical-orange: "#f28b3d"
  caution-amber: "#e5b53c"
  note-blue: "#7d9bc7"
  stopped-ochre: "#d9a441"
  setup-slack-orange: "#f0a24a"
  hold-slack-violet: "#b58cf0"
typography:
  display:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Cascadia Code, Menlo, Consolas, DejaVu Sans Mono, monospace"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.15
    fontFeature: "tnum"
  headline:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    letterSpacing: "-0.2px"
  heading:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.3
  lead:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Cascadia Code, Menlo, Consolas, DejaVu Sans Mono, monospace"
    fontSize: "17px"
    fontWeight: 700
    fontFeature: "tnum"
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 600
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  control:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 600
  small:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 500
  caption:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "11.5px"
    fontWeight: 500
    letterSpacing: "0.6px"
  micro:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "10.5px"
    fontWeight: 800
    letterSpacing: "0.6px"
  readout:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Cascadia Code, Menlo, Consolas, DejaVu Sans Mono, monospace"
    fontSize: "12.5px"
    fontWeight: 700
    lineHeight: "19px"
    fontFeature: "tnum"
rounded:
  xs: "4px"
  sm: "6px"
  inner: "7px"
  md: "8px"
  lg: "10px"
  card: "12px"
  panel: "14px"
  pill: "99px"
spacing:
  xs: "4px"
  sm: "6px"
  md: "10px"
  lg: "14px"
  xl: "20px"
components:
  card:
    backgroundColor: "{colors.slate-page}"
    textColor: "{colors.chalk}"
    rounded: "{rounded.card}"
    padding: "10px 14px"
  card-hover:
    backgroundColor: "{colors.slate-page-raised}"
  panel-header:
    backgroundColor: "{colors.slate-page}"
    rounded: "{rounded.panel}"
    padding: "18px 20px"
  chip-met:
    textColor: "{colors.pass-green}"
    typography: "{typography.readout}"
    rounded: "{rounded.sm}"
    padding: "1px 8px"
  chip-notmet:
    textColor: "{colors.fail-red}"
    typography: "{typography.readout}"
    rounded: "{rounded.sm}"
    padding: "1px 8px"
  chip-notfinal:
    textColor: "{colors.caution-amber}"
    typography: "{typography.readout}"
    rounded: "{rounded.sm}"
    padding: "1px 8px"
  pill-status:
    textColor: "{colors.chalk-secondary}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  button:
    backgroundColor: "{colors.slate-page-high}"
    textColor: "{colors.chalk}"
    rounded: "{rounded.md}"
    padding: "6px 14px"
  icon-button:
    backgroundColor: "{colors.slate-page-raised}"
    textColor: "{colors.chalk-secondary}"
    rounded: "{rounded.md}"
    size: "34px"
  input:
    backgroundColor: "{colors.slate-page-raised}"
    textColor: "{colors.chalk}"
    rounded: "{rounded.md}"
    padding: "6px 12px"
  segmented-on:
    textColor: "{colors.signal-blue}"
    rounded: "{rounded.lg}"
    padding: "5px 14px"
---

# Design System: vmon

## Overview

**Creative North Star: "The Lab Notebook"**

vmon reads like a well-kept lab notebook for a build. Each build is a sequence of entries
(synth, opt, place, phys_opt, route, bitstream) written down the page along a single rail, each one
annotated with its readouts: counts, slack, durations. The page is calm, dense and exact. It is
quiet by default, holds a lot of information without raising its voice, and adds color only to
record a change of state. Dark is the default sheet; a light theme is a full equal, not an afterthought.

The notebook is read at a glance from a second monitor and studied closely when an alert fires.
So the hierarchy is two-tier: from the desk you can read status (rail color, status dot, pill,
timing chip), and up close you can read the numbers (monospaced, tabular readouts). Details live
one click deeper, in the drill-down, never on the overview.

Everything is self-contained: system font stacks, inline SVG icons, no webfonts or CDN assets.

**Key Characteristics:**
- One vertical rail threading every step; its segments take on the status color of what they connect.
- Tinted, low-alpha status fills (about 14%) with full-strength text, never solid colored blocks.
- All numbers set in a monospace font with tabular figures.
- Soft-edged, restrained components: thin 1px rules, faint ambient shadow, 6–14px radii.
- Motion only to signal "running": a pulse, a marching rail and a spinning icon. All of it is disabled under reduced motion.

## Colors

A cool, ink-and-slate neutral sheet with one signal blue, plus a strict semantic set for build state.
Every color has a light-theme twin (see the `light` values in `.impeccable/design.json`); both themes
are defined as CSS custom properties on `:root` and `:root[data-theme="light"]` in `vmon/static/style.css`.

### Primary
- **Signal Blue** (`signal-blue`): the "running now" color. Running step rail, status dot pulse, active tab
  underline, selected segmented control, focus rings and the running-card glow. It also serves as the generic
  interactive accent (hover borders), but at rest it means "this is happening".

### Tertiary (semantic state)
- **Pass Green** (`pass-green`): completed steps, timing met, the done rail.
- **Fail Red** (`fail-red`): final failures only: failed step, final timing not met, errors.
- **Critical Orange** (`critical-orange`): CRITICAL WARNING counts.
- **Caution Amber** (`caution-amber`): warnings and "not final" timing (intermediate or estimated values).
- **Note Blue** (`note-blue`): INFO messages, informational events.
- **Stopped Ochre** (`stopped-ochre`): runs that were stopped or killed without failing.
- **Setup Slack Orange** / **Hold Slack Violet** (`setup-slack-orange`, `hold-slack-violet`): chart series for
  WNS-family and WHS-family values in timing history and convergence charts.

### Neutral
- **Ink Night** (`ink-night`, deeper `ink-night-deep`): page background.
- **Slate Page** (`slate-page`), **Raised** (`slate-page-raised`), **High** (`slate-page-high`): three surface
  steps for cards, inputs and buttons, and hovered or nested panels.
- **Graphite Rule** (`graphite-rule`, softer `graphite-rule-soft`): 1px borders and dividers.
- **Rail Dim** (`rail-dim`): the dashed rail segment before a step has started.
- **Chalk** (`chalk`), **Chalk Secondary** (`chalk-secondary`), **Pencil Grey** (`pencil-grey`): primary text,
  secondary text, and muted metadata/pending labels.
- **On Status** (`on-status`): text and glyphs on a solid status fill (NOT MET badge, tab alert count, failed-step
  icon). Dark ink in the dark theme, white in the light theme, so both stay above 4.5:1. Never hard-code `#fff` on a status color.

### Named Rules
**The Never Cry Wolf Rule.** Fail Red is reserved for final results that actually failed. Intermediate,
estimated or stale values use Caution Amber or fade; they never turn red. A build that crashed before final timing shows
its last estimate as INCOMPLETE in neutral. Utilization is amber from 80%, Critical Orange from 90%, and red only above
100% (over capacity). A zero count carries no severity tint. A finished build whose final timing fails is labelled
by its outcome, "Finished, timing not met", in red on the pill, tab dot and summary bar, never a green "Done".

**The Tint, Don't Fill Rule.** Status color appears as a ~10–16% alpha background with full-strength text
(`--ok-bg`, `--err-bg`, ...), or as a rail/dot. The one solid fill is the final NOT MET timing badge: the loudest thing
on the page is reserved for the one result that is truly lost. Status text must reach 4.5:1 on its own tint in both themes.

**The No Side Stripe Rule.** Status is never a thick colored left border. Cards change their 1px border color, carry an
icon, or take a tint.

**The One Signal Rule.** Signal Blue at rest means "running". Don't spend it on decoration.

## Typography

**Body Font:** system UI stack (`system-ui`, -apple-system, Segoe UI, Roboto, ...)
**Readout Font:** system monospace stack (`ui-monospace`, SF Mono, JetBrains Mono, ... DejaVu Sans Mono)

**Character:** Plain native sans for the words, monospace with tabular figures for every number, so columns of
slack, counts and durations line up like a notebook table.

### Hierarchy
The scale lives in `style.css` as `--fs-*` custom properties; every `font-size` uses one of them.
- **Display** (mono 600, 28px, tabular): elapsed time in the build header, the one number read from across the room.
- **Headline** (700, 22px, -0.2px): firmware name.
- **Heading** (600, 20px): current step line, ETA, WNS/TNS/WHS/THS values, the selected stage title.
- **Lead** (mono 700, 17px): message counts, brand, the final NOT MET badge.
- **Title** (600, 15px): step labels on the flow cards.
- **Body** (400, 14px, 1.45): default text; tab names, summary bar name.
- **Control** (600, 13px): buttons, inputs, segmented controls.
- **Small** (500, 12.5px): metadata rows, top issues, section headings (600, Chalk Secondary, sentence case).
- **Caption** (500, 11.5px, 0.6px, uppercase): data keys only (Elapsed, Started, WNS…), sub-lines.
- **Micro** (800, 10.5px, 0.6px, uppercase): severity pills, NEW / STALE / FINAL tags. Nothing is set smaller.
- **Readout** (mono 700, 12.5px, tabular): badges, timing chips, durations.

### Named Rules
**The Tabular Numbers Rule.** Any number that can change during a build is set in the mono stack with
`font-variant-numeric: tabular-nums`, so it doesn't jitter as it updates.

**The No Webfonts Rule.** Only system stacks. The tool must render identically offline.

**The Keys Shout, Headings Speak Rule.** Uppercase letter-spaced micro type is for data keys and tags. Section headings
(Needs attention, Build progress, Stages, Build info) are sentence case at Small 600.

## Layout

Two columns under the sticky top bar and the firmware tab strip. On the left, a 290px **stage rail**: the stage list
(Synthesis … write_bitstream) with the "follow live" switch on top. It is sticky beside everything else and scrolls
on its own when long, so the stages and follow-live are always in view, in every view (Flow, Messages, Timing). On
the right: the **hero** (name, status pill and path with Compare, Build info and an overflow menu for exports; a one-line
verdict tinted by tone; the build progress strip; four metric tiles that go 2x2 below 1250px; the one Needs attention
list), then the selected stage's detail or the Messages/Timing view. Because
the rail already shows each stage's counts, timing chip, time and progress, the detail header keeps only the name,
status, description, report chips, docs link and peak memory. Max width 1760px, 20px side padding.

Below that header the stage detail is a **phase timeline**: one flat outline (chevron, status dot, name, message chips,
Gantt bar, elapsed, peak memory; 16px indent per level, memory hidden below 1000px, bars below 700px) over one shared
time axis, with a "Whole step" root row, and a single **inspector** under it (breadcrumb, status, counts, time, then the
Messages / Log / Reports / Timing / Congestion / Convergence tabs that apply to the selected row). The outline scrolls
at most ~460px, so the inspector stays in view. Running bars are striped with a "now" line, expected ones dashed. The
running or failed row is selected and its ancestors opened by themselves; a manual selection is pinned. Hints fold to
one line ("CHECK title · N suggested actions"). The outline is an ARIA tree (arrows, Enter) and rows are patched in place.

The recap card stays compact: the start time sits under the elapsed readout, message counts are small chips, and Top
issues is one summary line ("2 critical warnings · 1 warning") that expands on click (remembered). Opening anything in
the right column (a step, a detail tab, a report, a message or path row, Build info) that ends below the window
scrolls the page just enough to show it whole, never pushing the control that opened it under the sticky bars; a
wheel or touch scroll by the user cancels that.

The flow node is a two-column grid: a 36px rail gutter and the card. The rail's dashed connector runs exactly
through every icon center.

Density is high but evenly spaced: gaps of 5–6px inside chip rows, 10–14px between cards, 18–22px between major
blocks. Below 1000px the layout stacks into one column (hero, then the stage list as a single tree: the selected
stage's detail opens directly under its own card, and the list is hidden in the Messages and Timing views). Top-bar breakpoints at
1520, 1360, 1180 and 1100px progressively hide secondary items rather than shrinking type.

**Mobile (below 700px).** The nested tree gives way to drill-in navigation, one screen per level, so text keeps the full
width at any depth. A compact sticky top bar holds the logo, a firmware switcher (status dot, name, state; it opens a
bottom sheet listing every firmware with state, progress, WNS and alert count, led by an "All builds" entry, plus the
CPU/RAM/Swap meters, Explore and Theme) and the notifications bell; the logo, with its attention badge, also opens All builds. The Build tab is the firmware screen: a compact hero (progress ring, status, current
step, elapsed and ETA, the verdict line, WNS/TNS/WHS tiles, message counts), the same Needs attention list (three rows,
Fix fold-outs, dismiss), then the stages as full-width rows. Tapping a row pushes that node's screen: a back button, a
scrollable breadcrumb, its status and counts, and its children as flat rows (status, name, chips, duration; no indentation
at any depth). Levels use `history.pushState`, so the phone's Back pops one. Messages / Log / Reports / Timing of the
current level open in a bottom sheet with a segmented control and the same inspector renderers as the desktop. A bottom
tab bar switches Build / Messages / History (the Messages view and History page are the shared desktop ones, restyled to
stack). A *Jump to running* chip makes the stack follow the running node; any manual navigation pauses it. Bars respect
`env(safe-area-inset-*)`, every control is at least 44px, both themes. The code is a separate section of `app.js` with
`m-` prefixed classes; the desktop render keeps running underneath, hidden.

## Elevation & Depth

Mostly flat with tonal layering: depth comes from the three slate surface steps and 1px graphite borders. A single
faint ambient shadow sits under cards and header panels. The only stronger effect is the running-card glow: a 1px
signal-blue ring plus soft halo, together with a left-to-right accent tint. It marks the live step, not an elevation.

### Shadow Vocabulary
- **Ambient** (`box-shadow: 0 1px 2px rgba(0,0,0,.35), 0 6px 18px rgba(0,0,0,.18)`): cards, header panels.
- **Running glow** (`box-shadow: 0 0 0 1px rgba(110,168,255,.55), 0 0 22px rgba(110,168,255,.22)`): the running step card only.
- **Focus ring** (`box-shadow: 0 0 0 3px var(--accent-soft)` with accent border): inputs.

### Named Rules
**The Glow Means Live Rule.** Glow and pulse are state signals for "running" (and the flash on a new alert),
never hover or decoration.

## Shapes

Soft but not bubbly. Radii scale with the size of the object: 4–6px for chips, badges and progress bars, 8px for
buttons, inputs and icon buttons, 10px for tabs and segmented controls (7px for an element nested inside a 10px tray with
3px padding, so the corners stay concentric), 12px for flow cards, and 14px for the build
header panel. Pills and dots are fully round. Pending, queued and skipped steps switch to a dashed border on a
transparent card: an entry not yet written.

## Components

### Buttons
- **Shape:** gently rounded (8px).
- **Default:** Slate High background, 1px Graphite Rule border, 600 weight at 13px, padding 6px 14px.
- **Hover:** border shifts to Signal Blue; no fill change.
- **Icon button:** 34px square, Slate Raised, secondary text; text brightens and the border turns blue on hover.
- **Segmented control:** a 10px-radius tray with 7px-radius options; the selected option gets the blue tint and blue text.

### Chips (timing and counts)
- **Style:** mono readout on a tinted fill, 6px radius, 1px 8px padding: `met` green, `notmet` red, `softbad` amber
  (not final), `nil` neutral.
- **Badges:** same shape for INFO/WARNING/CRITICAL/ERROR counts, with a small sans letter-spaced prefix.

### Status pill and dot
- **Pill:** fully round, 600/12px, capitalized status text on the matching tint.
- **Dot:** 9px circle; pulses blue when running, solid green/red/ochre otherwise.

### Cards / Containers
- **Corner Style:** 12px (flow cards), 14px (build header).
- **Background:** Slate Page; Slate Raised on hover.
- **Shadow Strategy:** Ambient; the running card swaps to the running glow.
- **Border:** 1px Graphite Rule. Red (error alert) or amber (warning alert) 1px border; dashed on pending/skipped/queued.
- **Internal Padding:** 10px 14px (cards), 14px 18px (hero).

### Inputs / Fields
- **Style:** Slate Raised fill, 1px Graphite Rule border, 8px radius, 13px text.
- **Focus:** border turns Signal Blue with a 3px soft blue ring.

### Navigation (firmware tabs)
- One tab stop for the strip (roving tabindex): arrow keys and Home/End move between the visible firmwares, Delete stops
  watching; the × is a mouse affordance outside the tab order.
- Folder-style tabs with 10px top corners on a panel-to-page gradient strip. A tab is compact: status dot, name
  (600/15px), a small host marker for a remote firmware and the alert count. The current step, elapsed time and path are in
  its tooltip, so a tab keeps its width between polls. Tabs that do not fit are hidden, never scrolled: a **+N** pill at the
  end of the strip opens a menu of them (arrows, Home/End, Enter, Esc). The selected tab is always one of the visible
  ones, and a red dot on the pill says that a hidden tab has errors. The active tab joins the page background and has a
  2px Signal Blue line on top.
- The **logo** is a real button named "All builds" (key `0`, URL `#home`): it opens the All builds page, which is not a
  tab, so no tab is selected and the logo takes the active tint. Its red badge counts the builds that need attention.

### All builds page
- A responsive grid (340px minimum) of **build cards** in three groups: Running, Needs attention (failed, stopped,
  timing not met, or errors; a running build with errors sits here with its Running pill) and Finished. A card is one
  button: status dot, name, host marker, attempt and status pill; the current step with its ETA (or how it ended); the
  same build strip as the firmware hero, bars only; then Elapsed/Duration, WNS with its estimate/final/incomplete tag,
  worst utilization, error and critical-warning counts, and the Vivado CPU/RAM when known. A coloured left edge repeats
  the state; a red or ochre line spells out why it needs attention.
- **Wall display** is the same page fullscreen (when the browser allows it) with no top bar or tab bar, a clock, and
  larger type and bars (460px cards). Esc, or its button, leaves it. On a phone the cards are one per row and the wall
  button is not offered.

### History trends and the Reports menu
- Above the table, with one firmware selected, three small charts (WNS, duration, worst utilization) share one **evenly
  spaced** x axis: one slot per build in date order (the last 40), dates labelled at the ends and the middle. Builds come
  in bursts, so a calendar axis would stack the points of a busy day on top of each other and make them impossible to
  click, and would spend the width on quiet weeks; one slot per build keeps every point a button and the order readable.
  WNS is coloured by sign (red only for a final failure, amber for an estimate), utilization by the usual 80/90 steps,
  with a dashed 80% line; a point scrolls to its row and flashes it. With "All firmwares" a one-line hint replaces them.
  Stacked on a phone.
- The row's report links, bitstream and Markdown export live in one **Reports ▾** menu next to a **Summary** button
  (printable HTML). The menu is a fixed popup under its button with arrow keys, Home/End and Esc; it closes on a click
  outside or when the page scrolls, not when its own list does.

### Alerts
- Listed once, in the hero's **Needs attention** list together with the top message groups and the suggested actions
  (a hint that explains an alert becomes that row's *Fix* fold-out; duplicates are merged). Worst first, three rows then
  "Show N more"; each row jumps to its step and has a dismiss x (dismissed items stay counted, "N dismissed · show"
  restores them). The stage detail does not repeat them: the stage card carries the alert icon and border, and a hint
  of the stage is one line ("N suggested actions → Needs attention") that opens its row, so the fix text has one owner.
- The verdict never says later steps may fix timing on a finished or HLS build; red is for final failures only.
- **Build progress strip:** one segment per top-level stage, width = actual time (done, running) or `expected_s`
  (pending, and the running stage's projected end), with a minimum width; the running one is striped with NOW and %.
- Each row names the alert in words (Timing, Critical warnings, Step failed…), never the internal code; the code stays
  in the tooltip.

### Flow Rail (signature)
- The vertical connector of the notebook. Dashed (4px on, 4px off) in Rail Dim before a step starts. Solid green
  once done. Blue and marching (animated dash) while running. Red or ochre after a failed or stopped step. Status
  icons (24px) sit centered on the line with a page-colored backing so the line appears to pass behind them.

## Do's and Don'ts

### Do:
- **Do** define every color as a CSS custom property with both dark and light values; never hard-code a hex in a rule.
- **Do** set changing numbers in the mono stack with tabular figures.
- **Do** express status as tint plus text, rail color or dot, in the matching semantic color.
- **Do** keep detail one click away (drill-down, tabs, expandable rows) rather than on the overview.
- **Do** disable all animation and transitions under `prefers-reduced-motion`.
- **Do** give every focusable element the 2px Signal Blue `:focus-visible` ring (inputs keep their border + soft halo), and make
  every clickable card or tab reachable with Tab and operable with Enter/Space.

### Don't:
- **Don't** use Fail Red for intermediate, estimated or stale values (The Never Cry Wolf Rule).
- **Don't** load webfonts, icon fonts or anything from a CDN; icons are inline SVG.
- **Don't** use glow or pulse for hover or decoration; they mean "running".
- **Don't** introduce solid saturated status blocks (except final NOT MET), heavy drop shadows, or colored side stripes.
- **Don't** shrink type to fit narrow widths; hide secondary items instead.
