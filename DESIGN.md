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
(Top issues, Stages, Timing, Utilization, Build info) are sentence case at Small 600.

## Layout

A single centered column (max 1100px, 20px side padding) under a sticky top bar and a horizontal tab strip (one tab
per firmware). Inside a firmware: a header panel (name, status pill, path, meta row), a sticky summary bar, then
the flow. The flow is a master–detail layout: the stage column on the left and the expanded step details on the
right. Below about 1000px it collapses to a single column with inline drill-down.

The flow node is a two-column grid: a 36px rail gutter and the card. The rail's dashed connector runs exactly
through every icon center.

Density is high but evenly spaced: gaps of 5–6px inside chip rows, 10–14px between cards, 18–22px between major
blocks. Responsive breakpoints at 1400, 1180, 1000, 960, 820 and 640px progressively hide secondary summary items
(utilization, counts, ETA) rather than shrinking type.

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
- **Internal Padding:** 10px 14px (cards), 18px 20px (header).

### Inputs / Fields
- **Style:** Slate Raised fill, 1px Graphite Rule border, 8px radius, 13px text.
- **Focus:** border turns Signal Blue with a 3px soft blue ring.

### Navigation (firmware tabs)
- One tab stop for the strip (roving tabindex): arrow keys and Home/End move between firmwares, Delete stops watching;
  the × is a mouse affordance outside the tab order. The strip fades at the edge that hides more tabs.
- Folder-style tabs with 10px top corners on a panel-to-page gradient strip. Each tab shows the name (600/13.5px),
  a muted sub-line and a status dot. The active tab joins the page background and has a 2px Signal Blue line on top.

### Alerts
- Listed once, in the firmware banner (compact strip when only warnings), each row jumping to its step. The stage
  detail does not repeat them; the stage card carries the alert icon and border.
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
