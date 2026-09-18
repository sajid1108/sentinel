# Phase 8 — Phase 7 follow-ups and the order detail page: gate report

*Spec phase 8 (`docs/ARCHITECTURE.md` §12); `october_master_architecture.md` calls it stage 9. Brief:
`docs/briefs/phase-8-order-detail.md` (Part 1 = Phase 7 follow-ups, Part 2 = Phase 8).*

```
PROGRESS  phase 8 of 12  [########--]  9/11 stages to Definition of Done (82%)
          this phase: gate — 8 of 8 sections done  |  elapsed 4h35m
```

Elapsed is wall clock from the session's first command (`date -u`, 05:51:25Z) to the gate. Active build time
is roughly 2h15m; the rest is the four full backend suite runs (3m40s each), three `seed-db` runs, the fixture
capture, the browser pass, and gaps between turns.

Both commits are green on the full suite (slow included) and pushed. Phase 9 is not started.

| Commit | What |
|---|---|
| `fa43f4b` | `phase 7: follow-ups` (Part 1) |
| `556ae6a` | `phase 8: order detail` (Part 2) |

Progress lines printed during the session:

| Checkpoint | Sections done | Elapsed |
|---|---|---|
| start | 0 of 8 | 0h01m |
| Part 1 committed (`fa43f4b`) | 1 of 8 | 0h23m |
| A–F (ground rules, layout, dialogs, states, tests, browser pass) | 7 of 8 | ~4h00m |
| gate | 8 of 8 | 4h35m |

A–E were built as one pass over the page (the components only make sense together) and checkpointed at F,
when the real browser confirmed them.

---

## 1. Files changed

**Part 1 — `fa43f4b` (`phase 7: follow-ups`)**

| File | Change |
|---|---|
| `backend/sentinel/features/graph_features.py` | `Reached` records the BFS parent; new `PathEdge`; `EgoView` gains `depth_of`, `parent_of`, `path_edges`, `must_draw`, `confirmed_device_peers`; `recent_orders` now covers every reliable-component account (1.1) |
| `backend/sentinel/api/services/graph_view.py` | draws the counted accounts and the identifier hops that reach them; cap prioritises them; ring per account hop; reports the two `*_shown` counts (1.1) |
| `backend/sentinel/api/schemas.py` | `GraphPayload.linked_orders_24h_shown`, `confirmed_peers_shown`; `PolicyAssumptionValue` / `PolicyAssumptionSection` / `PolicyAssumptionsResponse` (1.1, 1.2) |
| `backend/sentinel/api/routers/internal_policy.py` | **new**: `GET /policy` (1.2) |
| `backend/sentinel/api/main.py` | registers the policy router |
| `backend/sentinel/policy/config.py` | `_SECTIONS` → `SECTIONS` so the route enumerates the loaded config rather than re-parsing the TOML |
| `backend/tests/scenarios/test_db_audit_scoring.py` | +3 tests (replay over all 250, the stored payloads, the three demos); `test_seeded_graphs_contain_nothing_first_seen_at_or_after_t0` extended to resolve every identifier node and check every non-own edge |
| `backend/tests/api/test_api.py` | +2 policy-endpoint tests; `/policy` added to the auth and route-table lists |
| `frontend/src/api/openapi.json`, `types.ts` | regenerated |
| `docs/DEVIATIONS.md` | #35, #36 added; #34 updated with 1.3 and 1.4 |

**Part 2 — `phase 8: order detail`**

| File | Change |
|---|---|
| `frontend/src/index.css` | the §11b palette as Tailwind v4 `@theme` tokens, the infeasible hatch, a reduced-motion guard |
| `frontend/src/lib/actions.ts` | **new**: the fixed action order, labels and the colour token per action |
| `frontend/src/lib/policy.ts` | **new**: reading values out of `GET /internal/policy` (the abuse meter's red band) |
| `frontend/src/lib/format.ts` | probabilities (`<0.1%`, `No model score`), probability points, timestamps, hash prefixes. Still never money |
| `frontend/src/api/client.ts` | typed calls for detail, policy, verify, override, appeal; 422 bodies rendered as field messages |
| `frontend/src/components/` | **new**: `ActionBadge`, `Panel`, `ScorePair`, `CostComparison`, `RelationshipGraph`, `ReasonList` (evidence + attribution), `AuditTimeline`, `BaselineComparison`, `OverrideDialog` (+ appeal), `AssumptionsPanel`, `ReviewerPicker`, `SyntheticDataBanner` |
| `frontend/src/pages/` | **new**: `OrderDetailPage.tsx`; `OverviewPage.tsx` and `QueuePage.tsx` moved out of `App.tsx` unchanged in content |
| `frontend/src/App.tsx` | routes to the page files; the banner moved to its own component |
| `frontend/src/__fixtures__/` | **new**: 8 payloads recorded from the real backend |
| `frontend/src/__tests__/` | **new**: `render.tsx` harness, `order-detail.test.tsx` (54), `no-hard-coding.test.ts` (51) |
| `frontend/src/test/setup.ts`, `vitest.config.ts` | **new**: jsdom viewport shims and the vitest config |
| `frontend/package.json`, `package-lock.json`, `tsconfig.*.json` | four exact-pinned test devDependencies, `test` / `test:watch`, `vitest/globals` types |
| `backend/sentinel/api/services/graph_view.py` | `HOP_RADIUS` 280 → 200, from the browser pass (the two-hop spike made the fitted graph too small) |
| `docs/reports/phase-8/*.png` | six screenshots |
| `docs/DEVIATIONS.md`, `docs/PROGRESS.md`, `README.md`, `docs/reports/phase-8.md` | #37 added, #16 updated; progress row; build status; this report |

No model artifact, policy value, generator code or `features.parquet` byte changed. `backend/data/sentinel.db`
was regenerated by `seed-db` (git-ignored).

## 2. Test results, build output

| Run | Result | Time |
|---|---|---|
| Baseline `-m "not slow"` (session start) | **547 passed** | 18.7 s |
| Part 1 gate, full suite incl. slow | **826 passed**, 1 skipped | 3 m 36 s |
| **Part 2 gate, full suite incl. slow** | **826 passed**, 1 skipped | 3 m 40 s |
| `npm test` (vitest) | **105 passed** (2 files) | 9.5 s |
| `npm run build` (`tsc -b && vite build`) | passes | 3.9 s |
| `seed-db` | 250 decisions plus graph capture | 6.2–7.1 s |

Build output: `dist/assets/index-*.js` **860.9 kB** (gzip **257.7 kB**), `index-*.css` **37.8 kB**
(gzip **7.5 kB**), `index.html` 0.42 kB — 896 kB on disk. Recharts and React Flow are most of the JS; Vite's
500 kB chunk warning is the only build warning and no code splitting was added, because the app is served from
the demo laptop over localhost.

The frontend suite is 105 tests: 54 on the page against the recorded payloads and 51 on the source scan
(one per file per check). The scan was verified to fail on a planted `const BLOCK_THRESHOLD = 0.70`, then
the plant was removed.

## 3. Screenshots

All six were taken by Playwright (installed globally in this environment, **not** added to `package.json`)
against `python -m sentinel.cli serve` and `npm run dev`, at **1440×900**, device scale 2, after scoring the
three presets through `POST /score-order`.

| File | What |
|---|---|
| `docs/reports/phase-8/demo-1.png` | Demo 1 — ALLOW, full page |
| `docs/reports/phase-8/demo-2.png` | Demo 2 — BLOCK, full page |
| `docs/reports/phase-8/demo-3.png` | Demo 3 — MANUAL_REVIEW, full page |
| `docs/reports/phase-8/override-dialog.png` | the override dialog on Demo 3, filled in |
| `docs/reports/phase-8/demo-3-after-override.png` | Demo 3 after the override to PREPAID_ONLY |
| `docs/reports/phase-8/assumptions.png` | the "Demonstration assumptions" panel, open |

**Horizontal overflow at 1280 is 0 px on all three demo pages** (measured as
`documentElement.scrollWidth − clientWidth` in the same run). The only console message in the whole pass is one
404 for `/favicon.ico`.

Three things the browser pass changed, and they are worth your eye:

1. **The infeasible bar was not hatched.** The `<defs>` holding the pattern was wrapped in a component, which
   Recharts drops. Inlining it in the chart fixed it; Demo 1's BLOCK bar and Demo 2's ALLOW bar are now clearly
   hatched `slate-600` with their guardrail chips beside them.
2. **The graph did not fit.** React Flow's `fitView` prop waits for measured handle bounds, which these nodes
   never produce (they declare their handles, see #37). The fit is now driven from the instance on mount, and
   the server's coordinates are treated as node centres. `HOP_RADIUS` also came down from 280 to 200 so the
   two-hop branch does not stretch the bounding box.
3. **The override dialog vanished on success.** The page refetched with its loading skeleton, unmounting the
   dialog that was showing the server's `warnings`. The refetch after an override is now silent. A test pins it.

## 4. What each demo page actually says

Read from the running page (`innerText`), not from the payload.

### Demo 1 — `ORD-DEMO-001`

| | Text |
|---|---|
| Decision card | **Allow** · Auto applied · Policy `v1.0` · Fingerprint `e1744f12` · Return model `return-hgb-fs1.0-e3c877bc` · Abuse model `abuse-hgb-fs1.0-446c817f` |
| Return card | **61.5%** — "Operational context — not used for action selection." Then the two RETURN reasons: "Multiple sizes of the same item in the cart." (+31.5 pp) and "The customer returned 28 of 48 delivered orders. This affects return likelihood, not abuse risk." (+18.7 pp) |
| Abuse card | **<0.1%** — "Without relationship evidence: <0.1% (counterfactual: relationship features set to typical values)" |
| Policy explanation | "ALLOW was selected because its expected cost (₹0) is lower than PREPAID_ONLY (₹750), MANUAL_REVIEW (₹912) and BLOCK (₹19,819) under policy v1.0. BLOCK was also not permitted: G2 requires two corroborating signals; none was found. G3 requires p_abuse of at least 0.70; this order scored 0.000." |
| Evidence | "No material abuse evidence was found; the score reflects this account's own history rather than links to other accounts." — **Mitigating factors**: MODERATE "Long-standing account with no flagged claims." (+0.0 pp, with the redundancy note); WEAK "Shared address discounted: household pattern." |

BLOCK is hatched with **G2** and **G3**; the RULE_BASED baseline strip reads **Block** — the §9.5 contrast, on
the same screen as a 61.5 % return rate in `sky-400`.

### Demo 2 — `ORD-DEMO-002`

| | Text |
|---|---|
| Decision card | **Block** · Auto applied · same versions |
| Return card | **37.8%** — same caption, no RETURN reasons fired |
| Abuse card | **95.1%** — "Without relationship evidence: 9.9% (counterfactual: relationship features set to typical values)", with the ghost marker on the same meter |
| Policy explanation | "BLOCK was selected because its expected cost (₹419) is lower than MANUAL_REVIEW (₹4,188), PREPAID_ONLY (₹8,118) and ALLOW (₹19,537) under policy v1.0. ALLOW was also not permitted: G5 removes ALLOW when p_abuse is at least 0.40 and the order value is at least ₹10,000." |
| Evidence | "The abuse score is driven mainly by links to other accounts sharing this order's device, payment method or delivery pattern." — STRONG "The payment method was used by 3 other accounts in the last 30 days." (+0.2 pp, redundancy note); STRONG "This device was used by 3 accounts later confirmed for return abuse, most recently 3 days ago." (+0.0 pp, redundancy note); MODERATE "Linked accounts placed 4 orders in the last 24 hours." (+4.5 pp); MODERATE "Linked accounts ordered the same item 3 times this week." (+3.8 pp); MODERATE "This device was used by 5 other accounts in the last 30 days." (+3.6 pp); WEAK "New account placing a high-value order." (+94.3 pp) |

The graph caption reads **"4 linked orders in the last 24 h · 3 confirmed accounts on this device · component
of 8"** and the picture now contains four linked order nodes and three red confirmed accounts — the count and
the drawing agree (1.1). The model-attribution panel lists the same six codes sorted by |Δ|, headed by
NEW_ACCOUNT_HIGH_VALUE at +94.3 pp: the two panels disagree about what matters, which is exactly #27's point.

### Demo 3 — `ORD-DEMO-003`, after the reviewer override

| | Text |
|---|---|
| Decision card | **Prepaid only** · **"System recommended: MANUAL_REVIEW"** · Overridden · same versions |
| Return card | **24.6%** — same caption |
| Abuse card | **69.1%** — amber, below the red band, "Without relationship evidence: <0.1% (counterfactual: relationship features set to typical values)" |
| Policy explanation | "MANUAL_REVIEW was selected because its expected cost (₹1,858) is lower than PREPAID_ONLY (₹3,171), BLOCK (₹4,052) and ALLOW (₹7,155) under policy v1.0. BLOCK was also not permitted: G3 requires p_abuse of at least 0.70; this order scored 0.691. ALLOW was also not permitted: G5 removes ALLOW when p_abuse is at least 0.40 and the order value is at least ₹10,000." |
| Evidence | "The abuse score is driven mainly by links to other accounts sharing this order's device, payment method or delivery pattern." — MODERATE "This device was used by 3 other accounts in the last 30 days." (+39.0 pp); MODERATE "The account had 1 flagged return or delivery claim in the last 6 months." (+0.0 pp, redundancy note) — **Mitigating factors**: WEAK "Shared address discounted: stale relationship." |

The audit timeline shows both events oldest first: `Decision created · System · MANUAL_REVIEW · f5a47505f7`,
then `Override applied · reviewer-placeholder-01 · MANUAL_REVIEW → PREPAID_ONLY · CUSTOMER_VERIFIED — "Customer
confirmed the prior claim was a courier error; prepaid with warehouse inspection." · 4642e17d77`, with **Chain
verified ✓** in teal. The graph draws the confirmed-abuse account reached through the address as a **dashed**
edge — the stale relationship, visibly not counted.

## 5. The two Part 1 items, measured

**1.1 — the graph agrees with the numbers.** Demo 2 draws **4 of 4** linked 24 h orders (was 3 of 4; the fourth
is placed by a ring member two account hops out) and **3 of 3** confirmed device peers, at 17 nodes and 18
edges, not truncated. Demo 1 draws 0 and 0 at 6 nodes, Demo 3 draws 1 and 0 at 9 nodes. Over the **250** seeded
decisions, recomputed from one chronological replay, every graph's drawn 24 h order nodes equal
`linked_orders_24h` and its confirmed-through-the-device accounts equal `device_confirmed_peer_count`; none is
truncated, so the `*_shown` fields equal the feature values everywhere in the current world.

The fix also covers a case the brief did not name: an account can be linked through an identifier the current
account used on an **earlier** order (a COD order has no token of its own and §6.3 falls back to the account's
prior tokens). Those accounts were previously left out of the graph while their orders were counted. The
graph can therefore show more than one DEVICE or PAYMENT_TOKEN node next to the current account; the order's
*own* device is identified by its id, not by adjacency, which is how the new tests find it.

**1.2 — the assumptions panel.** `GET /api/v1/internal/policy` returns all eight sections and 22 keys of
`policy_v1_0.toml` exactly as `load_policy_config()` produced them, with a server-formatted `Money` on each of
the 8 `*_inr` keys (`₹150`, `₹2,000`, `₹1,00,000`, `₹30`, `₹250`, `₹100`, `₹10,000`, `₹5,000`, `₹1`). A test
compares value by value against the loaded config; another asserts the guardrail key set. The panel is headed
by the notice and shows the full 64-character fingerprint.

## 6. Deviations added or updated

- **#35 added** (1.1): the two `GraphPayload` fields, the ego graph reaching counted accounts at any hop, the
  `features/` additions, the layout and cap rules, and the prior-identifier case. Closes Phase 7 open
  question 1 in favour of option (a).
- **#36 added** (1.2): `GET /internal/policy`, its three contracts and the new router file.
- **#34 updated** (1.3, 1.4): the two action counts stay as they are and the page labels each explicitly;
  probe logging stays limited to valid requests, with the reason.
- **#37 added** (Part 2): every frontend choice the brief leaves open — the test harness and its jsdom shims,
  the palette's two extra tokens and the AA measurement behind `--color-block-text`, reading the 70 % band
  from the policy endpoint, the page-per-route split, the graph's declared handles and self-driven fit, the
  scan's rules and its {0, 1, 2, 100} exclusion, the recorded fixtures, and the silent refetch after an override.
- **#16 updated**: the four test devDependencies at exact pins.

## 7. Open questions

1. **Graph legibility at the default zoom.** Demo 2's graph spans about 1,600 units and the panel is 580 px
   tall, so at the fitted zoom the masked node labels are small (readable on the 2× screenshot, tight on a
   projector). Zoom and fit controls are there, and the brief allows only those. If you want it bigger on stage
   I can raise the panel height, or drop the `RECENT_24H` badges from satellite order nodes, which are what
   force the extra ring of spacing. I changed neither on my own.
2. **`{0, 1, 2, 100}` are excluded from the no-hard-coding scan.** They are a loop bound, a border width and a
   percentage denominator, and they collide with `block_min_corroborating_signals = 2` and
   `genuine_support_cost_inr = 100`. Every other configured value is checked and the scan is verified to fail
   on a planted threshold. Say if you want those two checked some other way.
3. **The timestamp locale.** `formatTimestamp` uses the browser's timezone, so the screenshots taken in this
   UTC container read "1 Sept 2026, 4:55 am" where the demo laptop (IST) will read 10:25 am. That is correct
   behaviour, but it means the rehearsal machine's clock settings are load-bearing for what a judge sees.
4. **The two panels disagree on Demo 2 and that is the point.** Evidence leads with the two STRONG graph codes
   at +0.2 pp and +0.0 pp; Model attribution leads with NEW_ACCOUNT_HIGH_VALUE at +94.3 pp. Both are honest
   (#27), and the captions say so, but a judge will ask. It may be worth a sentence in the demo script.

## 8. Gate

Full backend suite green including slow (**826 passed, 1 skipped**), `npm run build` and `npm test`
(**105 passed**) all before the Part 2 commit. `seed-db` re-run. `git status -sb` and `git log --oneline -5`
immediately after the commit are recorded by the follow-up docs commit, never by amending.

`git status -sb` and `git log --oneline -5` immediately after the Part 2 commit:

```
## claude/phase-8-order-detail-jj8aik...origin/claude/phase-8-order-detail-jj8aik
```
```
556ae6a phase 8: order detail
fa43f4b phase 7: follow-ups
59daa4b docs: phase 8 brief and builder session rules
5824e2c docs: record the actual phase 7 commit hash in the report and progress log
d76f2c1 phase 7: api
```

*(This session works on `claude/phase-8-order-detail-jj8aik`, not `main`, as the operator instructed; the
builder header's "work on `main`" is superseded for this session only.)*

Stopping here. Phase 9 is not started.
