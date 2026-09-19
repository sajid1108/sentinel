# Phase 10 brief: "Try an order", a live checkout simulator

*(After the Definition of Done. The product is now branded **AegisShift** in everything a user sees; the code package, CLI and repo stay `sentinel`.)*

Issued by the Architect after Phase 9 was merged (`6cd8350`).

**Goal:** turn the demo from "watch three presets" into "try it yourself". A judge builds an order, submits it, and immediately sees two things:
- what the **customer** is told (outcome only)
- what the **reviewer** sees (the full decision page)

The backend already scores arbitrary orders. This phase exposes that safely.

Read before writing code (exclusive list, per `BUILDER_HEADER.md`):
- `docs/ARCHITECTURE.md` §4 (`ScoreOrderRequest`, `CheckoutOutcome` and the customer-message table), §7.2 (P12, P14), §13.5, §14.3
- `docs/DEVIATIONS.md` #22, #30, #31, #34, #41
- `docs/reports/phase-9.md` §7
- `DESIGN.md` §2, §4 and §7

Iterate with `pytest -m "not slow"` and `npm test`. Run the full suite once before each commit.

Two commits: `phase 10: demo source` (Part 1) and `phase 10: try an order` (Part 2).

---

## Part 1: demo presets are recorded as DEMO

`POST /internal/score-order` always records `source = "LIVE"`, so the three presets show "Live" in the queue. The schema already has `DEMO` for exactly this case.

- Add `POST /internal/demo/presets/{order_id}/score` (`DEMO_MODE` only; 404 otherwise). It finds the preset by its `order_id` in `demo_presets.json`, scores it with source `DEMO`, and returns `ScoreOrderResponse`. An unknown preset returns 404 `"Not found."`.
- The Queue's Simulate checkout buttons call this route instead of posting the preset body.
- A preset already scored returns its recorded decision (idempotent replay), as today.
- Tests:
  - the three presets record `DEMO`
  - `POST /score-order` still records `LIVE`
  - the route returns 404 with `DEMO_MODE` off
  - it returns 404 for an unknown preset
  - it requires the internal key
- Regenerate `openapi.json` and `types.ts`. Record the change in a deviation (≤ 150 words).

## Part 2: "Try an order"

### A. Backend: `GET /internal/demo/order-builder` (`DEMO_MODE` only)

This route returns everything the form needs, so that nothing is typed free-hand and nothing is hard-coded in the frontend.

- `placed_at`: the presets' own `placed_at`. It is already valid: after the frozen history and before `DEMO_CLOCK` (#31).
- `accounts`: a short, **data-derived** list. Each entry has `account_id`, a label, `account_age_days`, `prior_orders`, and the account's own most recent `device_id`, `address_id` and `payment_token_id` (hashed ids only). The list contains:
  1. every preset's account (the three demo accounts)
  2. up to three seeded accounts whose stored decision has a `HOUSEHOLD_PATTERN` or `MULTI_TENANT_ADDRESS` discounted link (read from `discounted_links_json`), labelled from that reason ("Shares a household address", "Lives at a multi-tenant address")
  3. up to two accounts with no prior orders at `placed_at`, if any exist

  **Never read `sim_ground_truth` or `order_labels`.** The import-boundary test must stay green. Never special-case an id: the list is built from the presets file and the stored decisions.
- `devices`: the options for the device field, each with a label and a hashed `device_id`:
  - "The account's own device" (resolved per account in the frontend)
  - "A brand-new device": a fresh HMAC id per request, made with `features/identifiers.py` from a random value, never a placeholder
  - "A device shared with the ring": the `device_id` of the preset whose recorded decision has the highest `device_confirmed_abuse_weight`. This is data-driven; do not name Demo 2.
- `tokens`: the same three options for the payment token (own, new, "the ring's card", chosen by the same rule on the token signal).
- `categories`: the six §4 categories.
- Tests:
  - auth
  - 404 with `DEMO_MODE` off
  - no field outside the 32-hex pattern where an identifier is expected
  - the ring options equal the identifiers of the preset with the strongest recorded device and token evidence
  - no import of generator or ground-truth modules

### B. Frontend: a "Try an order" panel on the Queue page

Put it beside Simulate checkout. Scope stays at three routes (§14.3).

**The form, every control a real `<label>`:**
- account (select)
- category (select)
- item price in ₹ (number, 1–5,00,000)
- quantity (1–20)
- sizes of the same item (1–4). This creates that many lines of one product, which is size bracketing.
- discount % (0–90)
- delivery speed (Standard / Express)
- payment method (UPI / card / COD)
- device (own / new / the ring's)
- payment token (own / new / the ring's; hidden and null for COD)

**Submit ("Place order"):**
- Build a `ScoreOrderRequest` with a fresh `order_id` `ORD-TRY-<8 random upper-case hex>`, `placed_at` from the builder route, and SKU/product ids `SKU-TRY-<CATEGORY>-<n>` / `PRD-TRY-<CATEGORY>`.
- Send it **once** to the public `POST /api/v1/public/checkout/decision`. That call scores the order (source `LIVE`) and returns the customer outcome.
- Then fetch `GET /internal/orders/{order_id}` for the reviewer view. **Don't call score-order a second time**: the checkout call already wrote the decision.

**Output, shown inline under the form:**
1. **Customer view:** a card styled like a checkout message showing `customer_message` and `support_reference` verbatim, and nothing else. No score, action name, reason, cost or colour that reveals the action. Caption: "What the shopper sees."
2. **Reviewer view:** the action badge, both probabilities (separate), the policy explanation verbatim, and an "Open full decision" link to `/orders/{order_id}`. Caption: "What your team sees."

**States:**
- The submit button reads "Placing order…" while the request runs.
- On a 422, show the server's field messages beside the fields.
- On a 404 (unknown account), show "This account doesn't exist in the demo world."
- Other errors show a message with a Retry button.

**Rules:**
- Money is never formatted from the typed input. Show the order value only from the server's `order_value.display` on the result.
- Nothing is hard-coded: no thresholds, no ids, no policy values.

### C. Measure the headline moment (report it; don't force it)

Through the real API, score these orders in order:
1. Demo 1's account with its own device and its own token, with the preset's cart (expect ALLOW)
2. the same cart with **the ring's device**
3. the same cart with the ring's device **and** the ring's card

For each, report `p_abuse`, the selected action, the counted signals and the guardrails. **If the stance does not shift, report the numbers and stop. Never tune anything to make it shift.** This is the demo talking point, and it must be true.

### D. Tests

- **Frontend:**
  - the form builds a request that validates against the generated type
  - COD nulls the token
  - the customer card renders only the three `CheckoutOutcome` strings (a scan finds no `%` and no action name)
  - the reviewer card shows two separate probabilities
  - "Placing order…" disables the button
  - 422 field errors render
  - the no-hard-coding scan covers the new files
- **Backend:** the tests in A and Part 1, plus one scenario test that the Part C orders score without error and each writes a verified audit event. Assert on **validity and the audit chain, not on a particular action.**

### E. Visual check (if a browser tool is available)

Save these to `docs/reports/phase-10/`:
- `try-form.png`
- `try-result-allow.png`
- `try-result-shifted.png` (the Part C order that shifts, if one does)

Measure horizontal overflow at 1280.

### F. Progress line

```
PROGRESS  phase 10 (try an order)  [#####-----]  C. measure — 3 of 6 sections done  |  elapsed 0h52m
```

Sections: Part 1, A, B, C, D+E, gate.

### G. Gate and report

- Full backend suite (slow included), `npm test` and `npm run build` before each commit. Push after each.
- Write `docs/reports/phase-10.md`:
  1. files changed
  2. test results
  3. screenshots
  4. **the Part C table**
  5. deviations
  6. open questions
  7. `git status -sb` and `git log --oneline -5`
- Update `docs/PROGRESS.md` and the README build status. Stop.
