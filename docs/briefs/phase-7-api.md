# Phase 7 brief: Phase 6 follow-ups, then the API

*(The operator calls this "stage 6 fix and stage 7 build"; the operating manual calls it stage 8. Phase numbering here matches `docs/ARCHITECTURE.md` §12.)*

Issued by the Architect after reviewing `docs/reports/phase-6.md`.

Read before writing code: `docs/ARCHITECTURE.md` §2 (trust boundaries), §4 (contracts, including the customer-message table and HTTP errors), §11b (graph layout notes); `docs/DEVIATIONS.md` in full, especially #14, #27–#31.

Usage note: iterate with `pytest -m "not slow"`. Run the full suite only before each commit.

Two commits: Part 1 as `phase 6: follow-ups`, Part 2 as `phase 7: api`.

---

## Part 1 — Phase 6 follow-ups (decisions on your open questions)

**1.1 Graph evidence for seeded decisions (open question 1).** The 250 seeded decisions lack discounted links, and Phase 7 also needs a relationship graph for every decision, which the frozen as-of-`DEMO_CLOCK` builder cannot produce for historical orders without leaking later events.

Decision: capture both **at seed time**, point-in-time.
- During `seed-db`, replay the history chronologically once. At each seeded order's t0, capture:
  - its discounted links
  - its `GraphPayload` (defined in Part 2, section C)
- Store them in two new nullable columns on `decisions`: `discounted_links_json` and `graph_payload_json`. Add both to the `decisions_core_immutable` trigger.
- For live and demo orders, `ScoringService.score()` fills both from the frozen builder at scoring time.
- `features/` and `db/schema.sql` may change for this item only.
- Record as a deviation: schema addition and the reason.
- Test: a seeded hard-negative order (HOUSEHOLD or OFFICE_HOSTEL_PG, if one is among the 250) shows its discounted link. A seeded order's graph contains no node or edge first seen at or after its t0.

**1.2 Pre-history orders rejected (question 2).** Accepted as is. Scoring them would leak later events. Record the reason in #31 if not already there.

**1.3 Unknown accounts rejected (question 3).** Accepted for the prototype. The only live callers are the demo presets. Phase 7 maps the rejection to 404 with a neutral message. Record in #31.

**1.4 Reviewer clock (question 4).** A timeline that jumps from 2026-09-01 to the real date looks like a bug on stage. Reviewer actions (override, appeal) use a **demo reviewer clock**: `DEMO_CLOCK + (wall time elapsed since service start)`. It is monotonic, stays in the demo world, and preserves the real ordering and spacing of reviewer actions. Tests inject a fixed clock. Record as a deviation.

**1.5 Declare `threadpoolctl`.** `models/attribution.py` now imports it directly, so it must be a declared dependency, not an accident of scikit-learn's. Add `threadpoolctl==3.7.0` to `pyproject.toml` and confirm `requirements.lock` already pins that version. Record in #27 next to the latency fix.

Part 1 gate: full suite green, re-run `seed-db`, commit, push.

---

## Part 2 — Phase 7: API

Out of scope: any frontend code except the generated types file in section F; UI; model or policy changes.

### A. App shell (`api/main.py`)

- The lifespan constructs one `ScoringService` and one `ReviewService` at startup.
- If `backend/data/sentinel.db` is missing, fail fast with: *"Database not found. Run: python -m sentinel.cli seed-db"*.
- Routers:
  - internal under `/api/v1/internal`
  - public under `/api/v1/public`
  - `/health` stays unauthenticated
- **No CORS middleware** (the Vite proxy makes the UI same-origin).
- No `/predict` or any route that returns a model score without a decision.

### B. Internal routes (all require `X-Internal-Key`; `verify_internal_key` already returns 401 without echoing the header name)

| Route | Contract | Notes |
|---|---|---|
| `POST /score-order` | `ScoreOrderRequest` → `ScoreOrderResponse` | source `LIVE`; idempotent per order id |
| `GET /orders` | `QueueFilters` (query model) → `QueueResponse` | all filters and sorts in §4; `counts_by_action` over the filtered set |
| `GET /orders/{order_id}` | `OrderDetailResponse` | includes `GraphPayload`, both baselines, full audit history |
| `POST /orders/{order_id}/override` | `OverrideRequest` → `OverrideResponse` | reviewer from `X-Reviewer-Id` |
| `POST /orders/{order_id}/appeal` | `AppealRequest` → audit event | placeholder lifecycle |
| `GET /audit-events` | paged → `AuditEventsResponse` | `limit` ≤ 200, `offset`, optional `order_id` |
| `GET /audit-events/verify` | `AuditVerifyResponse` | |
| `GET /metrics` | `MetricsResponse` | see section D |
| `GET /demo/presets` | the three demo `ScoreOrderRequest`s | `DEMO_MODE` only, else 404 |
| `POST /demo/reset` | `{ "status": "reset", "decisions": 250 }` | `DEMO_MODE` only, else 404; calls `reset_demo()` and rebuilds the services |

Baselines on the detail page:
- FIXED_THRESHOLD uses the tuned τ pair recorded in `evaluation.json`.
- RULE_BASED uses the order's raw matured return counts and payment method.
- Both come from `policy/baselines.py`; nothing is re-implemented.

### C. `GraphPayload` builder (`api/services/graph_view.py`)

- **Ego graph:** the current account at the centre, its order, its identifiers (device, address, token), the other accounts linked through those identifiers, and linked orders from the last 24 h.
- **Cap:** at most 40 nodes. Priority: current → identifiers → confirmed-abuse accounts → by edge weight. Set `truncated` and `hidden_node_count` when capped.
- **Deterministic radial layout, computed server-side:** current account at the origin; identifiers on ring 1; linked accounts on ring 2; orders as satellites. Angular order sorted by `(kind, id)`. No randomness and no force layout. Same input, byte-identical output.
- **Edges** carry `reliability`, `decayed_weight`, `counted_as_evidence` and `discount_reason`. Discounted edges have `counted_as_evidence = false` and a reason; the UI draws them dashed.
- **Labels are masked** (`display_label`); no raw identifier or address ever appears. Node `state`: `CURRENT`, `CONFIRMED_ABUSE` (confirmed before t0 only), `LINKED`, `NEUTRAL`. Flags per §4.
- Point-in-time: built from the builder state as of t0. For seeded orders it is the stored `graph_payload_json` from Part 1.

### D. `GET /metrics`

- `activity` from the DB: counts, action distribution, friction, review volume, override rate, explanation coverage, version traceability (must be 1.0), weak-evidence decisions. `model_estimated_cost_avoided` = Σ EC(ALLOW) − EC(selected) over non-degraded decisions, labelled as an estimate.
- `backtest`, `models`, `cold_start_ring_recall`, `sensitivity` from `backend/artifacts/reports/evaluation.json`, unchanged.
- `drift_monitoring = "PLACEHOLDER_NOT_COMPUTED"` and `data_notice` exactly as §4.
- **Never** compute backtest numbers from the live queue: live decisions have no labels.

### E. Public route

`POST /api/v1/public/checkout/decision`: `CheckoutRequest` → `CheckoutOutcome`, via the same `ScoringService` in-process.
- Map actions exactly per the §4 customer-message table. **ALLOW and MANUAL_REVIEW return byte-identical bodies apart from `order_id` and `support_reference`.**
- `support_reference` is a neutral id (for example `SUP-` plus 8 hex characters derived from the decision id). It encodes nothing about the action.
- Errors (401 does not apply here; use 404, 409, 422): the body is a fixed generic message and **never echoes request fields**.
- **Probe logging:** every call inserts a `probe_events` row with `attempts_24h` and `distinct_carts_24h` for the device over the last 24 h of the reviewer clock. Log only; never block and never change the response.

### F. OpenAPI types for the frontend

- New CLI command `export-openapi` writes `frontend/src/api/openapi.json`.
- Add `openapi-typescript` as a frontend devDependency at an **exact pinned version** (approved new dependency; record in #16's list), plus the npm script `"gen:types": "openapi-typescript src/api/openapi.json -o src/api/types.ts"`.
- Regenerate `types.ts`, delete the hand-written types, and make `npm run build` pass.
- A test asserts the committed `openapi.json` equals a fresh export, so contract drift fails the build.

### G. Tests

- **Auth:** every internal route returns 401 without, or with a wrong, `X-Internal-Key` (parametrised over the route table); `/health` and the public route need no key.
- **No model endpoint:** the OpenAPI paths contain nothing matching `predict`, `score` outside `/internal/score-order`, or `model`.
- **Public safety:**
  - checkout body keys ⊆ `{order_id, outcome, customer_message, support_reference}`
  - no digits in `customer_message`
  - ALLOW vs MANUAL_REVIEW bodies identical after removing the two id fields
  - error bodies contain none of the request's field values
  - a probe row is written per call
- **Idempotency over HTTP:** same order twice → same `decision_id`; different payload under the same id → 409.
- **Override over HTTP:** stale `expected_current_action` → 409; missing or short reason → 422; BLOCK without corroboration and a wrong reason category → 422.
- **Unknown order** → 404 with a neutral message.
- **Detail:** for all three demos after scoring, and for 5 seeded orders:
  - `GraphPayload` ≤ 40 nodes
  - layout byte-identical across two calls
  - no raw identifier in any label
  - discounted edges have `counted_as_evidence = false` and a reason
  - no node first seen at or after t0
- **Queue:** each filter and sort; `counts_by_action` consistent with the filtered items.
- **Metrics:** `version_traceability == 1.0`; `data_notice` exact; backtest values equal `evaluation.json`; `activity` counts equal a direct DB count.
- **Demo endpoints:** 404 when `DEMO_MODE` is false; reset twice in a row succeeds on Windows; presets score to ALLOW / BLOCK / MANUAL_REVIEW.
- **Money:** every monetary field in every response has a `display` string from `format_inr`.
- **Latency:** `POST /score-order` p95 < 300 ms over 30 calls on fresh order ids (use the demo accounts with distinct order ids).
- **OpenAPI drift test** from F.

### H. Progress reporting (required)

At the start, after Part 1, after each Part 2 section A–G, and in the final report:

```
PROGRESS  phase 7 of 12  [######----]  7/11 stages to Definition of Done (64%)
          this phase: C. graph view — 4 of 9 sections done  |  elapsed 0h52m
```

Sections: Part 1, A, B, C, D, E, F, G, gate (9 total). Compute `elapsed` from real timestamps (`git log` or the shell clock), not estimates.

### I. Gate and report

- Full suite including slow, plus `npm run build` in `frontend/`, before the Part 2 commit. Push after each commit.
- Report to `docs/reports/phase-7.md`, and update `docs/PROGRESS.md` and the README build status.
- Report contents:
  1. files changed
  2. test results and timings, including `npm run build` and the score-order p95
  3. the route table as implemented, with status codes
  4. the full `OrderDetailResponse` JSON for Demo 2
  5. the `GraphPayload` for Demo 2, summarised (node and edge counts by kind, truncation, discounted edges)
  6. public checkout responses for all three demos, side by side
  7. `GET /metrics` JSON
  8. deviations added
  9. open questions
  10. `git status -sb` and `git log --oneline -5`
- Stop. Do not start Phase 8.
