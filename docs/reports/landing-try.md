# Landing page "Try an order" (recorded grid): report

*Brief: `docs/briefs/landing-try-an-order.md`. No backend or app code changed.*

```
PROGRESS  landing try  [##########]  ship — 4 of 4 steps done  |  elapsed 0h38m
```

| Checkpoint | Steps done | Elapsed |
|---|---|---|
| grid defined, script written | 1 of 4 | 0h04m |
| recorded (second run) | 2 of 4 | 0h12m |
| section built, browser pass | 3 of 4 | 0h14m |
| gate green, commit | 4 of 4 | 0h38m |

Elapsed is wall clock from the session's first command (11:22:56 IST).

## 1. The grid

Axes that come from `GET /internal/demo/order-builder` on a freshly seeded database: **6 accounts**
(ACC-DEMO-001/002/003 and three discounted-link accounts; the builder found no account without orders),
**3 devices** and **3 tokens** (OWN, NEW, RING). Categories: the builder's **6**. Payment methods: the
**3** in the `ScoreOrderRequest` enum in `openapi.json`.

I reduced the Phase 10 form's free inputs this way. Every combination uses the first preset's cart (ORD-DEMO-001), built
the way `tryOrder.ts` `buildRequest` builds it (`SKU-TRY-{category}-{n}`, one line per size):

| Form input | Grid value |
|---|---|
| sizes of the same item | 3 (the preset's line count) |
| quantity | 1 |
| discount | 10 % |
| delivery | STANDARD |
| item price | **2 value bands**: the lowest and highest preset order values, ₹4,500 (unit ₹1,666.67) and ₹24,000 (unit ₹8,888.89) |
| category | all 6 |
| payment method | all 3 |

**Exclusions:** COD carries no token, so a COD combination has token `-`. ACC-DEMO-002 has no device or token of
its own (5 days old, no orders), and the Phase 10 form disables OWN for it, so its OWN combinations are not
in the grid. On the site those options are disabled. The first run did not exclude them, stopped on the
first such combination and wrote nothing; the script was fixed and run again.

**Count:** 5 accounts × 12 carts × 3 devices × (3 + 3 + 1) = 1,260, plus ACC-DEMO-002's 12 × 2 × (2 + 2 + 1) = 120,
for **1,380 combinations**. The default is `ACC-DEMO-001|APPAREL|0|PREPAID_UPI|OWN|OWN`, Demo 1's own
order. The script refuses to run if that cart is not in the grid.

A NEW device or token is a fresh HMAC id from a fresh builder call for each combination.

## 2. Recording

`scripts/record_try_grid.py` seeds a fresh database in a temporary folder and serves it with `create_app`
over local HTTP. For each combination it calls `POST /public/checkout/decision` once, then
`GET /internal/orders/{id}`, with no second scoring call. It asserts that no decision is degraded or replayed and
that model, feature-set and policy versions are constant across the run, and deletes the folder at the end.
The run took 158 s.

**The real `backend/data/sentinel.db` is untouched:** its SHA-256 (`96c268b0…`) is the same before and after.

**File:** `landing/try-grid.json`, **648,039 bytes** (limit 3 MB), so no field was dropped. Per combination it stores the
outcome, the shopper message, the current action, the cost-optimal action, p_abuse, p_return, p_abuse without
graph evidence, the counted signals, the four expected costs (server `display` strings plus `excluded_by`),
the top 4 reasons (code and reviewer text) and the policy explanation. Repeated texts go through a string table.
Metadata: `recorded_at` 2026-09-19T06:02:28Z, `git_sha` `9ec72e6` with `git_dirty: true` (the script was
not yet committed when it ran, and the site says so), and the model, feature-set and policy versions.

**Order independence: 20 of 20 re-scored combinations match exactly.** The script picks 20 random combinations,
places them again with new order ids (and new NEW ids), and compares every recorded value with the first pass.
The one thing masked is the shopper's support reference: it is a digest of the decision id, which is new for
every order by design. It appears only inside the BLOCK message. The 20 keys are in the file under
`order_check`.

**Cross-check against Phase 10 Part C** (same account, cart value and identifiers, different SKU ids):
identical to the last digit. The default gives p_abuse 0.0000441 (ALLOW); with another account's device,
0.01856 (ALLOW, 2 signals); with its device and token, 0.05555 (ALLOW, 3 signals, costs ₹221 / ₹802 / ₹919 / ₹18,719).

## 3. Outcomes

| Action | Combinations | Shopper outcome |
|---|---|---|
| ALLOW | 836 | CONFIRMED |
| MANUAL_REVIEW | 290 | CONFIRMED |
| BLOCK | 204 | UNABLE_TO_PROCESS |
| PREPAID_ONLY | 50 | PREPAID_PAYMENT_REQUIRED |

Every BLOCK is in the ₹24,000 band (band 0 has none), and 180 of the 204 use another account's device. The
site shows combinations only as the user picks them. Nothing is ordered, filtered or featured to make BLOCK look
common.

## 4. The landing section

This is a new `#try` view ("Try an order" in the nav), built with plain JS and no libraries. The selects are filled from
`try-grid.json`, and an option with no recorded answer is disabled. Above the form, word for word: "Answers are recorded
from the real model and policy, not computed live. Every combination here was scored ahead of time." The
§1 item 18 synthetic-data notice is on the section. The result shows "What the shopper sees" (the message only)
next to "What the reviewer sees": the action, the order value, the two probabilities in separate cards, the
counted signals, the expected cost per action with removed actions hatched and chipped, the explanation and the top reasons.
Money comes only from the recorded `display` strings, and red appears only on BLOCK.

The device and token labels use the Phase 11 wording ("Another account's device (strongest evidence)",
"Another account's token (strongest evidence)"), and no option label says "ring". A button
selects "Demo 1 with another account's device and token". It shows the recorded ALLOW with the brief's sentence.
That sentence appears only for Demo 1's cart with both shared identifiers **and** a recorded ALLOW. The tree
follows the shown p_abuse through the page's existing `pToRisk`.

## 5. Browser pass

Microsoft Edge through `playwright-core` (already in `frontend/node_modules`; nothing installed), against
`python -m http.server` on `landing/`, device scale 2.

| Width | Horizontal overflow (try, default / shared) | Home overflow | Max video drift (try + home) |
|---|---|---|---|
| 375 | 0 / 0 px | 0 px | 0.027 s |
| 1280 | 0 / 0 px | 0 px | 0.017 s |
| 1440 | 0 / 0 px | 0 px | 0.039 s |

At 375, every other view (stance, demo, results, disclosures) also has a 0 px page overflow. The results table
scrolls inside its own container, as before. No layer video was paused while the master played. The one
console error is `/favicon.ico` 404, as in Phase 9 and 10.

Screenshots in `docs/reports/landing-try/`: `try-default-{375,1280,1440}.png` (Demo 1's own order) and
`try-shared-{375,1280,1440}.png` (another account's device and token: ALLOW, with the sentence).

## 6. Changes beyond the new section

All of them came out of the 375 px check. I found them on the page as it was already published:

- **`<meta charset="utf-8">`**: there was none. Pages served without a charset showed "·" as "Â·".
- **`<meta name="viewport" …>`**: there was none, so phones laid the page out at the 980 px default and
  shrank it. With it, the page renders at device width. This is the change most likely to affect how the site looks
  on a phone, and it is why the next two were needed.
- **The nav button** overflowed by 10 px at 375 on the live site. Under 560 px the nav gap and the button
  padding are smaller.
- **`.cbar` wraps**: guardrail chips in the Demos panel's cost rows overflowed by 36 px at 375, and in the new
  section by 18 px.
- `landing/README.md`: one line about the section.

**Site repo:** `sajid1108/aegisshift` gets `index.html` and `try-grid.json`. Its `index.html` matched
`landing/index.html` apart from CRLF line endings, and the videos matched byte for byte. Its own `README.md`
(the project overview) differs from `landing/README.md` and was left as it is.

## 7. Gate and ship

| Run | Result |
|---|---|
| Full backend suite, first attempt (`-x`) | stopped at `test_seeding_finishes_within_budget` (budget 30 s): the recording, Edge and the suite were running together, and the whole run took 14 min instead of ~6.5. The test passed alone (1 passed); the bound was not changed |
| Full backend suite, gate (slow included) | **874 passed** (6 m 30 s) |
| `npm test` / `npm run build` | not run: `frontend/` is unchanged |

Commits: `landing: try an order (recorded grid)` on `sentinel` `main`; `landing/index.html` and `landing/try-grid.json`
copied to `sajid1108/aegisshift` `main` and pushed. The live check is recorded in §8.
