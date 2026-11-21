---
name: RAG Workspace
description: A quiet instrument panel for grounded document questions
colors:
  light-bg: "#faf9f6"
  dark-bg: "#000000"
  surface: "#ffffff"
  surface-dark: "#0a0a0a"
  raised-dark: "#141414"
  ink: "#111110"
  ink-dark: "#f5f5f3"
  muted: "#61605a"
  muted-dark: "#9a9a95"
  border: "#dedcd5"
  border-dark: "#262626"
  signal: "#2049d8"
  signal-dark: "#7ea6ff"
  success: "#16803c"
  success-dark: "#62c98a"
  warning: "#a5660b"
  warning-dark: "#e2b45c"
  destructive: "#c22b22"
  destructive-dark: "#ff7b70"
typography:
  micro:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "10px"
    fontWeight: 500
  caption:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 500
  label:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 500
  body:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.01em"
  section:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 600
  subtitle:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
  headline:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.025em"
  auth-title:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    letterSpacing: "-0.03em"
  title:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.025em"
  display:
    fontFamily: "Geist Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 600
    letterSpacing: "-0.03em"
  mono:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 400
rounded:
  sm: "6px"
  md: "8px"
  panel: "10px"
  sheet: "14px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "20px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.light-bg}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
  button-primary-dark:
    backgroundColor: "{colors.ink-dark}"
    textColor: "{colors.dark-bg}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "20px"
---

# Design System: RAG Workspace

## Overview

**Creative North Star: "The Evidence Console."**

A document-review instrument, not a marketing surface. The UI gets out of the
way of two activities: getting an answer and verifying where it came from.
Everything is built from hairline rules, quiet surfaces and one signal color;
density is high enough for long sessions but never crowded. Dark mode is true
black with one step of surface lift; light mode is warm off-white with white
panels. The rejected reference is the dashboard of equal cards and hero numbers.

**Key Characteristics:** monochrome-first, one signal, hairline structure,
developer-console rhythm, source always within reach, native at 320px.

## Colors

One neutral family plus a single blue signal. Status colors are semantic only
and never carry decoration. Dark surfaces lift from black instead of shadowing.

### Neutral
- **Off-white ground** (`#faf9f6`): light page; content sits on white panels.
- **True black** (`#000000`): dark page.
- **Ink / Frost** (`#111110` / `#f5f5f3`): primary text in light / dark.
- **Muted** (`#61605a` / `#9a9a95`): secondary text; never lower contrast than 4.5:1.
- **Hairline** (`#dedcd5` / `#262626`): borders, dividers, table rules.

### Signal
- **Cobalt** (`#2049d8` / `#7ea6ff`): active nav, primary focus, citation links,
  progress. Kept to a small fraction of any screen.

### Named Rules
**The One Voice Rule.** One accent, used for state and action only. Status
green/amber/red appear exclusively on real statuses.

## Typography

**Display/Body:** Geist Sans (local). **Data:** Geist Mono (local).

Numbers, hashes, slugs, file sizes and chunk counts are monospaced and
tabular-numeric. Headings carry meaning through weight and size, not color or
kickers.

### Hierarchy
- **Display** (600, 30px): dashboard page title on wide screens.
- **Title** (600, 26px, 1.1, -0.025em): standard page title; 24px on auth pages.
- **Headline** (600, 22px): compact page titles.
- **Section** (600, 14–15px): section headings inside a page.
- **Body** (400, 13px, 1.5): messages, rows, descriptions (65–75ch measure).
- **Label** (500, 11–12px): metadata, statuses, badges; 10px for micro labels.
- **Mono** (400, 11px): identifiers, hashes, sizes, chunk counts; tabular numerals.

## Layout

A 220px fixed rail on desktop holds workspace switcher, four nav items and the
user menu; the main column starts at x=220 with 32px horizontal padding and a
thin top bar. Lists are full-width ruled rows (12px vertical padding), not
cards. At <768px the rail becomes a sticky top bar with switcher and a 64px
bottom tab bar; at <1024px the conversation sidebar becomes a bottom sheet and
the source panel becomes a right-edge sheet. Panels are never boxed inside
other panels.

## Elevation & Depth

Flat by default. Depth comes from surface steps (`--surface`, `--surface-raised`)
and 1px borders. A single authored shadow belongs to floating panels (dialogs,
citation sheet, command palette): `0 1px 2px … , 0 16px 40px -12px …`.

## Shapes

10px panels, 8px controls, 6px small chips and menu items, 999px for status
pills. Hairline borders, no colored left rules, no ghost shadows under borders.

## Components

### Buttons
Solid ink / frost primary, outline and ghost secondary. 13px medium weight,
8–14px padding, 9px height baseline (44px on coarse pointers). One hover step
of the same color, never a gray swap.

### Inputs & Selects
9px tall, hairline border, transparent-to-surface hover, accent focus ring.
Radix Select used for workspace, role, provider type and status filter.

### Rows
Name on the first line, mono metadata on the second, actions right-aligned.
Skeleton rows keep the same pitch as real rows.

### Dialogs & Sheets
Radix Dialog: centered for command palette, right edge for citations on desktop,
bottom sheet for conversation history on mobile. One overlay, one shadow.

### Toasts
Sonner, bottom-right, rich colors, closeable. Toasts confirm actions and name
recovery when something fails.

## Do's and Don'ts

- Do keep the source panel one click from every `[n]` citation.
- Do use real content in rows; skeletons only while loading.
- Do not nest cards, add kicker labels, or fill space with equal-size tiles.
- Do not introduce a second accent or use the signal as decoration.
- Do not hide functionality on mobile — reflow it into sheets and tabs.
