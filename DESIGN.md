# DESIGN.md — Sentinel reviewer console

The design system for every screen in `frontend/`. Agents building UI read this file before writing a component; reviewers check work against it. It sits below `docs/ARCHITECTURE.md` (§4 contracts, §11b palette) and above personal taste. When this file and a brief disagree, the brief wins for that phase and the disagreement is recorded in `docs/DEVIATIONS.md`.

---

## 1. Visual theme & atmosphere

**Who uses it:** a trust-and-safety reviewer deciding whether to let an order through, at a desk, on a laptop or a large monitor, many times a day. Secondarily: hackathon judges watching that reviewer for four minutes.

**What it must feel like:** a case file, not a marketing page. Dense, calm, exact. Every mark on the screen is either evidence, a decision, or the record of a decision. Nothing is decorative.

**The committed direction — "ledger":**
- **Surfaces are separated by rules (1 px lines), not floated as cards.** A page reads top-to-bottom like a document with sections, not like a grid of tiles.
- **Colour is reserved for meaning.** Neutral greys carry the interface; colour appears only where it encodes an action, a risk state or an integrity state. If you removed all colour, the page must still be fully usable; if you add colour, it must mean something.
- **Numbers are first-class.** Money, probabilities and counts use tabular figures and align on the right. Identifiers and hashes are monospaced.
- **Density over spectacle.** Information that a reviewer compares should be visible at once, not behind tabs, carousels or "show more".

**Dials** (Taste Skill's three scales, fixed for this product):

| Dial | Setting | Meaning here |
|---|---|---|
| Design variance | **2 / 10** | Conventional, predictable layout. Reviewers need the same thing in the same place on every order. |
| Motion intensity | **1 / 10** | Hover and focus feedback only. No entrance animations, no scroll effects. |
| Visual density | **8 / 10** | Dashboard density. 13–14 px body, tight rows, many facts per screen. |

---

## 2. Colour palette & roles

Defined once as Tailwind v4 `@theme` tokens in `frontend/src/index.css`. Components use **semantic token names only** (e.g. `bg-surface`, `text-muted`, `border-rule`, `text-action-block`), never raw palette classes like `slate-800` or `red-500`. That keeps the palette changeable in one place and makes misuse greppable.

### Neutrals (the interface)

| Token | Value | Use |
|---|---|---|
| `canvas` | slate-950 `#020617` | page background |
| `surface` | slate-900 `#0f172a` | raised regions: header strip, dialogs, side panel |
| `rule` | slate-800 `#1e293b` | every divider and border |
| `rule-strong` | slate-700 `#334155` | input borders, focused section edges |
| `text` | slate-200 `#e2e8f0` | primary text |
| `text-body` | slate-300 `#cbd5e1` | body text |
| `text-muted` | slate-400 `#94a3b8` | labels, captions, secondary metadata |
| `text-faint` | slate-500 `#64748b` | hashes, versions, disabled |

### Semantic colours (the only colour on the page)

| Token | Value | Means | Never used for |
|---|---|---|---|
| `action-allow` | teal-400 `#2dd4bf` | ALLOW; integrity verified | decoration, links |
| `action-prepaid` | amber-300 `#fcd34d` | PREPAID_ONLY | warnings unrelated to actions |
| `action-review` | amber-500 `#f59e0b` | MANUAL_REVIEW | the synthetic-data notice |
| `action-block` | red-500 `#ef4444` | BLOCK; confirmed-abuse graph nodes; broken audit chain | the abuse score meter, errors in forms |
| `return` | sky-400 `#38bdf8` | return probability only | anything abuse-related |
| `infeasible` | slate-600 hatched | actions removed by a guardrail | — |
| `focus` | sky-300 `#7dd3fc` | focus rings only | — |
| `error` | rose-300 `#fda4af` | form validation and API errors | action states |

Rules:
- **Red means BLOCK or confirmed abuse. Nothing else is red.** Form errors use `error` (rose-300 text, no fill) so a validation message never reads as "this customer is blocked".
- **Amber is taken by the two friction actions.** The synthetic-data notice is therefore neutral, not amber (see §4).
- **The abuse probability meter is neutral.** It does not turn amber or red at thresholds: colour bands on the meter would hard-code policy thresholds (0.50, 0.70) into the frontend and duplicate the job of the action badge. The action badge carries the verdict; the meter carries the measurement.
- **The return meter is `return` (sky).** It is never red, amber or teal, because a high return probability is not a risk verdict.
- **No gradients anywhere.** No gradient text, no gradient fills, no gradient borders.
- Contrast: body text ≥ 4.5:1 on its background; large text and UI glyphs ≥ 3:1. Check every token pair used.
- `color-scheme: dark` on `<html>` so native scrollbars, date inputs and selects match.

---

## 3. Typography

**Faces (self-hosted, offline-safe — no CDN, the demo must run without a network):**
- **IBM Plex Sans** for all interface text. Chosen for its engineered, instrument-like character that suits an audit tool, its clear distinction between `1`, `l` and `I`, and its true tabular figures.
- **IBM Plex Mono** for identifiers, hashes, versions, feature-free code-like strings (`ORD-DEMO-002`, `a3f1c9…`, `abuse-hgb-fs1.0-446c817f`).
- Loaded from `@fontsource/ibm-plex-sans` and `@fontsource/ibm-plex-mono`, weights 400/500/600 only. Fallback: `ui-sans-serif, system-ui, sans-serif` / `ui-monospace, monospace`.

**Scale** (px / line height). Five steps; nothing larger.

| Token | Size / LH | Use |
|---|---|---|
| `text-label` | 11 / 16, 500, uppercase, +0.06em tracking | section labels ("EXPECTED COST", "EVIDENCE") |
| `text-small` | 12 / 16 | captions, table metadata, chips |
| `text-base` | 13 / 20 | body, table cells, reasons |
| `text-strong` | 14 / 20, 500 | row titles, dialog body |
| `text-figure` | 20 / 28, 600, tabular | the key figures: action verdict, the two probabilities, order value |

Rules:
- **No hero headings.** The largest text on any screen is a *figure* (a probability, a price, a verdict), never a title. The page title is `text-strong`.
- `font-variant-numeric: tabular-nums` on every number that can be compared: money, probabilities, counts, times, pp attributions.
- Money and pp values right-aligned in lists and tables.
- Sentence case everywhere except `text-label`. No Title Case Headings.
- Real typography: `…` not `...`, `→` in action transitions, `₹` from the server string, non-breaking space between a number and its unit.

---

## 4. Component stylings

### Sections, not cards

A **section** is a region with a `text-label` heading and content, separated from its neighbour by a `rule` line. That is the default container. Use a filled `surface` region only when the content is a different *kind* of thing from the page (a dialog, a side panel, the sticky decision header). Never nest bordered boxes inside bordered boxes.

### Radii and elevation

| Element | Radius | Shadow |
|---|---|---|
| Buttons, inputs, selects, chips, badges | 2 px | none |
| Dialogs, side panel, tooltips | 4 px | one: `0 8px 24px rgb(0 0 0 / 0.5)` |
| Sections, tables, charts | 0 | none |
| Pills (fully rounded) | **never** | — |

### Buttons

- **One primary action per view**: light fill (`text` background, `canvas` label). On the order detail page that is **Override**. Everything else is secondary (1 px `rule-strong` border, transparent fill) or a text link.
- No icons inside buttons unless the button has no text (then it needs `aria-label`). No arrow glyphs welded to labels.
- Labels are verbs describing the outcome: "Apply override", "Open appeal", "Reload order". Never "Submit", "Continue", "Get started".
- Destructive or irreversible outcomes (override to BLOCK) get a confirmation line inside the dialog stating the effect in plain words, not a second modal.

### Badges

Badges are allowed for exactly three things, and nothing else:
1. **Action** (ALLOW / PREPAID ONLY / MANUAL REVIEW / BLOCK), in its semantic colour, as text on a 10 % tint with a 1 px border in the full colour.
2. **Evidence strength** (STRONG / MODERATE / WEAK), neutral, weight-coded (600 / 500 / 400), never coloured.
3. **Guardrail chips** on infeasible cost bars (`G2`, `G3`, `G5`), neutral, mono.

Status (`PENDING_REVIEW`, `OVERRIDDEN`) is plain `text-muted` text, not a badge. The `SYNTHETIC` marker is plain text in the header metadata row, not a badge.

### Data display

- **Meters** (the two probabilities): a 4 px track in `rule`, filled in `return` or neutral `text-muted`, with the figure above it. The abuse meter's "without relationship evidence" marker is a 1 px tick with a caption below, not a second bar.
- **Cost bars**: fixed order ALLOW → PREPAID_ONLY → MANUAL_REVIEW → BLOCK; zero-based; value label at the bar end from the server `display` string; selected bar in its action colour, others in `rule-strong`; infeasible bars hatched.
- **Lists of reasons**: one row per reason, a 3-column grid (strength · sentence · pp), rows separated by `rule`. Not cards.
- **Audit timeline**: a vertical rule with events as rows; timestamp and hash in mono `text-faint`.
- **Graph** (`@xyflow/react`): node shapes carry the kind, colour carries only state (current / confirmed / linked / neutral). The legend is always visible and uses the same shapes. Solid edge = counted evidence; dashed = discounted, with the reason on hover.

### Icons

Default: **no icon**. Text labels are clearer for this audience. Icons are allowed only where the glyph is the fastest way to read the information: the graph node shapes and legend, and the chain-integrity check mark. No icon library is added for decoration; no icons in rounded squares; no icons as bullet points.

### Notices

- **Synthetic-data notice:** a single `text-small` line in `text-muted`, pinned at the bottom of the viewport inside a 1 px top rule. Neutral, always visible, never dismissible, never coloured. It is a disclosure, not an alarm.
- **Degraded mode:** stated inline where the missing thing would be ("No model score — degraded mode"), in `text-muted`. Not a banner.

---

## 5. Layout principles

- **Spacing scale** (px): 4, 8, 12, 16, 24, 32. Nothing else. Vertical rhythm: 24 between sections, 12 between a label and its content, 8 inside rows.
- **Order detail layout** (desktop, ≥ 1280 px): a sticky decision header; then two columns at **3 : 2** — left: scores, expected cost, relationship graph; right: prediction sentence, evidence, model attribution, baselines, audit timeline. The verdict and the reasons for it are visible without scrolling at 1440 × 900.
- Left-aligned text, left-aligned layout. Nothing centred except empty-state messages inside their own region.
- Navigation is a slim left rail with text links (Overview, Queue). No logo lockup beyond the word "Sentinel" in `text-strong`.
- Page width is fluid; no `max-w-7xl mx-auto` marketing container. The reviewer's monitor width is used.

---

## 6. Depth & elevation

Flat by default. Exactly two layers exist above the page: **overlays** (dialogs, side panel) and **tooltips**. They get the single shadow in §4. No glassmorphism, no blur, no translucent panels over content.

---

## 7. Do's and don'ts

**Do**
- Put the verdict, the two scores and the reason sentence where the eye lands first.
- Show the guardrail that removed an action next to the action it removed.
- Keep the same element in the same place on every order so reviewers build muscle memory.
- Remove a decoration before adding one.

**Don't**
- Hero sections, oversized headings, landing-page structures.
- Card grids, icon + title + description tiles, repeated rounded rectangles.
- Gradients, glass, glow, multiple shadows, pill buttons.
- Colour bands on the abuse meter, traffic-light thresholds, or any colour that encodes a policy number.
- Badges for things that are just text.
- Entrance animations, skeleton shimmer, animated counters, pulsing dots, live-alert tickers.
- Copy like "Powerful", "Seamless", "AI-powered insights". State what happened.
- Any number formatted in the browser that the server already formatted.

---

## 8. Responsive behaviour

- **Primary target:** 1440 × 900. **Fully supported:** ≥ 1280 wide. **Degraded but usable:** 1024–1279, where the two columns stack (decision header, left column, right column) and the graph gets full width.
- **Below 1024:** a single column in the same order, read-only use acceptable. Reviewing on a phone is not a product goal; nothing may overflow horizontally, but no layout is designed for it.
- The decision header stays visible (sticky) at every width.

---

## 9. Interaction & accessibility

From the Vercel Web Interface Guidelines, applied to this product:

- Every interactive element has a visible `:focus-visible` ring in `focus`, 2 px, offset 2 px. Never `outline: none` without a replacement.
- Full keyboard path on the detail page: Tab reaches Override, Open appeal, the assumptions link, the graph's zoom and fit controls, and each guardrail chip (chips are focusable; their detail shows on focus as well as hover).
- Dialogs trap focus, restore focus to the opener on close, close on Esc, and use `overscroll-behavior: contain`.
- Form labels are real `<label>` elements. Errors render inline next to the field in `error`, and focus moves to the first invalid field on submit. The submit button stays enabled until the request starts, then shows "Applying…".
- Icon-only controls have `aria-label`. Colour is never the only carrier of meaning: action badges have text, dashed edges have a legend entry, infeasible bars have chips.
- Honour `prefers-reduced-motion`: transitions become instant. Transitions animate only `opacity`, `color` and `background-color`, ≤ 150 ms; never `transition: all`.
- Loading: skeleton blocks in the final layout's shape, static (no shimmer). Text reads "Loading…". Empty arrays render an explicit empty state, never a broken chart.
- Minimum hit target 32 × 32 px for pointer controls in this dense layout.

---

## 10. Content & voice

- Plain, factual, specific. Say what the system did and why, with the number: "BLOCK was not permitted: G3 requires a score of at least 70 %; this order scored 69.1 %."
- Never overclaim. Synthetic results are labelled as synthetic; counterfactuals are labelled as counterfactuals; attributions are labelled "not additive".
- Probabilities as percentages with one decimal; below 0.1 % render `<0.1%`.
- Actions are written in upper case with spaces in badges (MANUAL REVIEW) and as enum values nowhere visible to users.

---

## 11. Agent prompt guide & review checklist

Before building UI: read §1, §2, §4 and §7 of this file, then the brief.

Before committing UI, check every item:

1. Does any element use a raw palette class instead of a semantic token?
2. Is anything red that is not BLOCK, confirmed abuse or a broken chain?
3. Is there a gradient, a blur, a second shadow, or a fully rounded pill?
4. Is there a card that should be a section, or a bordered box inside a bordered box?
5. Is there a badge for something that is not an action, an evidence strength or a guardrail?
6. Is there an icon that text would say more clearly?
7. Is the largest text on the screen a figure rather than a title?
8. Are all compared numbers tabular and right-aligned?
9. Is any money formatted in the browser?
10. Does any colour or position encode a policy threshold?
11. Can the whole detail page be operated by keyboard, with visible focus?
12. Does every async region have loading, empty and error states?
13. Is there any motion beyond a ≤ 150 ms colour or opacity transition?
14. Would a reviewer find the verdict, both scores and the reason sentence without scrolling at 1440 × 900?

A "yes" to 1–6, 9, 10 or 13, or a "no" to 7, 8, 11, 12 or 14, is a defect.
