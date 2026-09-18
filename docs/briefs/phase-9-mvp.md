# Phase 9 brief: Phase 8 follow-ups, then the MVP (queue, simulate checkout, overview, demo reset)

*(Spec phases 9 and 10 combined to save a review round; the operating manual calls them stages 10 and 11. Phase numbering here matches `docs/ARCHITECTURE.md` §12.)*

Issued by the Architect after reviewing `docs/reports/phase-8.md`, the branch diff, the six screenshots, and a local re-run (backend full suite, `npm test` 105/105, `npm run build`).

**Goal:** after this phase, the whole demo runs end to end in the browser. Reset → Queue → "Simulate checkout" → order detail, for all three demos, plus an Overview that shows the synthetic backtest honestly. That is the Definition of Done (§12 cut line). The design pass comes after, so **don't polish**. Build it correct, consistent and complete.

Read before writing code (exclusive list, per `BUILDER_HEADER.md`):
- `docs/ARCHITECTURE.md` §4 (`QueueFilters`, `QueueItem`, `QueueResponse`, `MetricsResponse`, `StrategyBacktest`), §9.3, §11, §11b and §12
- `docs/DEVIATIONS.md` #14, #27, #34, #35, #36 and #37
- `docs/reports/phase-8.md` §4 and §7
- `DESIGN.md` §2 and §7

The four correctness rules in `BUILDER_HEADER.md` are part of the gate.

Usage note: iterate with `pytest -m "not slow"`, `npm test` and `npm run build`. Run the full suite only before each commit.

Two commits: Part 1 as `phase 8: follow-ups`, Part 2 as `phase 9: mvp`.

---

## Part 1: Phase 8 follow-ups

Phase 8 is accepted and merged. Each item below is a defect a judge could read on screen. The architect caused 1.1; the rest came up in the review.

**1.1 The abuse meter is neutral.** *(Architect's error in the Phase 8 brief, B2.)* The meter currently turns amber at 50 % (`AMBER_FROM_PERCENT = 50` in `ScorePair.tsx`, a policy-like number written into the frontend) and red at G3's `block_min_p_abuse`. The screenshots show it: Demo 3's meter is amber at 69.1 % and Demo 2's is red. Colour bands on the meter encode policy thresholds and repeat the action badge's job (DESIGN.md §2, §7).
- Fill the abuse meter in one neutral token at every value. Remove `AMBER_FROM_PERCENT`, the block band and `blockFromPercent`. Delete `lib/policy.ts` if nothing else uses it.
- Leave the ghost marker for `p_abuse_without_graph_evidence` unchanged.
- Test: the meter's fill is identical for the Demo 1, 2 and 3 fixtures, and the meter never carries an action colour.
- Update #37.

**1.2 The redundancy note must be true for the code it sits under.** `REDUNDANT_NOTE` in `models/reason_codes.py` reads "Redundant with other **relationship** evidence…" on every code. It currently renders under `MITIGATING_ESTABLISHED_ACCOUNT` (Demo 1) and `ACCOUNT_PRIOR_SUSPICIOUS_CLAIM` (Demo 3), and neither is relationship evidence.
- Keep the current text for codes whose predicate features are all in `ABUSE_GRAPH_FEATURES`.
- Every other code gets: "Redundant with other evidence; the score is already explained by correlated features."
- The firing rule and the 2.0 pp threshold stay as they are.
- Tests cover both variants on the demo rows.
- Re-run `seed-db`. Re-record the frontend fixtures that change.
- Record the change in #27.

**1.3 Reviewer-facing probability text uses the page's format.** The policy explanation reads "G3 requires p_abuse of at least 0.70; this order scored 0.691", while the card above it shows 69.1 %. Demo 1 reads "scored 0.000" beside a card showing `<0.1%`.
- Add one server helper, `format_probability()`, beside `format_inr` in `sentinel/money.py`. Use the frontend's rule: one decimal as a percentage, `<0.1%` below 0.1 %, and `0%` only for an exact zero.
- Use it in `policy/guardrails.py` (the G3 and G5 detail strings and any other probability in a detail) and in the baselines' `rule_fired` text (e.g. "p_abuse >= 0.75").
- Write "abuse probability" instead of the variable name `p_abuse`.
- Target G3 wording: "G3 requires an abuse probability of at least 70.0%; this order scored 69.1%."
- Leave the action enum names in the explanation as they are. §6.5's own example uses them, and the design pass decides that.
- Update the explanation tests (including `test_c7_demo_1_explanation`) to the new full sentences. Changing the expected text is fine here: this is a deliberate wording change, not a loosened check.
- Re-run `seed-db`, re-record the fixtures, and record the change as a new deviation.

**1.4 No "(s)" plurals in reviewer text.** `policy/guardrails.py:111` renders "0 suspicious claim(s)" and "1 suspicious claim(s)" in the signal details. Make it count-aware, as #27 1.3 did for reason templates. Grep `sentinel/` for any other `(s)` in reviewer-facing strings and fix those too.

**1.5 Timestamps in the demo's timezone, not the laptop's.** Phase 8 open question 3. `formatTimestamp` uses the browser's zone, so the screenshots say 4:55 am for an order placed at 10:25 IST.
- Format every timestamp in `Asia/Kolkata`, the offset `DEMO_CLOCK` carries, and suffix it "IST".
- Test: render a fixture under `TZ=UTC` and assert that Demo 1's placed-at reads 10:25.

**1.6 Action and reason names read as labels, not enums, in text the frontend controls.**
- The decision card's "System recommended: MANUAL_REVIEW" and the audit timeline's `MANUAL_REVIEW → PREPAID_ONLY` use the labels from `lib/actions.ts` ("Manual review → Prepaid only").
- Override reason categories are humanised ("Customer verified").
- Server sentences rendered verbatim (the policy explanation) are not rewritten in the browser.

**1.7 Evidence-strength tags don't stretch.** In every screenshot the STRONG/MODERATE tag box grows to the full row height. Align it to the top of the row. This is a CSS change only.

**1.8 Graph order badges.** Phase 8 open question 1: remove the `RECENT_24H` badge from ORDER nodes, and change the legend's Order entry to "Order placed in the last 24 h".
- First add a test that every ORDER node in the three demo payloads and all 250 seeded payloads carries `RECENT_24H`. If any does not, stop and escalate rather than change the legend.
- Leave the panel height alone. That belongs to the design pass.

**Decided, no work:** open question 2 (the scan's `{0, 1, 2, 100}` exclusion) is accepted as is. Open question 4 (evidence and attribution disagreeing on Demo 2) goes into the demo script, not the UI.

Part 1 gate: full backend suite green, `npm test`, `npm run build`, `seed-db` re-run. Then commit and push.

---

## Part 2: Phase 9, the MVP

Routes: `/` (Overview) and `/queue` (Queue). Both replace their placeholders. `/orders/:orderId` exists already. Section A of the Phase 8 brief (ground rules: generated types only, no browser money formatting, probability format, scores never combined, nothing hard-coded, palette, motion, 1280 px) applies to all new code unchanged.

### A. Queue page (`/queue`)

- Table from `GET /internal/orders`. One row per `QueueItem`, with these columns in order:
  - order id (links to `/orders/:orderId`)
  - scored at
  - `order_value.display` (right-aligned)
  - **Return probability**
  - **Abuse probability**
  - recommended action (badge)
  - current action (badge)
  - status
  - `graph_risk_summary`
  - source

  Return and abuse are two columns with their own headers. They are never combined, and the return column is never red. A degraded row shows `No model score`.
- Filters bound to `QueueFilters`: current action, status, source, graph evidence, and sort (all four sort keys). Put the filter state in the URL query, so a reload keeps it.
- Label the action filter and the counts row explicitly: **"Current action (after review)"**, because #34 says the queue counts the current action. Render `counts_by_action` in the fixed action order.
- Pagination: `limit` 50 with previous and next buttons, and "Showing a–b of `total`".
- States: loading skeleton, "No orders match these filters" with a Clear filters link, and an API error with a Retry button.

### B. Simulate checkout (on the Queue page, above the table)

- Load the presets from `GET /internal/demo/presets`, which returns a list of `ScoreOrderRequest`. If the call returns 404 (`DEMO_MODE` off), don't render the panel at all.
- Show one button per preset, in the order the server returns them. Label each from the preset's own data: `order_id`, the first line's category, and `payment_method`. **Never special-case a demo id** and never hard-code a label per preset.
- Clicking a button sends the preset to `POST /internal/score-order` **unmodified**, then navigates to `/orders/{response.order_id}`. A second click on the same preset is an idempotent replay, so it simply navigates again. The button reads "Scoring…" and is disabled while the request is in flight.
- On an error, show the server message beside the button. The page must stay usable.

### C. Reset demo

- Put a secondary "Reset demo" button in the Simulate checkout panel, so it exists only when the panel does (`DEMO_MODE` on).
- Clicking it shows an inline confirmation line (DESIGN.md §4): "This deletes every scored demo and live decision and rebuilds the database. Reset demo?" with Confirm and Cancel.
- Confirm calls `POST /internal/demo/reset`. Show "Resetting…" while it runs (it takes about 10 s), then "Demo reset: N decisions", using the `DemoResetResponse`, and refetch the queue.
- Check in the browser that after a reset all three presets score again, each detail page matches its Phase 8 content, and the audit chain verifies.

### D. Overview page (`/`), minimal

Two sections, visibly separate, each with its own label and source line.

1. **Decision activity**, from `activity`, labelled *"Decision activity: decisions in this database, counted by system recommendation"* (#34):
   - `orders_evaluated`
   - `action_distribution` in the fixed action order
   - `friction_orders`
   - `manual_review_volume`
   - `override_rate`
   - `model_estimated_cost_avoided.display`, labelled "Model-estimated cost avoided (estimate, not realized)"
   - `weak_evidence_decisions`

   Plain figures in a row. No animated counters, no charts.
2. **Synthetic backtest**, from `backtest`, labelled *"Synthetic backtest: realized cost against synthetic labels on the held-out TEST split. Monetary values are demonstration assumptions."*
   - A table with one row per strategy, in fixed order: SENTINEL, FIXED_THRESHOLD, RULE_BASED, ALLOW_ALL.
   - Every `StrategyBacktest` field is a column. Money comes from `display`. Rates are shown as percentages with one decimal, and `manual_reviews_per_1000` with one decimal.
   - **No row is highlighted, coloured or marked "best".** The tuned fixed-threshold baseline has a lower realized cost than Sentinel, and the table must show that plainly. The UI makes no claim about which row wins; the demo script explains the trade.
   - Include the policy version from `/health` in the label. Don't hard-code it.
   - `cold_start_ring_recall` goes on one line under the table: "Cold-start ring (R3, unseen in training): recall X%".

Calibration chart, sensitivity sweep and cohort tables stay out of scope (Phase 11). The carried TODO stays open.

### E. Frontend tests

- Record new fixtures from the real backend: a queue page, the presets, a score-order response, and metrics.
- Queue:
  - the two probability columns are separate and the return column never uses a red class
  - money appears verbatim from `display`
  - the counts are labelled "current action"
  - filter changes update the URL query
- Presets:
  - clicking sends the exact preset body and navigates to the returned order id
  - with presets returning 404, neither the panel nor the reset button renders
- Reset: the confirmation step comes before the POST, and the queue refetches afterwards.
- Overview:
  - the backtest rows come in fixed order
  - no row carries a highlight or an action colour
  - the activity and backtest sections are separate, with their labels
- Every page (Overview, Queue, Order detail) renders the synthetic-data notice verbatim.
- The no-hard-coding scan covers the new files.

### F. Visual check (required if a browser tool is available)

With `serve` and `npm run dev` running, do the full demo path at 1440×900: reset → queue → Demo 1 → back → Demo 2 → back → Demo 3 → override → back to queue (the counts reflect the override) → overview.

Save these to `docs/reports/phase-9/`:
- `queue.png` (after the three demos are scored)
- `queue-filtered.png`
- `overview.png`
- `reset-confirm.png`
- `demo-3-detail.png` (to show the Part 1 fixes: neutral meter, IST times, labels)

Measure horizontal overflow at 1280 on all three routes.

### G. Progress reporting (required)

Print this at the start, after Part 1, after each Part 2 section A–F, and in the final report. Take elapsed time from real timestamps:

```
PROGRESS  phase 9 of 12  [#########-]  10/11 stages to Definition of Done (91%)
          this phase: B. simulate checkout — 3 of 8 sections done  |  elapsed 0h52m
```

Sections: Part 1, A, B, C, D, E, F, gate. After the gate the bar reads `11/11 stages to Definition of Done (100%)`.

### H. Gate and report

- Before the Part 2 commit: full backend suite including slow, `npm test` and `npm run build`. Push after each commit.
- Write the report to `docs/reports/phase-9.md`, and update `docs/PROGRESS.md` (one row for Phase 8 follow-ups plus Phase 9, marking the Definition of Done) and the README build status.
- Report contents:
  1. files changed
  2. test results (backend and frontend) and build size
  3. the screenshots, or a statement that none were possible
  4. the exact rendered text for Demo 3's policy explanation and evidence panel after Part 1, the Overview's two section labels, and the backtest table as rendered
  5. how long the reset took in the browser
  6. deviations added
  7. open questions
  8. `git status -sb` and `git log --oneline -5`
- Stop. Do not start the design pass or Phase 11.
