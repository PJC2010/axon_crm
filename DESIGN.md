---
name: Axon
description: Territory intelligence CRM — a dark slate console with a turquoise signal accent
colors:
  console-black: "#111418"
  canvas-deep: "#1c2127"
  paper: "#252a31"
  surface: "#2f343c"
  surface-hi: "#383e47"
  cream: "#f6f7f9"
  ink-50: "#2f343c"
  ink-100: "#383e47"
  ink-200: "#404854"
  ink-300: "#5f6b7c"
  ink-400: "#96a0ae"
  ink-500: "#abb3bf"
  ink-600: "#c5cbd3"
  ink-700: "#d3d8de"
  ink-800: "#e5e8eb"
  ink-900: "#f6f7f9"
  accent: "#00a396"
  accent-600: "#13c9ba"
  accent-700: "#007067"
  accent-800: "#004d46"
  accent-300: "#7ae1d8"
  accent-100: "#0c3a37"
  accent-50: "#103330"
  accent-200: "#0f4f49"
  moss: "#36b171"
  moss-soft: "#1c3527"
  ocean: "#3fa6da"
  ocean-soft: "#16313d"
  gold: "#f0b726"
  gold-soft: "#3a2f12"
  plum: "#bd6bbd"
  plum-soft: "#331a33"
  rose: "#f5498b"
  rose-soft: "#3a1626"
  success: "#36b171"
  success-bg: "#1c3527"
  warning: "#ec9a3c"
  warning-bg: "#3a2a12"
  danger: "#ec7a7e"
  danger-bg: "#3a1d1d"
  info: "#3fa6da"
  info-bg: "#16313d"
typography:
  display:
    fontFamily: "Roboto Slab, Geist, -apple-system, sans-serif"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Roboto Slab, Geist, -apple-system, sans-serif"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Geist, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  eyebrow:
    fontFamily: "Geist, -apple-system, sans-serif"
    fontSize: "10px"
    fontWeight: 600
    letterSpacing: "0.08em"
  label:
    fontFamily: "Geist, -apple-system, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.06em"
  mono:
    fontFamily: "Geist Mono, ui-monospace, SF Mono, Menlo, monospace"
    fontFeature: "tnum"
rounded:
  input: "4px"
  button: "4px"
  card: "4px"
  modal: "6px"
  pill: "9999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
  "10": "40px"
  "12": "48px"
  "16": "64px"
  "24": "96px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.console-black}"
    rounded: "{rounded.button}"
    padding: "6px 14px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.accent-600}"
  button-primary-active:
    backgroundColor: "{colors.accent-600}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.button}"
    padding: "6px 14px"
    height: "32px"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.console-black}"
    rounded: "{rounded.button}"
    padding: "6px 14px"
    height: "32px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.input}"
    padding: "8px 10px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "20px"
  tag:
    backgroundColor: "{colors.ink-50}"
    textColor: "{colors.ink-600}"
    rounded: "{rounded.input}"
    padding: "2px 9px"
---

# Design System: Axon

## Overview

**Creative North Star: "The Night Dispatch"**

Axon looks like a dispatcher's board after dark: a slate room where turquoise signals glow, every number sits in tabular columns, and nothing is decoration. The whole interface is built for a contractor deciding — tonight — which doors are worth knocking tomorrow. Surfaces are dark slate with a faint woven texture; light is information (etched card edges, bright accent text, glowing data chips), never ambience.

The voice is **confident, technical, workmanlike**. Brand lives in precise details — the slab-serif headings that read like print on a work order, the mono numerals, the single turquoise reserved for things you can act on. Components are **tactile and confident**: buttons physically depress 1px on press, clickable cards lift on hover, focus rings glow turquoise. Motion is quick (100–180ms) with one signature ease; the dashboard content rises into place in a staggered beat.

The confirmed anti-reference is bubbly consumer SaaS: big radii, pastels, playful illustration, floating white cards. Axon never drifts there.

**Key Characteristics:**
- Dark-only system: slate surfaces, inverted "ink" text scale (light on dark)
- One interactive hue — turquoise — kept strictly separate from data colors
- All numerals in Geist Mono with tabular figures
- "Etched glass" elevation: light 1px inset border + soft dark drop shadow
- Crisp 4px corners; pills only for status/grade chips
- Faint geometric textures (weave, dots, grid) as material, not decoration

## Colors

A nocturnal palette: five slate surfaces, a ten-step inverted ink scale, one turquoise voice for interaction, and a bright-on-dark data family that always travels with a soft chip tint.

### Primary

- **Signal Turquoise** (`accent`, #00a396): the one interactive color — filled buttons at rest, focus borders, selection states. If it's turquoise, you can act on it. As a *fill* it carries an ink label; it is never small text (2.9:1 on slate).
- **Bright Turquoise** (`accent-600`, #13c9ba): the landing/marketing accent, and the hover state of filled controls — the signal intensifies, it never dims.
- **Turquoise Glow** (`accent-300`, #7ae1d8, 8.1:1 on slate): bright accent *text and links* on dark surfaces — eyebrows, "qualified" status, every accent-colored label.
- **Deep Turquoise** (`accent-700`, #007067) and **Abyssal Turquoise** (`accent-800`, #004d46): gradient depths, borders, and accent text on light fills.
- **Chip Tints** (`accent-100` #0c3a37, `accent-50` #103330) and **Faint Border** (`accent-200` #0f4f49): soft dark turquoise fills and the border that edges them.

### Neutral

- **Slate Paper** (`paper`, #252a31): the app background, always under the signature weave texture.
- **Card Slate** (`surface`, #2f343c) and **Raised Slate** (`surface-hi`, #383e47): card fill and its hover/raised step.
- **Recessed Slate** (`canvas-deep`, #1c2127) and **Console Black** (`console-black`, #111418): recessed canvases, deep panels, sidebar, bands.
- **Inverted Ink scale** (`ink-50`–`ink-900`): light-on-dark text and border ramp. Headings `ink-900`, body `ink-700`, muted `ink-500`, placeholder `ink-400`, dividers `ink-300`, borders `ink-200`/`ink-100`, faint fills `ink-50`.
- **Signal Cream** (`cream`, #f6f7f9): the brightest text tone (shares ink-900's value) for deep panels and gradient cards. Filled accent controls carry Console Black via `--text-on-accent`, not cream.

Product code should reach these through the semantic aliases (`--bg-app`, `--surface-card`, `--border-default`, `--text-body`, `--text-muted`, `--intent-primary`, …) rather than raw scale steps.

### Data & Semantic Intents

Bright-on-dark categorical family, each paired with a `-soft` chip tint: **Moss** (#36b171), **Cerulean** (`ocean`, #3fa6da), **Dispatch Gold** (#f0b726), **Plum** (#bd6bbd), **Flare Rose** (#f5498b). Semantic intents: success = moss, info = cerulean, **Amber Warning** (#ec9a3c), **Ember Red** (`danger`, #ec7a7e), each with a `-bg` tint. Moss and Ember Red are tuned to hold 4.5:1 as text on Card Slate; Flare Rose does not (3.4:1) and is a chart/graphic color, never a lone text color.

Lead grades and pipeline statuses have exactly one source: `frontend/lib/gradeColors.ts` (A = success, B = info, C = gold, D/F = danger; `lost` = danger but `not_interested` = neutral ink, deliberately).

### Named Rules

**The Affordance Hue Rule.** Turquoise belongs to interaction only — controls, focus, selection. Data categories never wear it: grade B is info blue, not accent. A data mark painted turquoise reads as a selected control, which is exactly the bug `gradeColors.ts` exists to prevent.

**The Soft Pair Rule.** A data color never appears as a full-strength fill behind text. Chips and badges pair the bright foreground with its dedicated soft dark tint (`moss`/`moss-soft`, `gold`/`gold-soft`, …).

## Typography

**Display Font:** Roboto Slab (with Geist fallback)
**Body Font:** Geist (with system-ui fallback)
**Label/Mono Font:** Geist Mono (tabular figures)

**Character:** Slab-serif headings give the console an editorial, printed-work-order authority; Geist keeps the UI technical and neutral; every numeral lands in mono columns like a ledger.

### Hierarchy

Sizes come from a compact, dashboard-first px scale: 10 / 11 / 13 / 15 / 17 / 20 / 26 / 32 / 40 / 56 / 72.

- **Display** (Roboto Slab 600, 1.05, −0.02em): marketing hero and hero stats; landing h1 is `clamp(40px, 6vw, 68px)`.
- **Title** (Roboto Slab 600, 1.2, −0.01em): page titles (32px), card/section titles (20px), panel heads.
- **Body** (Geist 400, 15px, 1.55): default reading text; secondary UI text drops to 13px.
- **Eyebrow** (Geist 600, 10px, +0.08em, uppercase, `ink-500`): section markers and KPI labels.
- **Label** (Geist 600, 11px, +0.06em, uppercase, `ink-500`): form field labels, table headers.
- **Mono** (Geist Mono, `tabular-nums`): scores, KPI values (26px/700), currency, anything that aligns in columns.

### Named Rules

**The Tabular Numbers Rule.** Every numeral renders in Geist Mono with tabular figures (the `.tabular` utility). Scores, money, counts, deltas — no exceptions. Proportional digits in a data surface are a defect.

## Layout

Content lives in a max-width **1200px** container under a **64px** top nav. Spacing runs on a strict 4px base scale (4–96px); density is compact and dashboard-first (15px body, 32px-tall default controls, 16–20px card padding).

Responsiveness is CSS-first: fluid grids and `clamp()` type on the landing page (squeeze points at 860/560/480px), with exactly one JavaScript breakpoint — `(max-width: 767px)` via `useMediaQuery` — for structural swaps like the map's mobile sheet. Two mobile guarantees are load-bearing: the document never exceeds the viewport width (`html, body { max-width: 100%; overflow-x: hidden }` — wide tables and the Kanban board opt back in with inner `overflow-x: auto` wrappers), and on touch devices all text controls are floored at **16px** font (`@media (pointer: coarse)`) so iOS never auto-zooms. Touch targets hold a 40–44px minimum.

## Elevation & Depth

A hybrid dark-ramp system: depth is conveyed by a **light 1px inset "border" plus a soft dark drop shadow**, so cards read as etched glass on slate — never as floating white boxes. Recession uses darker surfaces (`canvas-deep`, `console-black`) rather than shadow.

### Shadow Vocabulary

- **Card** (`box-shadow: inset 0 0 0 1px rgba(255,255,255,0.2), 0 1px 10px 0 rgba(0,0,0,0.2)`): resting elevation for every card and KPI tile.
- **Pop** (`inset 0 0 0 1px rgba(255,255,255,0.2), 0 4px 6px -4px rgba(0,0,0,0.5), 0 10px 30px -5px rgba(0,0,0,0.5)`): hover state of interactive cards; dropdowns, popovers.
- **Modal** (`inset 0 0 0 1px rgba(255,255,255,0.2), 0 20px 25px -5px rgba(0,0,0,0.3), 0 10px 30px -5px rgba(0,0,0,0.3)`): dialogs.
- **Drawer** (`-4px 0 24px 0 rgba(0,0,0,0.5)`): side sheets (X-offset; rotate when the sheet docks to the bottom).
- **Focus ring** (`0 0 0 3px color-mix(in srgb, var(--color-accent) 18%, transparent)`): paired with a turquoise border on focused fields; keyboard focus elsewhere is a 2px accent outline, offset 2px.

### Named Rules

**The Etched Glass Rule.** Every raised surface carries the light inset border *with* its drop shadow. A naked drop shadow on slate reads as a hole, not a lift.

## Shapes

Crisp, workmanlike geometry: **4px** radius on inputs, buttons, and cards; **6px** on modals; full **pills reserved for status, grade, and count chips** — the roundness itself signals "this is a data chip, not a control." Borders are 1px from the ink scale. Surfaces may carry one of three faint white geometric textures (`.tex-weave` 18px crosshatch — the body default, `.tex-dots` 22px, `.tex-grid` 26px) at 3–6% opacity: material, not decoration.

The brand mark is a turquoise diamond cut by a rounded cross into four quadrants with a center node dot — the "axon" — paired with a Roboto Slab wordmark. Its geometry (diamond, cross-cut, node) is the only place the system draws pictorially.

## Components

### Buttons

Tactile and confident: they depress 1px on press (`translateY(1px)`, 100ms) and change fill in 180ms.

- **Shape:** crisp corners (4px); sizes sm/md/lg = 28/32/44px min-height with 12/13/15px labels, weight 500.
- **Primary:** Signal Turquoise fill with a Console Black label (`--text-on-accent`, 5.9:1); hover brightens to Bright Turquoise — filled controls intensify, they never darken, so the ink label holds contrast in every state.
- **Secondary / Outlined:** slate fill (or transparent) with `ink-300` border; hover raises to `surface-hi`.
- **Minimal:** borderless ghost for toolbars; **Danger:** Ember Red fill, ink label, lightened on hover via `color-mix`.
- **Disabled:** 40% opacity, `not-allowed` cursor. **Icon buttons:** 40px square, `ink-400` glyph that turns `ink-900` with a turquoise border on hover; a borderless variant serves the nav.

### Cards / Containers

- **Corner style:** 4px; **background:** Card Slate; **internal padding:** 20px (16px KPI tiles).
- **Shadow strategy:** elevation levels 0–3 = none / Card / Pop / Modal (see Elevation).
- **Interactive cards** lift −1px and step up to Pop on hover.

### Inputs / Fields

- **Style:** Card Slate fill, 1px `ink-200` border, 4px radius, 13px text (16px on touch), `ink-400` placeholder.
- **Focus:** turquoise border + the 3px translucent turquoise ring; no native outline.
- **Error:** Ember Red border. **Disabled:** 55% opacity on a raised fill.
- **Labels:** paired uppercase 11px `t-label` above the field.

### Chips (ScoreBadge / StatusPill / Tag)

- **Style:** pill (or 4px for square tags), soft tinted background + bright foreground per the Soft Pair Rule, 11–12px semibold text, optional 6px status dot.
- **ScoreBadge:** the grade letter is set in the slab display face; tooltip/aria text is the grade's *action* ("A — call first").
- **State:** intents none/primary/success/warning/danger/info map straight onto the semantic palette.

### Navigation

64px top bar on deep slate; borderless icon buttons; the Logo (diamond mark at 28px + slab wordmark) anchors the left. Active/hover states use ink-scale steps, never turquoise fills.

### KPI Tile (signature component)

The dashboard's fingerprint: a Card-Slate tile with a **3px turquoise gradient top-rule** (`accent → accent-300`, 70% opacity), a 10px uppercase eyebrow label, a 26px/700 tabular mono value, an optional moss/rose ▲▼ delta, and a 12px `ink-400` sub-line. Min-height 88px.

### Sheet / Drawer

Side drawer with the Drawer shadow; on mobile it docks to the bottom with a 40×4px grab handle and 44px touch targets.

### Motion

One signature ease — `cubic-bezier(0.4, 1, 0.75, 0.9)` — at two speeds: 100ms (press feedback) and 180ms (state changes). Page content enters via `.axon-rise` (460ms rise-in, per-section `--d` stagger). `prefers-reduced-motion` collapses all of it globally; any new animation must survive that guard.

## Do's and Don'ts

### Do:

- **Do** reach colors through the semantic aliases (`--bg-app`, `--surface-card`, `--text-body`, `--intent-primary`) in product code; raw scale steps are for the design system itself.
- **Do** route every grade and status color through `frontend/lib/gradeColors.ts` — it is the single source of truth, and the map resolves its variable *names* (`gradeVarName()`) because WebGL can't read CSS variables.
- **Do** set every numeral in Geist Mono tabular (`.tabular`), from KPI values to table cells.
- **Do** pair every data foreground with its soft dark tint in chips and badges.
- **Do** keep touch text controls at ≥16px font and interactive targets at ≥40px.
- **Do** use the signature ease at 100/180ms and stagger entrances with `.axon-rise`.

### Don't:

- **Don't** paint data categories turquoise — the accent means "you can act on this," so a turquoise data mark reads as a selected control (the Affordance Hue Rule).
- **Don't** ship light or white surfaces; the system is dark-only, and cream exists solely as text on filled accents.
- **Don't** invent radii — corners are 4px (6px modals); pills are for chips only.
- **Don't** apply a drop shadow without its light inset border (the Etched Glass Rule).
- **Don't** define one-off colors; a new hue joins the data-viz family with a `-soft` pair or it doesn't ship.
- **Don't** drift toward bubbly consumer SaaS — big radii, pastels, playful illustration are the confirmed anti-reference.
