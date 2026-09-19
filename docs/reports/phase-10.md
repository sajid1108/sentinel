# Phase 10 — "Try an order": gate report

*Brief: `docs/briefs/phase-10-try-an-order.md` (Part 1 = presets recorded as DEMO, Part 2 = "Try an order").*

```
PROGRESS  phase 10 (try an order)  [##########]  gate — 6 of 6 sections done  |  elapsed 1h00m
```

Elapsed is wall clock from the session's first command (10:11:14 IST) to the Part 2 commit.

| Commit | What |
|---|---|
| `b588d1a` | `phase 10: demo source` (Part 1) |
| Part 2 commit | `phase 10: try an order` (Part 2) |

| Checkpoint | Sections done | Elapsed |
|---|---|---|
| Part 1 tests green | 1 of 6 | 0h27m |
| Part 1 committed (`b588d1a`) | 1 of 6 | 0h35m |
| A. builder route | 2 of 6 | 0h41m |
| B + C. panel, measurement | 4 of 6 | 0h42m |
| D + E. tests, browser pass | 5 of 6 | 0h52m |
| gate | 6 of 6 | **1h00m** |

**Headline: the stance does not shift** (§4). Demo 1's cart on Demo 1's account stays **ALLOW** with the ring's
device and with the ring's device *and* card. The evidence does register (0 → 2 → 3 counted signals, G2 stops
firing, p_abuse 0.004 % → 1.9 % → 5.6 %), but ALLOW stays the cheapest action. Nothing was tuned, and
`try-result-shifted.png` is therefore absent. See open question 1.

**Escalated and settled before any code** (header rule): the brief says "On a 422, show the server's field
messages beside the fields", but the form posts to the public checkout, whose 422 is the fixed sentence "The request
could not be processed." with no field locations (#34). The user chose to **keep #34**. The form checks each field
against the bounds in the generated `openapi.json` before anything is sent and shows those messages beside the
fields. If the server still refuses, its fixed sentence appears beside the button (#44).

Also noted: while this session ran, the architect session committed `768a7a8` (`docs/ARCHITECT_HANDOFF.md` only) to
local `main`. Part 1 sits on top of it, and nothing was rebased.

---

## 1. Files changed

**Part 1 — `b588d1a` (`phase 10: demo source`)**

| File | Change |
|---|---|
| `backend/sentinel/api/routers/demo.py` | `POST /demo/presets/{order_id}/score`: finds the preset in `demo_presets.json`, scores it with source `DEMO`, 404 "Not found." for an unknown preset or with DEMO_MODE off; `load_presets` shared with `GET /demo/presets` |
| `backend/tests/api/test_api.py` | the shared fixture scores the presets through the new route (as the Queue does); new route added to the auth table and the DEMO_MODE-off test; 4 new tests (presets record DEMO, the route scores and replays, `/score-order` still records LIVE, unknown preset 404); the no-model-endpoint test now allows exactly the two scoring paths and asserts both return the whole `ScoreOrderResponse` |
| `frontend/src/api/client.ts` | `postScorePreset(orderId)` replaces `postScoreOrder(preset)`: no body is sent |
| `frontend/src/components/SimulateCheckout.tsx` | the buttons call the new route |
| `frontend/src/__tests__/queue.test.tsx`, `render.tsx` | the stub answers the new route; the click test asserts the route, `POST`, no body, and no call to `/score-order` |
| `frontend/src/api/openapi.json`, `types.ts` | regenerated |
| `docs/DEVIATIONS.md` | #43 |

**Part 2 — Part 2 commit (`phase 10: try an order`)**

| File | Change |
|---|---|
| `backend/sentinel/api/schemas.py` | `BuilderAccount`, `BuilderIdentifierOption`, `OrderBuilderResponse` |
| `backend/sentinel/api/services/order_builder.py` | new: the builder's accounts, identifier options and ring rule (§A) |
| `backend/sentinel/api/routers/demo.py` | `GET /demo/order-builder` (DEMO_MODE only, under the scoring lock) |
| `backend/tests/api/test_try_an_order.py` | new, 7 tests (§A and the §D scenario) |
| `backend/tests/api/test_api.py` | the builder route is in the auth table and the DEMO_MODE-off test |
| `frontend/src/lib/tryOrder.ts` | new: form state, bounds from `openapi.json`, `validate`, `buildRequest`, `newOrderId` |
| `frontend/src/components/TryAnOrder.tsx` | new: the form, the two result cards, the states |
| `frontend/src/pages/QueuePage.tsx` | the two demo panels side by side (1 : 2 at `xl`) |
| `frontend/src/api/client.ts` | `getOrderBuilder`, `postCheckout` |
| `frontend/src/index.css` | `--color-error` (rose-300) |
| `frontend/src/__tests__/try-order.test.tsx` | new, 16 tests |
| `frontend/src/__tests__/no-hard-coding.test.ts` | asserts the scan covers the two new source files |
| `frontend/src/__fixtures__/order-builder.json`, `checkout-outcome.json`, `try-detail.json` | recorded from the real backend |
| `frontend/src/api/openapi.json`, `types.ts` | regenerated |
| `docs/DEVIATIONS.md` | #44 |
| `docs/reports/phase-10.md`, `docs/reports/phase-10/*.png`, `docs/PROGRESS.md`, `README.md` | report, screenshots, status |

## 2. Test results

| Run | Result |
|---|---|
| Baseline, `pytest -m "not slow"` | 577 passed |
| Part 1 gate: full backend suite (slow included) | 865 passed (6 m 26 s) |
| Part 1 gate: `npm test` / `npm run build` | 164 passed / built |
| Part 2 gate: full backend suite (slow included) | 874 passed (7 m 24 s) |
| Part 2 gate: `npm test` / `npm run build` | 186 passed / built |

`npm run build` prints the existing warning that one chunk is over 500 kB; it was already there.

What the new tests hold:

- **Backend (§A):**
  - the builder offers the presets' `placed_at`, the preset accounts first, and the six categories
  - discounted-link accounts carry a reason from their own stored decisions
  - every account's own identifiers equal its latest HISTORY order before `placed_at`
  - every identifier is 32-hex or null, and only the OWN option is null
  - NEW ids change on every request
  - the ring options equal the device and token of the preset with the strongest *recorded* evidence (read from `decisions` after the presets are scored)
  - a fresh interpreter importing the builder and the demo router loads no generator, archetype, label or evaluation module
- **Backend (§D scenario):** the three Part C orders go through the public checkout; each returns the four-key body, is recorded as LIVE, not degraded and not replayed, and has exactly one `DECISION_CREATED` event; the audit chain verifies. **No assertion is made on the action.**
- **Frontend:**
  - for every payment method × device × token choice, the request passes a JSON-schema check against the generated `ScoreOrderRequest`
  - COD nulls the token and hides the field
  - the shopper card's text nodes are only `customer_message` and `support_reference`, with no `%`, no action name and no `data-action`
  - the team card's two probabilities are separate elements
  - "Placing order…" disables the button, and a second click sends nothing
  - field messages are tied to their inputs by `aria-describedby`, and nothing is sent
  - a 422 shows the server's sentence, and a 404 shows the unknown-account message
  - Retry resends the same body
  - exactly one checkout call and no scoring call are made
  - money is never shown from the typed price

## 3. Screenshots

Chromium via `playwright-core` (installed with `--no-save`, as in #41; `package.json` and the lockfile are
unchanged) against `python -m sentinel.cli serve` and `npm run dev`, at **1280×900**, device scale 2, on a
freshly reset database.

| File | What |
|---|---|
| `docs/reports/phase-10/try-form.png` | the panel before an order |
| `docs/reports/phase-10/try-result-allow.png` | Part C order 1 through the form: "Your order is confirmed." / ALLOW, <0.1 % |
| `docs/reports/phase-10/try-result-ring.png` | Part C order 3 through the form (the ring's device and card): still ALLOW, 5.6 % |
| `try-result-shifted.png` | **not produced: no Part C order shifts** |

**Horizontal overflow at 1280 is 0 px** on the Queue with the form, on the Queue with a result, and on the
tried order's detail page (`scrollWidth − clientWidth`).

Checked in the same run:
- **One checkout, no second score.** Placing an order issued exactly `POST /public/checkout/decision`, then `GET /internal/orders/{id}`, then the queue reload.
- **Button state.** "Placing order…" was visible while the request ran; each order took about 0.2–0.26 s.
- **Field messages.** An empty price and a 95 % discount gave "Required." and "Must be at least 0 and at most 90.".
- **Console.** One 404 console error with no matching page-level response. It is consistent with the browser's own `/favicon.ico` request, as in Phase 9.

## 4. The Part C table

Through the real API over HTTP (`sentinel.cli serve`, a freshly reset database). Demo 1's own cart and
account, placed at the builder's `placed_at`; only the device and the token change.

| # | Order | p_abuse | p_abuse without graph | Counted signals | Triggered guardrails | Cost-optimal → selected | Expected cost ALLOW / PREPAID / REVIEW / BLOCK | Shopper sees |
|---|---|---|---|---|---|---|---|---|
| 1 | own device, own token | 0.0000441 (<0.1 %) | 0.0000441 | none (0) | G2, G3 remove BLOCK | ALLOW → **ALLOW** | ₹0 / ₹750 / ₹912 / ₹19,819 | "Your order is confirmed." |
| 2 | **ring's device**, own token | 0.01856 (1.9 %) | 0.0000555 | DEVICE, TEMPORAL_BURST (2) | G3 removes BLOCK | ALLOW → **ALLOW** | ₹74 / ₹768 / ₹915 / ₹19,452 | "Your order is confirmed." |
| 3 | **ring's device and card** | 0.05555 (5.6 %) | 0.0000555 | DEVICE, PAYMENT_TOKEN, TEMPORAL_BURST (3) | G3 removes BLOCK | ALLOW → **ALLOW** | ₹221 / ₹802 / ₹919 / ₹18,719 | "Your order is confirmed." |

Order value ₹4,500 each; p_return 61.5 % each; every decision `MIN_EXPECTED_COST`, `AUTO_APPLIED`; the audit chain
verified after the three orders (`valid: true`). The ring identifiers came from the builder: the device of the
preset with the highest `device_confirmed_abuse_weight` and the token of the preset with the strongest
PAYMENT_TOKEN signal (both Demo 2's).

**Reading.** The graph evidence is doing exactly what it should: the counterfactual without graph evidence stays at
0.006 %, so the whole rise to 5.6 % is relationship evidence; the counted signals reach three, so G2 would now permit
BLOCK; and ALLOW's expected cost rises from ₹0 to ₹221. But the abuse model scores a 3.5-year, 52-order genuine
account at 5.6 % even on a ring device and card, and at that probability ALLOW (₹221) is still far cheaper than
PREPAID_ONLY (₹802). The talking point that is true is **"the evidence registers and is shown to the team; one
trusted account's single order on a shared device is not enough to add friction"**, not "the stance flips".

## 5. Deviations

- **#43 (Part 1):** presets are scored as DEMO through their own route, and the no-model-endpoint test allows exactly the two decision-returning scoring paths.
- **#44 (Part 2):**
  - the builder route and its contracts
  - the ring identifiers are computed from each preset with the recording code (a preset has no decision until it is scored), and a test compares them with the recorded rows
  - the token rule
  - accounts with no order get a fresh address and no own device or token
  - the public 422 stays generic, with bounds-driven field checks in the form (the user's decision)
  - `--color-error`

Choices inside the brief, not deviations:
- **Token option labels.** OWN and NEW read "The account's own token" and "A brand-new token", because UPI is not a card. They also fit the column at 1280. RING keeps the brief's "The ring's card".
- **Retry.** Retry resends the same order id, which the server replays idempotently, or, if the checkout already answered, only re-reads the decision.
- **The "no prior orders" group** is empty in the demo world. The only account with no order before `placed_at` is Demo 2's, which is already listed as a preset account.

## 6. Open questions

1. **The headline moment does not happen with Demo 1's account** (§4). If the demo needs a visible shift, the
   honest levers are *which account and cart* a judge tries, not the model or the policy. For example, the
   builder's discounted-link accounts or a new account on the ring's device are untested here, and I did not
   go looking for a combination that flips, because the brief says to report and stop. A decision for the
   Architect: is "evidence registers, stance holds for a trusted account" the talking point, or should a
   later brief measure a defined set of combinations?
2. **An intermittent Windows lock on `POST /demo/reset`.** On one server instance, reset failed twice with
   `WinError 32`. Restart Manager showed that the server process itself held `backend/data/sentinel.db`, so
   some connection outside the pool survived `engine.dispose()`. I could not reproduce it:
   - on three further instances, with builder → reset, reset → reset and score → reset
   - in-process against a copy
   - in the existing `test_reset_twice_in_a_row`

   The builder route opens connections only through `read_connection`, and its first real-server call was
   followed by a successful reset on two instances, so I have no evidence that this phase caused it. It is
   recorded for the hardening stage rather than chased here.
3. **Ring labels are claims.** "A device shared with the ring" / "The ring's card" are the brief's labels for "the
   preset with the strongest evidence". In this world that is Demo 2 (a ring recruit), but the route would attach
   the same label to whichever preset scored highest. A neutral label ("A device linked to confirmed abuse")
   would stay true for any presets file.

## 7. Git

As of just before the Part 2 commit, which sits on top of this log (a report cannot quote its own hash):

```
$ git status -sb
## main...origin/main
 M README.md
 M backend/sentinel/api/routers/demo.py
 M backend/sentinel/api/schemas.py
 M backend/tests/api/test_api.py
 M docs/DEVIATIONS.md
 M docs/PROGRESS.md
 M frontend/src/__tests__/no-hard-coding.test.ts
 M frontend/src/api/client.ts
 M frontend/src/api/openapi.json
 M frontend/src/api/types.ts
 M frontend/src/index.css
 M frontend/src/pages/QueuePage.tsx
?? backend/sentinel/api/services/order_builder.py
?? backend/tests/api/test_try_an_order.py
?? docs/reports/phase-10.md
?? docs/reports/phase-10/
?? frontend/src/__fixtures__/checkout-outcome.json
?? frontend/src/__fixtures__/order-builder.json
?? frontend/src/__fixtures__/try-detail.json
?? frontend/src/__tests__/try-order.test.tsx
?? frontend/src/components/TryAnOrder.tsx
?? frontend/src/lib/tryOrder.ts

$ git log --oneline -5
b588d1a phase 10: demo source
768a7a8 docs: handoff update (brand, live landing page, phase 10 brief, deploy plan)
318db3c docs: phase 10 brief (try an order: live checkout simulator)
cbf1121 landing: AegisShift site with the world-tree videos
4b3dbfa brand: rename the product to AegisShift (display names only; code package stays sentinel)
```
