# Phase 8 brief: Phase 7 follow-ups, then the order detail page

*(The operator calls this "stage 7 fix and stage 8 build"; the operating manual calls it stage 9. Phase numbering here matches `docs/ARCHITECTURE.md` §12.)*

Issued by the Architect after reviewing `docs/reports/phase-7.md`.

**This is the screen the live demo happens on.** Every number, label and sentence on it will be read by judges. Correctness and honesty come before polish; polish comes before extra features, and there are no extra features.

Read before writing code: `docs/ARCHITECTURE.md` §4 (contracts), §11 (demo scenarios and script), §11b (dashboard layout and palette); `docs/DEVIATIONS.md` in full, especially #14, #27, #29, #32–#34; `docs/reports/phase-7.md` (the Demo 2 detail JSON is your reference payload).

Usage note: iterate with `pytest -m "not slow"` and `npm run build`. Full suite only before each commit.

Two commits: Part 1 as `phase 7: follow-ups`, Part 2 as `phase 8: order detail`.

---

## Part 1 — Phase 7 follow-ups (backend)

**1.1 Graph must agree with the numbers beside it.** Demo 2 shows 3 of its 4 linked orders from the last 24 h, because the fourth comes from an account two hops away. A judge will count.
- Extend the graph view: every account whose order is counted in `linked_orders_24h`, and every account counted in `device_confirmed_peer_count`, appears in the graph, together with the intermediate identifier nodes that connect it, even when it is two hops away.
- These nodes take priority over other linked accounts under the 40-node cap. They are never dropped while unrelated accounts remain.
- Add two fields to `GraphPayload`: `linked_orders_24h_shown` and `confirmed_peers_shown` (integers). Record the contract addition in a deviation.
- Stored seeded payloads: regenerate them with `seed-db`.
- Tests: for all three demos and every seeded decision, the number of 24 h order nodes equals `linked_orders_24h`, and confirmed-account nodes reachable through the device equal `device_confirmed_peer_count`. The only exception is `truncated = true`, in which case the `*_shown` fields state the shown counts and the UI will say so.

**1.2 Policy assumptions endpoint.** The UI's "Demonstration assumptions" panel needs the real values, never hard-coded ones. Add `GET /api/v1/internal/policy` (internal key required), returning:
- `policy_version`, `policy_config_sha256`, `notice`
- every section and value of `policy_v1_0.toml`
- a `Money` object for every `*_inr` value (server-formatted)

Regenerate `openapi.json` and `types.ts`. Add an auth test and a test that the values equal the loaded config.

**1.3 Which action is counted.** Record in #34: `/metrics` `action_distribution` counts the **system recommendation**; the queue filters on the **current action** (after review). No code change. The UI labels each one explicitly (see Part 2).

**1.4 Probe logging only for valid requests.** Accepted: storing a malformed device id could store raw personal data. Record the reason in #34.

Part 1 gate: full suite green, `seed-db` re-run, commit, push.

---

## Part 2 — Phase 8: order detail page

Route: `/orders/:orderId`. Out of scope: the queue page and the "Simulate checkout" presets (Phase 9), and the Overview page (Phase 10). Leave their placeholders as they are.

### A. Ground rules for all frontend code

1. **Types come only from the generated `src/api/types.ts`.** No hand-written API types, no `any`, no non-null assertions on API data.
2. **Money is never formatted in the browser.** Render the server's `display` strings. `lib/format.ts` may format probabilities and timestamps only.
3. **Probabilities:** one decimal place as a percentage. Values below 0.1 % render as `<0.1%`, never `0.0%`. Null (degraded mode) renders `No model score`.
4. **The return and abuse scores are never combined,** averaged, summed or placed on a shared scale into one "risk" number anywhere on the page.
5. **No hard-coded values:** no thresholds, costs, guardrail numbers, policy versions or model versions in the frontend. They come from the API.
6. **Palette** (§11b), defined once as Tailwind v4 theme tokens in `index.css`:
   - base `slate-950` / `slate-900`, borders `slate-800`, body text `slate-300`
   - `sky-400`: return probability only, **never red**
   - `teal-400`: ALLOW and verified states
   - `amber-300`: PREPAID_ONLY; `amber-500`: MANUAL_REVIEW
   - `red-500`: **only** BLOCK and confirmed-abuse graph nodes
   - hatched `slate-600`: infeasible actions
   - Text contrast at least WCAG AA against its background.
7. **No animation** beyond ~150 ms hover/focus transitions. No live-alert tickers, no animated counters, no glitch or "hacker" styling.
8. Target viewport 1440×900, usable down to 1280 wide. Nothing overflows horizontally at 1280.

### B. Page layout, top to bottom

**B1. Header and policy decision card**
- Left: order id, placed-at time, `order_value.display`, account age in days, prior orders, and a `SYNTHETIC` badge.
- Right: the **policy decision card**:
  - large action badge showing `current_action`
  - status (`AUTO_APPLIED`, `PENDING_REVIEW`, `OVERRIDDEN`, `APPEAL_OPEN`)
  - if overridden: "System recommended: X" under the badge
  - policy version, first 8 characters of the policy fingerprint, both model versions (small, muted)
  - buttons: **Override** and **Open appeal**
- Degraded decision: a visible "Degraded mode: no model score" notice in place of the scores.

**B2. Two score cards, side by side, never merged**
- **Return probability** (`sky-400`): percentage and a horizontal 0–100 % meter. Caption, verbatim: *"Operational context — not used for action selection."* RETURN-model reasons (`model == "RETURN"`) are listed **here**, under this card, and nowhere else.
- **Abuse probability**: percentage and a 0–100 % meter; neutral fill below 50 %, amber at 50–70 %, red at 70 % or above. A ghost marker on the same meter shows `p_abuse_without_graph_evidence`, captioned *"Without relationship evidence: X% (counterfactual: relationship features set to typical values)"*.
- The two meters are separate components with separate scales. Test that they never share one.

**B3. Expected-cost comparison** (Recharts horizontal bars)
- Four bars in **fixed order**: ALLOW, PREPAID_ONLY, MANUAL_REVIEW, BLOCK. Never re-sort by value, so the same position means the same action on every order.
- Bar length = `expected_cost.inr`. Label at the bar end = `expected_cost.display`. The axis starts at zero.
- **Selected action:** full action colour and a "Selected" tag. Other feasible actions are muted.
- **Infeasible actions:** hatched `slate-600` fill plus a chip per guardrail in `excluded_by` (e.g. `G2`, `G3`, `G5`). Hovering a chip shows that guardrail's `detail` text from the response.
- If `cost_optimal_action ≠ selected_action`: a "Lowest cost" marker on the cost-optimal bar, with the guardrail that removed it.
- Tooltip per bar: abusive branch, genuine branch and operational cost, each as a server `display` string.
- Under the chart, render `policy.policy_explanation` verbatim, then a **"Demonstration assumptions"** link that opens a read-only side panel populated from `GET /internal/policy` (1.2), headed by the notice text.
- Degraded decision: hide the chart; show "Costs are not computed without a model score (degraded mode)."

**B4. Relationship graph** (`@xyflow/react`), about 60 % width, with the evidence panel beside it
- Use the server's `x` and `y` positions exactly. `nodesDraggable = false`, `nodesConnectable = false`, `elementsSelectable = false`. Controls: zoom and fit only. Call fit-view on load.
- Node shape by `kind`: ACCOUNT circle, DEVICE square, ADDRESS diamond, PAYMENT_TOKEN rounded rectangle, ORDER small dot.
- Node state: CURRENT has a teal ring and is larger; CONFIRMED_ABUSE has a red fill; LINKED is slate; NEUTRAL is dim slate. Flags (`MULTI_TENANT`, `SEQUENTIAL_DEVICE`, `HIGH_FANOUT`, `RECENT_24H`) as small badges.
- Edges: solid when `counted_as_evidence = true`; **dashed** when false, with the `discount_reason` in a tooltip.
- A legend explaining every shape, colour and the dashed edge. Always visible, not hidden behind a toggle.
- If `truncated`: *"Showing N of M nodes"*. Use `linked_orders_24h_shown` and `confirmed_peers_shown` wherever a count is printed next to the graph.
- Labels are the server's masked `label` only.

**B5. Evidence and model attribution** (two clearly separate panels, per #27)
- **Prediction explanation:** `prediction_explanation` rendered verbatim at the top, as the one-sentence summary.
- **Evidence** panel: ABUSE-model `reasons` in the server's order (strength first). Each row: `evidence_strength` tag, `reviewer_text`, `attribution_pp` as "+X.X pp to the score", and, when present, the `attribution_note` in muted italics beneath. Mitigating reasons in a separate "Mitigating factors" group.
- **Model attribution** panel: the same ABUSE codes sorted client-side by `|attribution_pp|` descending, as a small horizontal bar list in probability points. Caption, verbatim: *"What moved the model's score. Contributions overlap and are not additive."* Never display a sum of attributions anywhere.

**B6. Audit timeline and baselines**
- **Audit timeline** from `audit_events`, oldest first. Per event: type, actor (SYSTEM or the reviewer id), timestamp, `previous_action → new_action`, reason category and text for overrides, and the first 10 characters of `event_hash`. A header badge from `GET /audit-events/verify`: **"Chain verified ✓"** in teal, or **"Chain broken at event N"** in red.
- **Baselines** strip: *"How the baselines would decide"*: FIXED_THRESHOLD and RULE_BASED, each with its action badge and `rule_fired` text. Caption: *"For comparison only. Sentinel's action is the one above."*

### C. Override and appeal dialogs

- **Override:**
  - new-action select (all four actions)
  - reason category select (the five §4 values)
  - reason text with a live character count; submit disabled until ≥ 15 characters
  - `expected_current_action` sent automatically; `X-Reviewer-Id` from a small reviewer picker in the header (`reviewer-placeholder-01`, `-02`, `-03`), persisted in `localStorage` with a try/catch fallback
  - after success, show the returned `warnings`, refetch the detail, and let the new audit event appear in the timeline
  - 409 → "This order was changed by someone else. Reload to see the latest." with a Reload button
  - 422 → show the server message beside the field
- **Appeal:** channel select, a note of ≥ 10 characters, and the returned reference shown after success.

### D. States (all required)

- **Loading:** skeleton blocks in the final layout's shape. No spinners that shift layout.
- **Not found (404):** "Order not found" with a link back to the queue.
- **API error:** message plus a Retry button. Never a blank screen.
- **Degraded decision:** as in B1 and B3.
- **Empty graph** (no linked entities): "No relationships found for this order", with the current node still drawn.

### E. Frontend tests

Add `vitest`, `@testing-library/react`, `@testing-library/jest-dom` and `jsdom` as devDependencies at **exact pinned versions** (approved; record in #16). Add `npm test`. Use recorded API fixtures captured from the real backend: the Demo 1, 2 and 3 detail payloads, one degraded decision, one overridden decision, stored under `src/__fixtures__/`.

Tests:
- Scores: two separate meters for all three demos; no element renders a combined score; the return card never uses a red class; `<0.1%` for Demo 1's abuse probability.
- Money: every rendered money value appears verbatim in the fixture's `display` strings (scan the rendered text against the fixture).
- Cost chart: fixed action order; the selected bar is tagged; infeasible bars carry their guardrail chips (Demo 2's ALLOW shows `G5`; Demo 3's BLOCK shows `G3`); the degraded fixture hides the chart.
- Graph: node and edge counts equal the fixture; dashed edges exactly match `counted_as_evidence = false`; the legend is present.
- Evidence vs attribution: Demo 2's evidence panel lists STRONG codes first; the attribution panel is sorted by `|attribution_pp|`; the redundancy note renders; no summed attribution appears.
- Overridden fixture: "System recommended: X" appears; the audit timeline shows the override.
- Override dialog: submit disabled under 15 characters; 409 renders the reload message.
- No hard-coding: a source scan finds no numeric literal equal to any policy config value, and no `v1.0` or model-version string, in `src/`.

### F. Visual check (required if a browser tool is available to you)

Run the backend (`python -m sentinel.cli serve`) and the frontend (`npm run dev`). Score the three demo presets through the API, then open each detail page at 1440×900. Save screenshots to `docs/reports/phase-8/demo-1.png`, `demo-2.png`, `demo-3.png`, plus one of the override dialog and one after an override. The Architect reviews these images directly. If you have no browser tool, say so in the report.

### G. Progress reporting (required)

At the start, after Part 1, after each Part 2 section A–F, and in the final report. Elapsed time from real timestamps:

```
PROGRESS  phase 8 of 12  [#######---]  8/11 stages to Definition of Done (73%)
          this phase: B4. relationship graph — 4 of 9 sections done  |  elapsed 1h05m
```

Sections: Part 1, A, B, C, D, E, F, gate (count B as one section; report its sub-steps B1–B6 in the text).

### H. Gate and report

- Full backend suite including slow, `npm run build`, and `npm test` before the Part 2 commit. Push after each commit.
- Report to `docs/reports/phase-8.md`, and update `docs/PROGRESS.md` and the README build status.
- Report contents:
  1. files changed
  2. test results (backend and frontend) and build output size
  3. the screenshots, or a statement that none were possible
  4. for each demo: the exact text rendered in the decision card, both score cards, the policy explanation and the evidence panel
  5. deviations added
  6. open questions
  7. `git status -sb` and `git log --oneline -5`
- Stop. Do not start Phase 9.
