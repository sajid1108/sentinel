# Phase 7 — API: gate report

*Spec phase 7 (`docs/ARCHITECTURE.md` §12); `october_master_architecture.md` calls it stage 8. Brief:
`docs/briefs/phase-7-api.md` (Part 1 = Phase 6 follow-ups, Part 2 = Phase 7).*

```
PROGRESS  phase 7 of 12  [#######---]  8/11 stages to Definition of Done (73%)
          this phase: gate — 9 of 9 sections done  |  elapsed 2h13m
```

Elapsed is wall clock from the session's first command (08:52:31 IST) to the gate (11:05 IST). It includes an idle
gap of about 1h30m between Part 1 landing (09:07) and the session resuming (10:37). Active build time is about 45 min.

Both commits are green on the full suite (slow included) and pushed. Phase 8 is not started.

| Commit | What |
|---|---|
| `3dfbf20` | `phase 6: follow-ups` (Part 1) |
| `d76f2c1` | `phase 7: api` (Part 2) |

Progress lines printed during the session (elapsed from `date` at each checkpoint):

| Checkpoint | Sections done | Elapsed |
|---|---|---|
| start | 0 of 9 | 0h01m |
| Part 1 committed (`3dfbf20`) | 1 of 9 | 0h15m |
| A + B (shell, internal routes working end to end) | 3 of 9 | 1h45m (includes the idle gap) |
| C, D, E, F (graph view served, metrics, checkout + probe, OpenAPI types) | 7 of 9 | 1h49m |
| G (API tests, 67) | 8 of 9 | ~2h00m |
| gate | 9 of 9 | 2h13m |

C was built in Part 1 because the seed-time capture needs it. D and E were code-complete before F, so their
checkpoint lines were folded into F's.

---

## 1. Files changed

**Part 1 — `3dfbf20` (`phase 6: follow-ups`)**

| File | Change |
|---|---|
| `backend/sentinel/db/schema.sql`, `db/models.py` | `decisions.discounted_links_json`, `graph_payload_json` (nullable), both in `decisions_core_immutable` (1.1) |
| `backend/sentinel/features/graph_features.py` | `EgoView`, `IdentifierView`, `ego_view()`: the query order's identifiers, other accounts' visible use of them, their orders in the last 24 h, the reliable component (1.1) |
| `backend/sentinel/features/builder.py` | `iter_points_in_time()` (one replay, paused at each wanted order's t0), `discounted_links_at()`, `ego_view()` (1.1) |
| `backend/sentinel/api/services/graph_view.py` | **new**: `GraphPayload` builder with ego graph, 40-node cap, deterministic radial layout and masked labels (1.1 / §C) |
| `backend/sentinel/api/services/scoring.py` | live decisions store discounted links and the graph from the frozen builder, inside the G6 guard |
| `backend/sentinel/db/seed.py` | `capture_graph_evidence()`: one chronological replay; seeded decisions get links (so `MITIGATING_DISCOUNTED_LINKS` can fire) and a graph |
| `backend/sentinel/api/services/review.py` | `DemoReviewerClock` = DEMO_CLOCK + elapsed monotonic time, the default reviewer clock (1.4) |
| `backend/pyproject.toml` | `threadpoolctl==3.7.0` declared (1.5); `requirements.lock` already pinned 3.7.0 |
| `backend/tests/scenarios/test_db_audit_scoring.py` | +7 tests: hard negatives show their link, every seeded graph is point-in-time, live capture, degraded capture, immutability ×2 |
| `backend/tests/unit/test_reviewer_clock.py` | **new**: 3 tests |
| `backend/tests/unit/test_environment.py` | threadpoolctl pin = lock = installed |
| `backend/tests/unit/test_db.py` | column count 24 → 26, protected 21 → 23 (the new columns are protected) |
| `docs/DEVIATIONS.md` | #32, #33 added; #27, #31 updated |
| `docs/briefs/phase-7-api.md` | brief tracked |

**Part 2 — `phase 7: api`**

| File | Change |
|---|---|
| `backend/sentinel/api/main.py` | app factory, lifespan (fail fast without the DB), routers, error mapping; no CORS |
| `backend/sentinel/api/deps.py` | `get_services` |
| `backend/sentinel/api/routers/internal_scoring.py`, `internal_orders.py`, `internal_audit.py`, `internal_metrics.py`, `demo.py`, `public_checkout.py` | **new**: the §1 router files |
| `backend/sentinel/api/routers/health.py` | `HealthResponse` model, so the frontend type is generated |
| `backend/sentinel/api/services/runtime.py` | **new**: `AppServices` (engine, ScoringService, ReviewService, evaluation, clock, write lock, reset) |
| `backend/sentinel/api/services/order_view.py` | **new**: queue, detail (customer summary, baselines, graph, audit), audit listing |
| `backend/sentinel/api/services/metrics.py` | **new**: DB activity plus the `evaluation.json` sections, unchanged |
| `backend/sentinel/api/services/checkout.py` | **new**: §4 customer-message mapping, `support_reference`, probe logging |
| `backend/sentinel/api/services/errors.py` | `UnknownAccount(NotFound)` (1.3 → 404) |
| `backend/sentinel/api/services/scoring.py` | raises `UnknownAccount`; the live graph's `as_of` is stored in UTC |
| `backend/sentinel/db/seed.py` | writes `demo_presets.json` beside the DB; constants moved to `runtime.py` |
| `backend/sentinel/cli.py` | `export-openapi` |
| `backend/tests/api/test_api.py` | **new**: 67 tests (slow) |
| `backend/tests/model/test_models.py` | artifact-reproduction test trains in a fresh interpreter (see §8) |
| `backend/tests/scenarios/test_db_audit_scoring.py` | unknown account now expects `UnknownAccount` (1.3) |
| `frontend/package.json`, `package-lock.json` | `openapi-typescript` **7.13.0** (exact), `gen:types` script |
| `frontend/src/api/openapi.json` | **new**: exported contract |
| `frontend/src/api/types.ts` | generated; the hand-written types are gone |
| `frontend/src/App.tsx` | `HealthResponse` from the generated `components["schemas"]` |
| `docs/DEVIATIONS.md` | #34 added; #16 updated |
| `docs/PROGRESS.md`, `README.md`, `docs/reports/phase-7.md` | progress row, build status, this report |

No model artifact, policy code, generator code or `features.parquet` byte changed.

## 2. Test results and timings

| Run | Result | Time |
|---|---|---|
| Baseline `-m "not slow"` (session start) | 541 passed | 22.4 s |
| Part 1 gate, full suite incl. slow | **753 passed** | 3 m 28 s |
| `tests/api/test_api.py` alone | 67 passed | 51.5 s |
| Part 2 first full run | 819 passed, **1 failed** (`test_committed_artifacts_reproduce_on_the_same_cpu_count`; see §8) | 4 m 20 s |
| **Part 2 gate, full suite incl. slow** | **820 passed** | **4 m 29 s** |
| `npm run build` (tsc -b + vite) | passes, generated types only | 4.8 s wall (vite 1.31 s) |
| `seed-db` | 250 decisions plus graph capture | 7.3–7.8 s in-process (was 6.7–6.9 s) |

| Latency | Value |
|---|---|
| `POST /score-order` over HTTP (TestClient), 30 fresh order ids on the demo accounts, after one untimed warm-up | median **22.1 ms**, **p95 34.6 ms** (budget 300 ms) |

## 3. Route table as implemented

All internal routes are mounted under `/api/v1/internal` and require `X-Internal-Key`. A missing or wrong key
returns 401 `{"detail": "Unauthorized"}`, tested on every route. The 404 body is always `{"detail": "Not found."}`.

| Method | Path | Request → response | Status codes |
|---|---|---|---|
| GET | `/health` (no key) | → `HealthResponse` | 200 |
| POST | `/api/v1/internal/score-order` | `ScoreOrderRequest` → `ScoreOrderResponse` (source LIVE, idempotent) | 200 · 401 · 404 unknown account · 409 same id with a different payload, or a history order id · 422 validation, `placed_at` after the clock or before the end of the frozen history |
| GET | `/api/v1/internal/orders` | `QueueFilters` (query) → `QueueResponse` | 200 · 401 · 422 (limit > 200, unknown parameter) |
| GET | `/api/v1/internal/orders/{order_id}` | → `OrderDetailResponse` | 200 · 401 · 404 |
| POST | `/api/v1/internal/orders/{order_id}/override` | `OverrideRequest` + `X-Reviewer-Id` → `OverrideResponse` | 200 · 401 · 404 · 409 stale `expected_current_action` · 422 short or missing reason, or BLOCK without G2 and without `INDEPENDENT_EVIDENCE_OF_ABUSE` |
| POST | `/api/v1/internal/orders/{order_id}/appeal` | `AppealRequest` → `AuditEventOut` (APPEAL_OPENED) | 200 · 401 · 404 · 409 appeal already open · 422 |
| GET | `/api/v1/internal/audit-events` | `limit` ≤ 200, `offset`, optional `order_id` → `AuditEventsResponse` | 200 · 401 · 422 |
| GET | `/api/v1/internal/audit-events/verify` | → `AuditVerifyResponse` | 200 · 401 |
| GET | `/api/v1/internal/metrics` | → `MetricsResponse` | 200 · 401 |
| GET | `/api/v1/internal/demo/presets` | → `list[ScoreOrderRequest]` (the three §11 requests) | 200 · 401 · 404 when DEMO_MODE is off |
| POST | `/api/v1/internal/demo/reset` | → `{"status": "reset", "decisions": 250}` | 200 · 401 · 404 when DEMO_MODE is off |
| POST | `/api/v1/public/checkout/decision` (no key) | `CheckoutRequest` → `CheckoutOutcome` | 200 · 404 · 409 · 422, each with a fixed generic body that never echoes a request field |

OpenAPI paths are exactly these 12. None contains `predict` or `model`, and `score` appears only in `/internal/score-order` (tested).

## 4. `OrderDetailResponse` — Demo 2, in full

Real database (`seed-db`), the three presets scored through `POST /score-order`, then `GET /orders/ORD-DEMO-002`.
p_abuse **0.9507**, without graph evidence 0.0993, **BLOCK** (MIN_EXPECTED_COST). FIXED_THRESHOLD also blocks
(τ_block 0.75). RULE_BASED sends it to MANUAL_REVIEW (new account, ₹24,000), the §9.5 contrast.

```json
{
  "order": {
    "order_id": "ORD-DEMO-002",
    "placed_at": "2026-09-01T04:55:00Z",
    "order_value": {
      "inr": 24000.0,
      "display": "₹24,000"
    },
    "discount_pct": 0.0,
    "lines": [
      {
        "sku_id": "SKU-ELECTRONICS-R01-128GB",
        "product_id": "PRD-ELECTRONICS-R01",
        "variant": "128GB",
        "category": "ELECTRONICS",
        "unit_price_inr": 24000.0,
        "quantity": 1
      }
    ],
    "payment_method": "PREPAID_CARD",
    "delivery_speed": "EXPRESS"
  },
  "customer": {
    "account_id": "ACC-DEMO-002",
    "account_age_days": 5,
    "prior_orders": 0,
    "matured_return_rate": null,
    "prior_suspicious_claims_180d": 0,
    "clv_used_by_policy": {
      "inr": 2000.0,
      "display": "₹2,000"
    },
    "clv_basis": "NEW_CUSTOMER_FLOOR"
  },
  "decision": {
    "decision_id": "776c10aa-c2de-45eb-b6af-78a2e569419d",
    "order_id": "ORD-DEMO-002",
    "scored_at": "2026-09-01T05:00:00Z",
    "features_as_of": "2026-09-01T04:55:00Z",
    "scores": {
      "p_return": 0.3783783783783784,
      "p_abuse": 0.9507175565522707,
      "p_abuse_without_graph_evidence": 0.09933435590841493,
      "return_model_version": "return-hgb-fs1.0-e3c877bc",
      "abuse_model_version": "abuse-hgb-fs1.0-446c817f",
      "feature_set_version": "fs-1.0-0ad43d7f",
      "p_return_used_for_action": false
    },
    "prediction_explanation": "The abuse score is driven mainly by links to other accounts sharing this order's device, payment method or delivery pattern.",
    "reasons": [
      {
        "code": "GRAPH_TOKEN_REUSE",
        "model": "ABUSE",
        "direction": "INCREASES",
        "reviewer_text": "The payment method was used by 3 other accounts in the last 30 days.",
        "evidence": {
          "other_accounts": 3
        },
        "attribution_pp": 0.1802,
        "evidence_strength": "STRONG",
        "attribution_note": "Redundant with other relationship evidence; the score is already explained by correlated features."
      },
      {
        "code": "GRAPH_DEVICE_CONFIRMED_LINK",
        "model": "ABUSE",
        "direction": "INCREASES",
        "reviewer_text": "This device was used by 3 accounts later confirmed for return abuse, most recently 3 days ago.",
        "evidence": {
          "confirmed_accounts": 3,
          "days_since_confirmation": 3,
          "other_accounts_on_device_30d": 5
        },
        "attribution_pp": 0.0,
        "evidence_strength": "STRONG",
        "attribution_note": "Redundant with other relationship evidence; the score is already explained by correlated features."
      },
      {
        "code": "TEMPORAL_BURST",
        "model": "ABUSE",
        "direction": "INCREASES",
        "reviewer_text": "Linked accounts placed 4 orders in the last 24 hours.",
        "evidence": {
          "linked_orders_24h": 4
        },
        "attribution_pp": 4.5465,
        "evidence_strength": "MODERATE",
        "attribution_note": null
      },
      {
        "code": "SAME_SKU_COORDINATION",
        "model": "ABUSE",
        "direction": "INCREASES",
        "reviewer_text": "Linked accounts ordered the same item 3 times this week.",
        "evidence": {
          "same_item_orders_7d": 3
        },
        "attribution_pp": 3.7985,
        "evidence_strength": "MODERATE",
        "attribution_note": null
      },
      {
        "code": "GRAPH_DEVICE_SHARED",
        "model": "ABUSE",
        "direction": "INCREASES",
        "reviewer_text": "This device was used by 5 other accounts in the last 30 days.",
        "evidence": {
          "other_accounts_30d": 5
        },
        "attribution_pp": 3.5849,
        "evidence_strength": "MODERATE",
        "attribution_note": null
      },
      {
        "code": "NEW_ACCOUNT_HIGH_VALUE",
        "model": "ABUSE",
        "direction": "INCREASES",
        "reviewer_text": "New account placing a high-value order.",
        "evidence": {
          "account_age_days": 6.0,
          "order_value_inr": 24000.0
        },
        "attribution_pp": 94.2864,
        "evidence_strength": "WEAK",
        "attribution_note": null
      }
    ],
    "graph_summary": {
      "component_size_reliable_90d": 8,
      "confirmed_abusive_accounts_in_component": 3,
      "min_hops_to_confirmed_abuse": 1,
      "linked_orders_24h": 4,
      "corroborating_signal_count": 3,
      "signals": [
        {
          "signal": "DEVICE",
          "present": true,
          "weight": 0.7844922850087741,
          "counts_for_corroboration": true,
          "detail": "Device: confirmed-abuse weight 2.23, 5 other concurrent accounts in 30 d."
        },
        {
          "signal": "PAYMENT_TOKEN",
          "present": true,
          "weight": 0.8931309767988193,
          "counts_for_corroboration": true,
          "detail": "Payment token used by 3 other accounts in 30 d."
        },
        {
          "signal": "ADDRESS",
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "Confirmed-abuse weight 0.00 on this address (needs 0.30)."
        },
        {
          "signal": "TEMPORAL_BURST",
          "present": true,
          "weight": 0.8931309767988193,
          "counts_for_corroboration": true,
          "detail": "4 linked orders in 24 h, 3 same-SKU linked orders in 7 d, via device or token links."
        },
        {
          "signal": "ACCOUNT_CLAIMS",
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "0 suspicious claim(s) on this account in 180 d."
        }
      ],
      "discounted_links": [],
      "weak_evidence_only": false
    },
    "policy": {
      "policy_version": "v1.0",
      "policy_config_sha256": "e1744f126c99d32123f31768538768841b188f7ed7ac7509c406760f313915f0",
      "cost_optimal_action": "BLOCK",
      "selected_action": "BLOCK",
      "selected_rule": "MIN_EXPECTED_COST",
      "costs": [
        {
          "action": "ALLOW",
          "expected_cost": {
            "inr": 19537.25,
            "display": "₹19,537"
          },
          "abusive_branch": {
            "inr": 19537.25,
            "display": "₹19,537"
          },
          "genuine_branch": {
            "inr": 0.0,
            "display": "₹0"
          },
          "operational": {
            "inr": 0.0,
            "display": "₹0"
          },
          "feasible": false,
          "excluded_by": [
            "G5"
          ],
          "rank_by_cost": 4
        },
        {
          "action": "PREPAID_ONLY",
          "expected_cost": {
            "inr": 8117.69,
            "display": "₹8,118"
          },
          "abusive_branch": {
            "inr": 8085.85,
            "display": "₹8,086"
          },
          "genuine_branch": {
            "inr": 31.84,
            "display": "₹32"
          },
          "operational": {
            "inr": 0.0,
            "display": "₹0"
          },
          "feasible": true,
          "excluded_by": [],
          "rank_by_cost": 3
        },
        {
          "action": "MANUAL_REVIEW",
          "expected_cost": {
            "inr": 4187.76,
            "display": "₹4,188"
          },
          "abusive_branch": {
            "inr": 3907.45,
            "display": "₹3,907"
          },
          "genuine_branch": {
            "inr": 30.31,
            "display": "₹30"
          },
          "operational": {
            "inr": 250.0,
            "display": "₹250"
          },
          "feasible": true,
          "excluded_by": [],
          "rank_by_cost": 2
        },
        {
          "action": "BLOCK",
          "expected_cost": {
            "inr": 418.9,
            "display": "₹419"
          },
          "abusive_branch": {
            "inr": 0.0,
            "display": "₹0"
          },
          "genuine_branch": {
            "inr": 418.9,
            "display": "₹419"
          },
          "operational": {
            "inr": 0.0,
            "display": "₹0"
          },
          "feasible": true,
          "excluded_by": [],
          "rank_by_cost": 1
        }
      ],
      "guardrails": [
        {
          "guardrail_id": "G1",
          "name": "Return probability excluded",
          "triggered": false,
          "effect": "NONE",
          "removed_actions": [],
          "detail": "p_return is not an input to expected cost or any guardrail; shown for context only."
        },
        {
          "guardrail_id": "G2",
          "name": "BLOCK needs corroboration",
          "triggered": false,
          "effect": "NONE",
          "removed_actions": [],
          "detail": "Three corroborating signals: DEVICE, PAYMENT_TOKEN, TEMPORAL_BURST."
        },
        {
          "guardrail_id": "G3",
          "name": "BLOCK needs confidence",
          "triggered": false,
          "effect": "NONE",
          "removed_actions": [],
          "detail": "p_abuse 0.950 meets the 0.70 minimum for BLOCK."
        },
        {
          "guardrail_id": "G4",
          "name": "No BLOCK on weak or stale evidence",
          "triggered": false,
          "effect": "NONE",
          "removed_actions": [],
          "detail": "Evidence is recent and at least one counted signal is strong."
        },
        {
          "guardrail_id": "G5",
          "name": "No silent ALLOW at high exposure",
          "triggered": true,
          "effect": "REMOVED_ACTIONS",
          "removed_actions": [
            "ALLOW"
          ],
          "detail": "G5 removes ALLOW when p_abuse is at least 0.40 and the order value is at least ₹10,000."
        }
      ],
      "policy_explanation": "BLOCK was selected because its expected cost (₹419) is lower than MANUAL_REVIEW (₹4,188), PREPAID_ONLY (₹8,118) and ALLOW (₹19,537) under policy v1.0. ALLOW was also not permitted: G5 removes ALLOW when p_abuse is at least 0.40 and the order value is at least ₹10,000.",
      "assumptions_notice": "Monetary values are demonstration assumptions (policy v1.0)."
    },
    "status": "AUTO_APPLIED",
    "audit_event_id": "87c51424-3b4a-4be0-9477-96d8b0459d1f",
    "degraded_mode": false,
    "idempotent_replay": false
  },
  "graph": {
    "nodes": [
      {
        "id": "ACC:ACC-DEMO-002",
        "kind": "ACCOUNT",
        "label": "ACC-DEMO-002",
        "state": "CURRENT",
        "flags": [],
        "x": 0.0,
        "y": 0.0
      },
      {
        "id": "ORD:ORD-DEMO-002",
        "kind": "ORDER",
        "label": "ORD-DEMO-002",
        "state": "CURRENT",
        "flags": [],
        "x": 86.6,
        "y": -50.0
      },
      {
        "id": "ADR:43d4f91ffe811dda",
        "kind": "ADDRESS",
        "label": "Address ••e5a9",
        "state": "NEUTRAL",
        "flags": [],
        "x": 0.0,
        "y": -200.0
      },
      {
        "id": "DEV:5152b41532945507",
        "kind": "DEVICE",
        "label": "Device ••f5ae",
        "state": "LINKED",
        "flags": [],
        "x": 173.21,
        "y": 100.0
      },
      {
        "id": "TOK:cdca1da0e21ddebc",
        "kind": "PAYMENT_TOKEN",
        "label": "Payment token ••7d56",
        "state": "LINKED",
        "flags": [],
        "x": -173.21,
        "y": 100.0
      },
      {
        "id": "ACC:ACC-20F052A30F",
        "kind": "ACCOUNT",
        "label": "Account ••A30F",
        "state": "CONFIRMED_ABUSE",
        "flags": [],
        "x": 220.0,
        "y": -381.05
      },
      {
        "id": "ACC:ACC-9225F64678",
        "kind": "ACCOUNT",
        "label": "Account ••4678",
        "state": "CONFIRMED_ABUSE",
        "flags": [],
        "x": 440.0,
        "y": 0.0
      },
      {
        "id": "ACC:ACC-A6E8E9C22A",
        "kind": "ACCOUNT",
        "label": "Account ••C22A",
        "state": "CONFIRMED_ABUSE",
        "flags": [],
        "x": 220.0,
        "y": 381.05
      },
      {
        "id": "ACC:ACC-A801E0129F",
        "kind": "ACCOUNT",
        "label": "Account ••129F",
        "state": "LINKED",
        "flags": [
          "RECENT_24H"
        ],
        "x": -220.0,
        "y": 381.05
      },
      {
        "id": "ACC:ACC-B2C3BFE431",
        "kind": "ACCOUNT",
        "label": "Account ••E431",
        "state": "LINKED",
        "flags": [
          "RECENT_24H"
        ],
        "x": -440.0,
        "y": 0.0
      },
      {
        "id": "ACC:ACC-2B231FE5D6",
        "kind": "ACCOUNT",
        "label": "Account ••E5D6",
        "state": "LINKED",
        "flags": [
          "RECENT_24H"
        ],
        "x": -220.0,
        "y": -381.05
      },
      {
        "id": "ORD:ORD-343BDE231D25",
        "kind": "ORDER",
        "label": "Order ••1D25",
        "state": "LINKED",
        "flags": [
          "RECENT_24H"
        ],
        "x": -265.0,
        "y": -458.99
      },
      {
        "id": "ORD:ORD-4617D195F7B1",
        "kind": "ORDER",
        "label": "Order ••F7B1",
        "state": "LINKED",
        "flags": [
          "RECENT_24H"
        ],
        "x": -265.0,
        "y": 458.99
      },
      {
        "id": "ORD:ORD-BA7A88E00C94",
        "kind": "ORDER",
        "label": "Order ••0C94",
        "state": "LINKED",
        "flags": [
          "RECENT_24H"
        ],
        "x": -530.0,
        "y": 0.0
      }
    ],
    "edges": [
      {
        "id": "ACC:ACC-20F052A30F|DEV:5152b41532945507",
        "source": "ACC:ACC-20F052A30F",
        "target": "DEV:5152b41532945507",
        "kind": "USED_DEVICE",
        "age_days": 1.8681,
        "reliability": 0.8,
        "decayed_weight": 0.7662,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-2B231FE5D6|TOK:cdca1da0e21ddebc",
        "source": "ACC:ACC-2B231FE5D6",
        "target": "TOK:cdca1da0e21ddebc",
        "kind": "USED_TOKEN",
        "age_days": 0.6632,
        "reliability": 0.9,
        "decayed_weight": 0.8931,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-9225F64678|DEV:5152b41532945507",
        "source": "ACC:ACC-9225F64678",
        "target": "DEV:5152b41532945507",
        "kind": "USED_DEVICE",
        "age_days": 4.7951,
        "reliability": 0.8,
        "decayed_weight": 0.7161,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-A6E8E9C22A|DEV:5152b41532945507",
        "source": "ACC:ACC-A6E8E9C22A",
        "target": "DEV:5152b41532945507",
        "kind": "USED_DEVICE",
        "age_days": 2.6389,
        "reliability": 0.8,
        "decayed_weight": 0.7527,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-A801E0129F|DEV:5152b41532945507",
        "source": "ACC:ACC-A801E0129F",
        "target": "DEV:5152b41532945507",
        "kind": "USED_DEVICE",
        "age_days": 0.8472,
        "reliability": 0.8,
        "decayed_weight": 0.7845,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-A801E0129F|TOK:cdca1da0e21ddebc",
        "source": "ACC:ACC-A801E0129F",
        "target": "TOK:cdca1da0e21ddebc",
        "kind": "USED_TOKEN",
        "age_days": 0.8472,
        "reliability": 0.9,
        "decayed_weight": 0.8912,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-B2C3BFE431|DEV:5152b41532945507",
        "source": "ACC:ACC-B2C3BFE431",
        "target": "DEV:5152b41532945507",
        "kind": "USED_DEVICE",
        "age_days": 0.9479,
        "reliability": 0.8,
        "decayed_weight": 0.7827,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-B2C3BFE431|TOK:cdca1da0e21ddebc",
        "source": "ACC:ACC-B2C3BFE431",
        "target": "TOK:cdca1da0e21ddebc",
        "kind": "USED_TOKEN",
        "age_days": 0.9479,
        "reliability": 0.9,
        "decayed_weight": 0.8902,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-DEMO-002|ADR:43d4f91ffe811dda",
        "source": "ACC:ACC-DEMO-002",
        "target": "ADR:43d4f91ffe811dda",
        "kind": "SHIPPED_TO",
        "age_days": 0.0,
        "reliability": 0.4,
        "decayed_weight": 0.4,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-DEMO-002|DEV:5152b41532945507",
        "source": "ACC:ACC-DEMO-002",
        "target": "DEV:5152b41532945507",
        "kind": "USED_DEVICE",
        "age_days": 0.0,
        "reliability": 0.8,
        "decayed_weight": 0.8,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ACC:ACC-DEMO-002|TOK:cdca1da0e21ddebc",
        "source": "ACC:ACC-DEMO-002",
        "target": "TOK:cdca1da0e21ddebc",
        "kind": "USED_TOKEN",
        "age_days": 0.0,
        "reliability": 0.9,
        "decayed_weight": 0.9,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ORD:ORD-343BDE231D25|ACC:ACC-2B231FE5D6",
        "source": "ORD:ORD-343BDE231D25",
        "target": "ACC:ACC-2B231FE5D6",
        "kind": "PLACED_BY",
        "age_days": 0.6632,
        "reliability": 1.0,
        "decayed_weight": 1.0,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ORD:ORD-4617D195F7B1|ACC:ACC-A801E0129F",
        "source": "ORD:ORD-4617D195F7B1",
        "target": "ACC:ACC-A801E0129F",
        "kind": "PLACED_BY",
        "age_days": 0.8472,
        "reliability": 1.0,
        "decayed_weight": 1.0,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ORD:ORD-BA7A88E00C94|ACC:ACC-B2C3BFE431",
        "source": "ORD:ORD-BA7A88E00C94",
        "target": "ACC:ACC-B2C3BFE431",
        "kind": "PLACED_BY",
        "age_days": 0.9479,
        "reliability": 1.0,
        "decayed_weight": 1.0,
        "counted_as_evidence": true,
        "discount_reason": null
      },
      {
        "id": "ORD:ORD-DEMO-002|ACC:ACC-DEMO-002",
        "source": "ORD:ORD-DEMO-002",
        "target": "ACC:ACC-DEMO-002",
        "kind": "PLACED_BY",
        "age_days": 0.0,
        "reliability": 1.0,
        "decayed_weight": 1.0,
        "counted_as_evidence": true,
        "discount_reason": null
      }
    ],
    "truncated": false,
    "hidden_node_count": 0,
    "as_of": "2026-09-01T04:55:00Z"
  },
  "baselines": [
    {
      "strategy": "FIXED_THRESHOLD",
      "action": "BLOCK",
      "rule_fired": "p_abuse >= 0.75"
    },
    {
      "strategy": "RULE_BASED",
      "action": "MANUAL_REVIEW",
      "rule_fired": "new account (< 30 d) and value >= ₹15,000"
    }
  ],
  "audit_events": [
    {
      "seq": 252,
      "event_id": "87c51424-3b4a-4be0-9477-96d8b0459d1f",
      "event_type": "DECISION_CREATED",
      "occurred_at": "2026-09-01T05:00:00Z",
      "order_id": "ORD-DEMO-002",
      "actor_type": "SYSTEM",
      "actor_id": "sentinel-scoring",
      "previous_action": null,
      "new_action": "BLOCK",
      "policy_version": "v1.0",
      "return_model_version": "return-hgb-fs1.0-e3c877bc",
      "abuse_model_version": "abuse-hgb-fs1.0-446c817f",
      "payload": {
        "actor": {
          "id": "sentinel-scoring",
          "type": "SYSTEM"
        },
        "appeal": null,
        "audit_event_id": "87c51424-3b4a-4be0-9477-96d8b0459d1f",
        "candidate_actions": [
          {
            "abusive_branch": {
              "display": "₹19,537",
              "inr": 19537.25
            },
            "action": "ALLOW",
            "excluded_by": [
              "G5"
            ],
            "expected_cost": {
              "display": "₹19,537",
              "inr": 19537.25
            },
            "feasible": false,
            "genuine_branch": {
              "display": "₹0",
              "inr": 0.0
            },
            "operational": {
              "display": "₹0",
              "inr": 0.0
            },
            "rank_by_cost": 4
          },
          {
            "abusive_branch": {
              "display": "₹8,086",
              "inr": 8085.85
            },
            "action": "PREPAID_ONLY",
            "excluded_by": [],
            "expected_cost": {
              "display": "₹8,118",
              "inr": 8117.69
            },
            "feasible": true,
            "genuine_branch": {
              "display": "₹32",
              "inr": 31.84
            },
            "operational": {
              "display": "₹0",
              "inr": 0.0
            },
            "rank_by_cost": 3
          },
          {
            "abusive_branch": {
              "display": "₹3,907",
              "inr": 3907.45
            },
            "action": "MANUAL_REVIEW",
            "excluded_by": [],
            "expected_cost": {
              "display": "₹4,188",
              "inr": 4187.76
            },
            "feasible": true,
            "genuine_branch": {
              "display": "₹30",
              "inr": 30.31
            },
            "operational": {
              "display": "₹250",
              "inr": 250.0
            },
            "rank_by_cost": 2
          },
          {
            "abusive_branch": {
              "display": "₹0",
              "inr": 0.0
            },
            "action": "BLOCK",
            "excluded_by": [],
            "expected_cost": {
              "display": "₹419",
              "inr": 418.9
            },
            "feasible": true,
            "genuine_branch": {
              "display": "₹419",
              "inr": 418.9
            },
            "operational": {
              "display": "₹0",
              "inr": 0.0
            },
            "rank_by_cost": 1
          }
        ],
        "cost_optimal_action": "BLOCK",
        "decision_id": "776c10aa-c2de-45eb-b6af-78a2e569419d",
        "degraded_mode": false,
        "event_type": "DECISION_CREATED",
        "feature_attributions_pp": {
          "account_age_days": -3.8629,
          "address_other_accounts_weighted_30d": 0.0,
          "component_abuse_ratio_smoothed": 0.0,
          "component_recent_claims_30d": 10.9933,
          "component_size_reliable_90d": -0.8425,
          "confirmed_abuse_proximity": 0.0,
          "device_confirmed_abuse_weight": 0.0,
          "device_other_accounts_30d": 3.5849,
          "identifier_reuse_velocity_7d": 5.3842,
          "linked_orders_24h": 4.5465,
          "linked_same_sku_7d": 3.7985,
          "new_device_for_account": -0.2036,
          "order_value_inr": 94.2864,
          "primary_category": 9.595,
          "prior_orders": -2.6255,
          "prior_suspicious_claims_180d": 0.0,
          "token_other_accounts_30d": 0.1802
        },
        "features_as_of": "2026-09-01T10:25:00+05:30",
        "graph_summary": {
          "component_size_reliable_90d": 8,
          "confirmed_abusive_accounts_in_component": 3,
          "corroborating_signal_count": 3,
          "discounted_links": [],
          "linked_orders_24h": 4,
          "min_hops_to_confirmed_abuse": 1,
          "signals": [
            {
              "counts_for_corroboration": true,
              "detail": "Device: confirmed-abuse weight 2.23, 5 other concurrent accounts in 30 d.",
              "present": true,
              "signal": "DEVICE",
              "weight": 0.784492
            },
            {
              "counts_for_corroboration": true,
              "detail": "Payment token used by 3 other accounts in 30 d.",
              "present": true,
              "signal": "PAYMENT_TOKEN",
              "weight": 0.893131
            },
            {
              "counts_for_corroboration": false,
              "detail": "Confirmed-abuse weight 0.00 on this address (needs 0.30).",
              "present": false,
              "signal": "ADDRESS",
              "weight": 0.0
            },
            {
              "counts_for_corroboration": true,
              "detail": "4 linked orders in 24 h, 3 same-SKU linked orders in 7 d, via device or token links.",
              "present": true,
              "signal": "TEMPORAL_BURST",
              "weight": 0.893131
            },
            {
              "counts_for_corroboration": false,
              "detail": "0 suspicious claim(s) on this account in 180 d.",
              "present": false,
              "signal": "ACCOUNT_CLAIMS",
              "weight": 0.0
            }
          ],
          "weak_evidence_only": false
        },
        "guardrails": [
          {
            "detail": "p_return is not an input to expected cost or any guardrail; shown for context only.",
            "effect": "NONE",
            "guardrail_id": "G1",
            "name": "Return probability excluded",
            "removed_actions": [],
            "triggered": false
          },
          {
            "detail": "Three corroborating signals: DEVICE, PAYMENT_TOKEN, TEMPORAL_BURST.",
            "effect": "NONE",
            "guardrail_id": "G2",
            "name": "BLOCK needs corroboration",
            "removed_actions": [],
            "triggered": false
          },
          {
            "detail": "p_abuse 0.950 meets the 0.70 minimum for BLOCK.",
            "effect": "NONE",
            "guardrail_id": "G3",
            "name": "BLOCK needs confidence",
            "removed_actions": [],
            "triggered": false
          },
          {
            "detail": "Evidence is recent and at least one counted signal is strong.",
            "effect": "NONE",
            "guardrail_id": "G4",
            "name": "No BLOCK on weak or stale evidence",
            "removed_actions": [],
            "triggered": false
          },
          {
            "detail": "G5 removes ALLOW when p_abuse is at least 0.40 and the order value is at least ₹10,000.",
            "effect": "REMOVED_ACTIONS",
            "guardrail_id": "G5",
            "name": "No silent ALLOW at high exposure",
            "removed_actions": [
              "ALLOW"
            ],
            "triggered": true
          }
        ],
        "model_versions": {
          "abuse_artifact_sha256": "446c817f97bd67b61706d7ada5e727bf4732d474ecb24161e8862dac6bd20f20",
          "abuse_model": "abuse-hgb-fs1.0-446c817f",
          "feature_set": "fs-1.0-0ad43d7f",
          "label_definition": "ld-1.0",
          "return_artifact_sha256": "e3c877bc2a16d2991246c1e6b22271e214e517bcfe886b9c011b5221dcf074f8",
          "return_model": "return-hgb-fs1.0-e3c877bc"
        },
        "new_action": "BLOCK",
        "occurred_at": "2026-09-01T10:30:00+05:30",
        "order_id": "ORD-DEMO-002",
        "original_recommendation": "BLOCK",
        "override": null,
        "p_abuse": 0.950718,
        "p_abuse_without_graph_evidence": 0.099334,
        "p_return": 0.378378,
        "policy_config_sha256": "e1744f126c99d32123f31768538768841b188f7ed7ac7509c406760f313915f0",
        "policy_explanation": "BLOCK was selected because its expected cost (₹419) is lower than MANUAL_REVIEW (₹4,188), PREPAID_ONLY (₹8,118) and ALLOW (₹19,537) under policy v1.0. ALLOW was also not permitted: G5 removes ALLOW when p_abuse is at least 0.40 and the order value is at least ₹10,000.",
        "policy_rule": "MIN_EXPECTED_COST",
        "policy_version": "v1.0",
        "prediction_explanation": "The abuse score is driven mainly by links to other accounts sharing this order's device, payment method or delivery pattern.",
        "previous_action": null,
        "reason_codes": [
          "GRAPH_TOKEN_REUSE",
          "GRAPH_DEVICE_CONFIRMED_LINK",
          "TEMPORAL_BURST",
          "SAME_SKU_COORDINATION",
          "GRAPH_DEVICE_SHARED",
          "NEW_ACCOUNT_HIGH_VALUE"
        ],
        "schema_version": "audit-1.0",
        "selected_action": "BLOCK"
      },
      "prev_hash": "65ee51834f52ba6f4de7705d1bfcefadf6e84ac39820630d77b5a8a8ded126c4",
      "event_hash": "e1be220fded17aab6a69c96b7f8a2e3e99446922ee12c197f28e469d126b4c3b"
    }
  ],
  "current_action": "BLOCK",
  "appeal_reference": null
}
```

## 5. Demo 2 `GraphPayload`, summarised

| | Count |
|---|---|
| Nodes (14, cap 40, **not truncated**, hidden 0) | ACCOUNT 7 (1 CURRENT, **3 CONFIRMED_ABUSE**, 3 LINKED) · ORDER 4 (1 CURRENT, 3 LINKED with RECENT_24H) · DEVICE 1 (LINKED) · PAYMENT_TOKEN 1 (LINKED) · ADDRESS 1 (NEUTRAL: the ring rotates addresses, so no other account shares it) |
| Edges (15) | USED_DEVICE 6 (own + 5 peers) · USED_TOKEN 4 (own + 3 peers) · PLACED_BY 4 · SHIPPED_TO 1 (own) |
| Discounted edges | **none**: every peer link is concurrent, recent and reliable, so all 15 are `counted_as_evidence = true` |
| Flags | RECENT_24H on the 3 linked orders and the 3 accounts that placed them |

The graph draws **3** of the **4** orders counted in `linked_orders_24h`. The fourth was placed by a member reached
in two account hops (#24), and the ego graph shows only directly linked accounts (recorded in #32). Dashed edges do
occur elsewhere: on the 250 seeded decisions, household, multi-tenant, sequential-device and stale links produce them
(tested on hard-negative orders).

## 6. Public checkout responses, all three demos

| | Demo 1 (ALLOW) | Demo 2 (BLOCK) | Demo 3 (MANUAL_REVIEW) |
|---|---|---|---|
| `outcome` | `CONFIRMED` | `UNABLE_TO_PROCESS` | `CONFIRMED` |
| `customer_message` | "Your order is confirmed." | "We're unable to process this order right now. Contact support with reference SUP-3805F6F2." | "Your order is confirmed." |
| `support_reference` | `SUP-F39C1A09` | `SUP-3805F6F2` | `SUP-F4AAE4B3` |

```json
{
  "ORD-DEMO-001": {
    "order_id": "ORD-DEMO-001",
    "outcome": "CONFIRMED",
    "customer_message": "Your order is confirmed.",
    "support_reference": "SUP-F39C1A09"
  },
  "ORD-DEMO-002": {
    "order_id": "ORD-DEMO-002",
    "outcome": "UNABLE_TO_PROCESS",
    "customer_message": "We're unable to process this order right now. Contact support with reference SUP-3805F6F2.",
    "support_reference": "SUP-3805F6F2"
  },
  "ORD-DEMO-003": {
    "order_id": "ORD-DEMO-003",
    "outcome": "CONFIRMED",
    "customer_message": "Your order is confirmed.",
    "support_reference": "SUP-F4AAE4B3"
  }
}
```

Demo 1 and Demo 3 bodies are byte-identical once `order_id` and `support_reference` are substituted (tested).
After a reviewer overrides Demo 3 to PREPAID_ONLY, its checkout returns `PREPAID_PAYMENT_REQUIRED`, because the
outcome follows the current action (tested, §11 live step).

## 7. `GET /metrics`

Same database, after the three demos were scored (253 decisions). `activity` is counted from the DB, and
`version_traceability` is **1.0**. `backtest`, `models`, `cold_start_ring_recall` and `sensitivity` are
`evaluation.json`, unchanged (tested equal).

```json
{
  "activity": {
    "orders_evaluated": 253,
    "action_distribution": {
      "ALLOW": 91,
      "PREPAID_ONLY": 15,
      "MANUAL_REVIEW": 127,
      "BLOCK": 20
    },
    "friction_orders": 142,
    "manual_review_volume": 127,
    "override_rate": 0.0,
    "model_estimated_cost_avoided": {
      "inr": 829290.9,
      "display": "₹8,29,291"
    },
    "explanation_coverage": 1.0,
    "version_traceability": 1.0,
    "weak_evidence_decisions": 0
  },
  "backtest": [
    {
      "strategy": "SENTINEL",
      "realized_cost_per_1000": {
        "inr": 195312.54,
        "display": "₹1,95,313"
      },
      "abuse_loss_prevented": {
        "inr": 850799.93,
        "display": "₹8,50,800"
      },
      "genuine_block_rate": 0.001152073732718894,
      "customer_friction_rate": 0.03513824884792627,
      "manual_reviews_per_1000": 64.92089470812876,
      "cost_per_detected_abuse": {
        "inr": 1196.91,
        "display": "₹1,197"
      },
      "revenue_preserved": {
        "inr": 3128892.04,
        "display": "₹31,28,892"
      },
      "precision_block": 0.875,
      "recall_intercepted": 0.7154639175257731
    },
    {
      "strategy": "FIXED_THRESHOLD",
      "realized_cost_per_1000": {
        "inr": 160112.09,
        "display": "₹1,60,112"
      },
      "abuse_loss_prevented": {
        "inr": 937968.57,
        "display": "₹9,37,969"
      },
      "genuine_block_rate": 0.004032258064516129,
      "customer_friction_rate": 0.03398617511520737,
      "manual_reviews_per_1000": 56.737588652482266,
      "cost_per_detected_abuse": {
        "inr": 1252.65,
        "display": "₹1,253"
      },
      "revenue_preserved": {
        "inr": 3114814.49,
        "display": "₹31,14,814"
      },
      "precision_block": 0.8627450980392157,
      "recall_intercepted": 0.8247422680412371
    },
    {
      "strategy": "RULE_BASED",
      "realized_cost_per_1000": {
        "inr": 742313.29,
        "display": "₹7,42,313"
      },
      "abuse_loss_prevented": {
        "inr": 268729.86,
        "display": "₹2,68,730"
      },
      "genuine_block_rate": 0.024193548387096774,
      "customer_friction_rate": 0.0748847926267281,
      "manual_reviews_per_1000": 8.72885979268958,
      "cost_per_detected_abuse": {
        "inr": 45668.02,
        "display": "₹45,668"
      },
      "revenue_preserved": {
        "inr": 3029945.52,
        "display": "₹30,29,946"
      },
      "precision_block": 0.0,
      "recall_intercepted": 0.11030927835051546
    },
    {
      "strategy": "ALLOW_ALL",
      "realized_cost_per_1000": {
        "inr": 623290.95,
        "display": "₹6,23,291"
      },
      "abuse_loss_prevented": {
        "inr": 0.0,
        "display": "₹0"
      },
      "genuine_block_rate": 0.0,
      "customer_friction_rate": 0.0,
      "manual_reviews_per_1000": 0.0,
      "cost_per_detected_abuse": {
        "inr": 0.0,
        "display": "₹0"
      },
      "revenue_preserved": {
        "inr": 3173690.95,
        "display": "₹31,73,691"
      },
      "precision_block": 0.0,
      "recall_intercepted": 0.0
    }
  ],
  "models": [
    {
      "model": "RETURN",
      "model_version": "return-hgb-fs1.0-e3c877bc",
      "pr_auc": 0.38648592356168104,
      "pr_auc_ci95": [
        0.34360692991450725,
        0.4329458680799505
      ],
      "brier": 0.1548429011083062,
      "ece_10bin_quantile": 0.0321114704223476,
      "calibration_curve": [
        {
          "bin_mean_predicted": 0.07652211812304655,
          "observed_rate": 0.14054054054054055,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.1322751322751323,
          "observed_rate": 0.13513513513513514,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.14902820585477414,
          "observed_rate": 0.14594594594594595,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.16605166051660517,
          "observed_rate": 0.1783783783783784,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.17147254629631062,
          "observed_rate": 0.10270270270270271,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.1952301558122501,
          "observed_rate": 0.1837837837837838,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.2011494252873563,
          "observed_rate": 0.15675675675675677,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.22661811674284146,
          "observed_rate": 0.2810810810810811,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.26228916593929474,
          "observed_rate": 0.31891891891891894,
          "count": 185
        },
        {
          "bin_mean_predicted": 0.5084029509509407,
          "observed_rate": 0.5054347826086957,
          "count": 184
        }
      ],
      "by_value_band": {
        "<₹2k": {
          "n": 808.0,
          "positives": 159.0,
          "prevalence": 0.1967821782178218,
          "pr_auc": 0.3889640120838653,
          "pr_auc_ci95_low": 0.31960617436906463,
          "pr_auc_ci95_high": 0.4601963988943951,
          "brier": 0.14390134537222532,
          "ece_10bin_quantile": 0.04457639188919675
        },
        ">₹10k": {
          "n": 331.0,
          "positives": 86.0,
          "prevalence": 0.2598187311178248,
          "pr_auc": 0.46207138824462124,
          "pr_auc_ci95_low": 0.3671448066144875,
          "pr_auc_ci95_high": 0.5549570064470568,
          "brier": 0.17379572563973314,
          "ece_10bin_quantile": 0.060846106887746054
        },
        "₹2–10k": {
          "n": 710.0,
          "positives": 152.0,
          "prevalence": 0.2140845070422535,
          "pr_auc": 0.35346940295621426,
          "pr_auc_ci95_low": 0.2880606439322174,
          "pr_auc_ci95_high": 0.42755092721120025,
          "brier": 0.1584589463404908,
          "ece_10bin_quantile": 0.04724921744939485
        }
      },
      "by_cohort": {
        "account_age=30–365 d": {
          "n": 552.0,
          "positives": 93.0,
          "prevalence": 0.16847826086956522,
          "pr_auc": 0.20758946401663736,
          "pr_auc_ci95_low": 0.15545887700726088,
          "pr_auc_ci95_high": 0.28789209124649345,
          "brier": 0.1411177970758193,
          "ece_10bin_quantile": 0.05884010096597205
        },
        "account_age=<30 d": {
          "n": 185.0,
          "positives": 45.0,
          "prevalence": 0.24324324324324326,
          "pr_auc": 0.33565594402869026,
          "pr_auc_ci95_low": 0.2435274196914021,
          "pr_auc_ci95_high": 0.46698315192101547,
          "brier": 0.17909803330891957,
          "ece_10bin_quantile": 0.09556585197319134
        },
        "account_age=>365 d": {
          "n": 1112.0,
          "positives": 259.0,
          "prevalence": 0.2329136690647482,
          "pr_auc": 0.4471440151290033,
          "pr_auc_ci95_low": 0.3859266756511738,
          "pr_auc_ci95_high": 0.5075429765228014,
          "brier": 0.1576208309363811,
          "ece_10bin_quantile": 0.0305651563180882
        },
        "multi_tenant_address=no": {
          "n": 1792.0,
          "positives": 390.0,
          "prevalence": 0.21763392857142858,
          "pr_auc": 0.39059565230779425,
          "pr_auc_ci95_low": 0.3472279841423749,
          "pr_auc_ci95_high": 0.4375139138101529,
          "brier": 0.15622215819030552,
          "ece_10bin_quantile": 0.02747203770628507
        },
        "multi_tenant_address=yes": {
          "n": 57.0,
          "positives": 7.0,
          "prevalence": 0.12280701754385964,
          "pr_auc": 0.1592074592074592,
          "pr_auc_ci95_low": 0.05465765090415862,
          "pr_auc_ci95_high": 0.46995442362218676,
          "brier": 0.11148099424966122,
          "ece_10bin_quantile": 0.10791078428319269
        },
        "payment=COD": {
          "n": 484.0,
          "positives": 80.0,
          "prevalence": 0.1652892561983471,
          "pr_auc": 0.2797480069256677,
          "pr_auc_ci95_low": 0.20141522229419528,
          "pr_auc_ci95_high": 0.37424302020095723,
          "brier": 0.1328934680015892,
          "ece_10bin_quantile": 0.06021323262672742
        },
        "payment=PREPAID": {
          "n": 1365.0,
          "positives": 317.0,
          "prevalence": 0.23223443223443224,
          "pr_auc": 0.4112106968649095,
          "pr_auc_ci95_low": 0.3632731115203651,
          "pr_auc_ci95_high": 0.4666192987957689,
          "brier": 0.1626257037629956,
          "ece_10bin_quantile": 0.03277382325700807
        },
        "primary_category=ACCESSORIES": {
          "n": 186.0,
          "positives": 33.0,
          "prevalence": 0.1774193548387097,
          "pr_auc": 0.21111639665367501,
          "pr_auc_ci95_low": 0.1450904604143356,
          "pr_auc_ci95_high": 0.3344370422200895,
          "brier": 0.15047218571164145,
          "ece_10bin_quantile": 0.0846498518518748
        },
        "primary_category=APPAREL": {
          "n": 477.0,
          "positives": 127.0,
          "prevalence": 0.2662473794549266,
          "pr_auc": 0.49307353871505233,
          "pr_auc_ci95_low": 0.407249316259648,
          "pr_auc_ci95_high": 0.5823811747361237,
          "brier": 0.16887926255620045,
          "ece_10bin_quantile": 0.037037819097841276
        },
        "primary_category=BEAUTY": {
          "n": 203.0,
          "positives": 21.0,
          "prevalence": 0.10344827586206896,
          "pr_auc": 0.12327797234425561,
          "pr_auc_ci95_low": 0.06456667878413563,
          "pr_auc_ci95_high": 0.26338967279891795,
          "brier": 0.09800173162878884,
          "ece_10bin_quantile": 0.09139103522142818
        },
        "primary_category=ELECTRONICS": {
          "n": 452.0,
          "positives": 91.0,
          "prevalence": 0.2013274336283186,
          "pr_auc": 0.29601592074526506,
          "pr_auc_ci95_low": 0.22696278061680256,
          "pr_auc_ci95_high": 0.38240738484233433,
          "brier": 0.15505635271866566,
          "ece_10bin_quantile": 0.05692718864995566
        },
        "primary_category=FOOTWEAR": {
          "n": 305.0,
          "positives": 89.0,
          "prevalence": 0.29180327868852457,
          "pr_auc": 0.4934821023904721,
          "pr_auc_ci95_low": 0.40139253853945467,
          "pr_auc_ci95_high": 0.5901551042562443,
          "brier": 0.18941980603537828,
          "ece_10bin_quantile": 0.0979167338681457
        },
        "primary_category=HOME": {
          "n": 226.0,
          "positives": 36.0,
          "prevalence": 0.1592920353982301,
          "pr_auc": 0.21723308374650913,
          "pr_auc_ci95_low": 0.1429449499644434,
          "pr_auc_ci95_high": 0.3487229264831396,
          "brier": 0.13278064414740642,
          "ece_10bin_quantile": 0.056229556350543906
        },
        "archetype=FREQUENT_RETURNER": {
          "n": 247.0,
          "positives": 131.0,
          "prevalence": 0.5303643724696356,
          "pr_auc": 0.6676416063473386,
          "pr_auc_ci95_low": 0.5894982365410008,
          "pr_auc_ci95_high": 0.7477020512937399,
          "brier": 0.26046753406751727,
          "ece_10bin_quantile": 0.1619878504251453
        },
        "archetype=HOUSEHOLD": {
          "n": 88.0,
          "positives": 15.0,
          "prevalence": 0.17045454545454544,
          "pr_auc": 0.24390225034155125,
          "pr_auc_ci95_low": 0.12855097550425645,
          "pr_auc_ci95_high": 0.4537357763520061,
          "brier": 0.14553765439953678,
          "ece_10bin_quantile": 0.10752641327411018
        },
        "archetype=NORMAL": {
          "n": 1201.0,
          "positives": 160.0,
          "prevalence": 0.13322231473771856,
          "pr_auc": 0.1641802715132482,
          "pr_auc_ci95_low": 0.1299440707358289,
          "pr_auc_ci95_high": 0.20932787183933493,
          "brier": 0.11967150844888613,
          "ece_10bin_quantile": 0.061366577891122806
        },
        "archetype=OFFICE_HOSTEL_PG": {
          "n": 74.0,
          "positives": 12.0,
          "prevalence": 0.16216216216216217,
          "pr_auc": 0.17725562245550647,
          "pr_auc_ci95_low": 0.09259472518104231,
          "pr_auc_ci95_high": 0.3269178933358192,
          "brier": 0.14249184683218083,
          "ece_10bin_quantile": 0.11529138917234329
        },
        "archetype=OPPORTUNISTIC": {
          "n": 21.0,
          "positives": 11.0,
          "prevalence": 0.5238095238095238,
          "pr_auc": 0.4488844488844489,
          "pr_auc_ci95_low": 0.2684417104162239,
          "pr_auc_ci95_high": 0.7427287982500693,
          "brier": 0.3590129179346973,
          "ece_10bin_quantile": 0.42042281568125317
        },
        "archetype=REFURB_DEVICE": {
          "n": 55.0,
          "positives": 7.0,
          "prevalence": 0.12727272727272726,
          "pr_auc": 0.10878988121513039,
          "pr_auc_ci95_low": 0.047136809269162215,
          "pr_auc_ci95_high": 0.21470033121924434,
          "brier": 0.12196976219187393,
          "ece_10bin_quantile": 0.11593256089509513
        },
        "archetype=RING": {
          "n": 150.0,
          "positives": 50.0,
          "prevalence": 0.3333333333333333,
          "pr_auc": 0.43008928006046304,
          "pr_auc_ci95_low": 0.3328706606877208,
          "pr_auc_ci95_high": 0.5615777899031993,
          "brier": 0.2272714194392078,
          "ece_10bin_quantile": 0.14350297881315316
        },
        "archetype=UNCONFIRMED_ABUSER": {
          "n": 13.0,
          "positives": 11.0,
          "prevalence": 0.8461538461538461,
          "pr_auc": 0.9583333333333333,
          "pr_auc_ci95_low": 0.8472195512820512,
          "pr_auc_ci95_high": 1.0,
          "brier": 0.5041177093588961,
          "ece_10bin_quantile": 0.6177131273443022
        }
      }
    },
    {
      "model": "ABUSE",
      "model_version": "abuse-hgb-fs1.0-446c817f",
      "pr_auc": 0.8143109485111188,
      "pr_auc_ci95": [
        0.7345974309302301,
        0.8871238792218589
      ],
      "brier": 0.019417668588235053,
      "ece_10bin_quantile": 0.010046908133942196,
      "calibration_curve": [
        {
          "bin_mean_predicted": 1.6595595151041618e-05,
          "observed_rate": 0.0,
          "count": 184
        },
        {
          "bin_mean_predicted": 2.7604591242582994e-05,
          "observed_rate": 0.0,
          "count": 184
        },
        {
          "bin_mean_predicted": 3.3598372850917464e-05,
          "observed_rate": 0.0,
          "count": 184
        },
        {
          "bin_mean_predicted": 4.724663421685778e-05,
          "observed_rate": 0.0,
          "count": 183
        },
        {
          "bin_mean_predicted": 8.987178439909442e-05,
          "observed_rate": 0.0,
          "count": 183
        },
        {
          "bin_mean_predicted": 0.00018113889821030934,
          "observed_rate": 0.0,
          "count": 183
        },
        {
          "bin_mean_predicted": 0.0003784176590508075,
          "observed_rate": 0.0,
          "count": 183
        },
        {
          "bin_mean_predicted": 0.0013652711939195596,
          "observed_rate": 0.00546448087431694,
          "count": 183
        },
        {
          "bin_mean_predicted": 0.012850655857371105,
          "observed_rate": 0.03278688524590164,
          "count": 183
        },
        {
          "bin_mean_predicted": 0.41597983166985936,
          "observed_rate": 0.4918032786885246,
          "count": 183
        }
      ],
      "by_value_band": {
        "<₹2k": {
          "n": 806.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 1.3984711504175795e-07,
          "ece_10bin_quantile": 0.0001255623941504931
        },
        ">₹10k": {
          "n": 324.0,
          "positives": 49.0,
          "prevalence": 0.15123456790123457,
          "pr_auc": 0.8900044493057152,
          "pr_auc_ci95_low": 0.8073852788884344,
          "pr_auc_ci95_high": 0.9574543619055285,
          "brier": 0.04174998368958225,
          "ece_10bin_quantile": 0.02258251926566448
        },
        "₹2–10k": {
          "n": 703.0,
          "positives": 48.0,
          "prevalence": 0.06827880512091039,
          "pr_auc": 0.7501632060352798,
          "pr_auc_ci95_low": 0.6236345532769564,
          "pr_auc_ci95_high": 0.8738020817857852,
          "brier": 0.03138759472266781,
          "ece_10bin_quantile": 0.017946265528597696
        }
      },
      "by_cohort": {
        "account_age=30–365 d": {
          "n": 546.0,
          "positives": 27.0,
          "prevalence": 0.04945054945054945,
          "pr_auc": 0.8941672839257165,
          "pr_auc_ci95_low": 0.7777698863558941,
          "pr_auc_ci95_high": 0.9689829067445325,
          "brier": 0.02064919176914747,
          "ece_10bin_quantile": 0.02240976180816171
        },
        "account_age=<30 d": {
          "n": 180.0,
          "positives": 44.0,
          "prevalence": 0.24444444444444444,
          "pr_auc": 0.8406550713813782,
          "pr_auc_ci95_low": 0.7205068755450209,
          "pr_auc_ci95_high": 0.9372989295229645,
          "brier": 0.08122929242247179,
          "ece_10bin_quantile": 0.04015596173018658
        },
        "account_age=>365 d": {
          "n": 1107.0,
          "positives": 26.0,
          "prevalence": 0.023486901535682024,
          "pr_auc": 0.7859727229451182,
          "pr_auc_ci95_low": 0.6206089743516024,
          "pr_auc_ci95_high": 0.9228899787539431,
          "brier": 0.008759580108613744,
          "ece_10bin_quantile": 0.0016270062445932964
        },
        "multi_tenant_address=no": {
          "n": 1776.0,
          "positives": 97.0,
          "prevalence": 0.054617117117117114,
          "pr_auc": 0.8148301388856942,
          "pr_auc_ci95_low": 0.7326928935223515,
          "pr_auc_ci95_high": 0.8858468875414521,
          "brier": 0.020037524641865284,
          "ece_10bin_quantile": 0.010468568200768443
        },
        "multi_tenant_address=yes": {
          "n": 57.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 0.00010425891722999258,
          "ece_10bin_quantile": 0.0031558053031548695
        },
        "payment=COD": {
          "n": 481.0,
          "positives": 20.0,
          "prevalence": 0.04158004158004158,
          "pr_auc": 0.809143583066733,
          "pr_auc_ci95_low": 0.6296650369467707,
          "pr_auc_ci95_high": 0.9494587607770382,
          "brier": 0.01455403294558635,
          "ece_10bin_quantile": 0.007253514718485895
        },
        "payment=PREPAID": {
          "n": 1352.0,
          "positives": 77.0,
          "prevalence": 0.05695266272189349,
          "pr_auc": 0.8179533967930466,
          "pr_auc_ci95_low": 0.7225430754083295,
          "pr_auc_ci95_high": 0.9022817210436943,
          "brier": 0.021148000499561996,
          "ece_10bin_quantile": 0.011140011721631213
        },
        "primary_category=ACCESSORIES": {
          "n": 184.0,
          "positives": 4.0,
          "prevalence": 0.021739130434782608,
          "pr_auc": 0.95,
          "pr_auc_ci95_low": 0.7333333333333334,
          "pr_auc_ci95_high": 1.0,
          "brier": 0.007114595202825027,
          "ece_10bin_quantile": 0.004820541265945709
        },
        "primary_category=APPAREL": {
          "n": 477.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 5.193575969602099e-08,
          "ece_10bin_quantile": 8.236664514843431e-05
        },
        "primary_category=BEAUTY": {
          "n": 201.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 1.5362583450624585e-08,
          "ece_10bin_quantile": 6.246201255625222e-05
        },
        "primary_category=ELECTRONICS": {
          "n": 444.0,
          "positives": 62.0,
          "prevalence": 0.13963963963963963,
          "pr_auc": 0.8614755186342842,
          "pr_auc_ci95_low": 0.774565451464349,
          "pr_auc_ci95_high": 0.9249811234460262,
          "brier": 0.048857162277664734,
          "ece_10bin_quantile": 0.03541087063785888
        },
        "primary_category=FOOTWEAR": {
          "n": 302.0,
          "positives": 31.0,
          "prevalence": 0.10264900662251655,
          "pr_auc": 0.7776995334619321,
          "pr_auc_ci95_low": 0.6176586246143916,
          "pr_auc_ci95_high": 0.9208828764765722,
          "brier": 0.04168363665764748,
          "ece_10bin_quantile": 0.021800519661550607
        },
        "primary_category=HOME": {
          "n": 225.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 1.0821430158748203e-05,
          "ece_10bin_quantile": 0.0005545819801928791
        },
        "archetype=FREQUENT_RETURNER": {
          "n": 247.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 7.233267109713462e-05,
          "ece_10bin_quantile": 0.0016023462563539994
        },
        "archetype=HOUSEHOLD": {
          "n": 88.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 0.005611625756327882,
          "ece_10bin_quantile": 0.01999082002483043
        },
        "archetype=NORMAL": {
          "n": 1196.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 0.000510673994865729,
          "ece_10bin_quantile": 0.005116127723951559
        },
        "archetype=OFFICE_HOSTEL_PG": {
          "n": 74.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 9.289273339151663e-05,
          "ece_10bin_quantile": 0.002915735531885224
        },
        "archetype=OPPORTUNISTIC": {
          "n": 18.0,
          "positives": 6.0,
          "prevalence": 0.3333333333333333,
          "pr_auc": 0.8541666666666667,
          "pr_auc_ci95_low": 0.5495604395604397,
          "pr_auc_ci95_high": 1.0,
          "brier": 0.16036448595593283,
          "ece_10bin_quantile": 0.24111426103166644
        },
        "archetype=REFURB_DEVICE": {
          "n": 55.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 0.0019291306970614457,
          "ece_10bin_quantile": 0.01113713430094984
        },
        "archetype=RING": {
          "n": 142.0,
          "positives": 91.0,
          "prevalence": 0.6408450704225352,
          "pr_auc": 0.8762976292231612,
          "pr_auc_ci95_low": 0.7961777717953504,
          "pr_auc_ci95_high": 0.9434708028286447,
          "brier": 0.22043192243715956,
          "ece_10bin_quantile": 0.20142754398928203
        },
        "archetype=UNCONFIRMED_ABUSER": {
          "n": 13.0,
          "positives": 0.0,
          "prevalence": 0.0,
          "brier": 0.013020092628060725,
          "ece_10bin_quantile": 0.066085504144452
        }
      }
    }
  ],
  "cold_start_ring_recall": 0.7272727272727273,
  "sensitivity": [
    {
      "group": "economics",
      "factor": 0.5,
      "fixed_threshold_tau_review": 0.05,
      "fixed_threshold_tau_block": 0.65,
      "SENTINEL_realized_cost_per_1000_inr": 183292.14,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 131651.75,
      "RULE_BASED_realized_cost_per_1000_inr": 699571.77,
      "ALLOW_ALL_realized_cost_per_1000_inr": 619322.04
    },
    {
      "group": "economics",
      "factor": 1.5,
      "fixed_threshold_tau_review": 0.15,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 200439.6,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 188667.71,
      "RULE_BASED_realized_cost_per_1000_inr": 785054.82,
      "ALLOW_ALL_realized_cost_per_1000_inr": 627259.85
    },
    {
      "group": "clv",
      "factor": 0.5,
      "fixed_threshold_tau_review": 0.05,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 195255.13,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 160054.69,
      "RULE_BASED_realized_cost_per_1000_inr": 739842.3,
      "ALLOW_ALL_realized_cost_per_1000_inr": 623290.95
    },
    {
      "group": "clv",
      "factor": 1.5,
      "fixed_threshold_tau_review": 0.05,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 199554.53,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 162852.3,
      "RULE_BASED_realized_cost_per_1000_inr": 745493.25,
      "ALLOW_ALL_realized_cost_per_1000_inr": 623290.95
    },
    {
      "group": "allow",
      "factor": 0.5,
      "fixed_threshold_tau_review": 0.05,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 207143.63,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 169292.98,
      "RULE_BASED_realized_cost_per_1000_inr": 779908.09,
      "ALLOW_ALL_realized_cost_per_1000_inr": 677586.81
    },
    {
      "group": "allow",
      "factor": 1.5,
      "fixed_threshold_tau_review": 0.15,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 184275.98,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 164923.14,
      "RULE_BASED_realized_cost_per_1000_inr": 704718.49,
      "ALLOW_ALL_realized_cost_per_1000_inr": 568995.08
    },
    {
      "group": "prepaid_only",
      "factor": 0.5,
      "fixed_threshold_tau_review": 0.05,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 198995.53,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 160112.09,
      "RULE_BASED_realized_cost_per_1000_inr": 750198.52,
      "ALLOW_ALL_realized_cost_per_1000_inr": 623290.95
    },
    {
      "group": "prepaid_only",
      "factor": 1.5,
      "fixed_threshold_tau_review": 0.05,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 171994.34,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 160112.09,
      "RULE_BASED_realized_cost_per_1000_inr": 743555.15,
      "ALLOW_ALL_realized_cost_per_1000_inr": 623290.95
    },
    {
      "group": "manual_review",
      "factor": 0.5,
      "fixed_threshold_tau_review": 0.05,
      "fixed_threshold_tau_block": 0.65,
      "SENTINEL_realized_cost_per_1000_inr": 276206.07,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 225631.95,
      "RULE_BASED_realized_cost_per_1000_inr": 782371.93,
      "ALLOW_ALL_realized_cost_per_1000_inr": 623290.95
    },
    {
      "group": "manual_review",
      "factor": 1.5,
      "fixed_threshold_tau_review": 0.15,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 115094.4,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 135031.32,
      "RULE_BASED_realized_cost_per_1000_inr": 723828.84,
      "ALLOW_ALL_realized_cost_per_1000_inr": 623290.95
    },
    {
      "group": "block",
      "factor": 0.5,
      "fixed_threshold_tau_review": 0.05,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 193600.68,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 155928.99,
      "RULE_BASED_realized_cost_per_1000_inr": 660873.91,
      "ALLOW_ALL_realized_cost_per_1000_inr": 623290.95
    },
    {
      "group": "block",
      "factor": 1.5,
      "fixed_threshold_tau_review": 0.15,
      "fixed_threshold_tau_block": 0.75,
      "SENTINEL_realized_cost_per_1000_inr": 196181.9,
      "FIXED_THRESHOLD_realized_cost_per_1000_inr": 180405.59,
      "RULE_BASED_realized_cost_per_1000_inr": 823752.67,
      "ALLOW_ALL_realized_cost_per_1000_inr": 623290.95
    }
  ],
  "drift_monitoring": "PLACEHOLDER_NOT_COMPUTED",
  "data_notice": "Synthetic data is used to validate the architecture, policy behaviour, auditability, and coordinated-pattern detection. Real deployment would require merchant-specific historical data and prospective validation."
}
```

## 8. Deviations added or updated

- **#32 added** (Part 1, 1.1): the two point-in-time columns; seed-time capture by one chronological replay; live
  capture from the frozen builder; the `features/` additions; every graph layout, id, label, state, discount and
  cap choice. Measured: 25 discounted links over the 250 seeded decisions (HOUSEHOLD_PATTERN 12,
  SEQUENTIAL_DEVICE_USE 7, MULTI_TENANT_ADDRESS 5, STALE_RELATIONSHIP 1); `MITIGATING_DISCOUNTED_LINKS` now fires on 23 of them; no seeded action changed.
- **#33 added** (Part 1, 1.4): demo reviewer clock.
- **#27 updated** (1.5): threadpoolctl declared. **#31 updated** (1.2 accepted with the reason, 1.3 → 404 with a neutral
  message, 1.4 superseded by #33, open question 1 closed by #32).
- **#34 added** (Part 2): every Phase 7 choice the brief leaves open. This includes **demo endpoints → 404, not §4's 409**
  (the brief amends it), presets served from a seed-time file because `data/demo_orders.py` reaches the generator,
  the queue's current-action semantics and graph-evidence partition, metrics on the recommended action, checkout from
  the current action, the probe-logging definitions, error bodies, and the test-isolation fix below.
- **#16 updated**: `openapi-typescript` 7.13.0 (approved).

**Worth your eye: an order-dependent test failure found at the gate.** The first full Part 2 run failed
`test_committed_artifacts_reproduce_on_the_same_cpu_count` (Phase 4), which passed alone. `tests/api` now runs before
`tests/model` and loads the committed bundles. Measured in a standalone script: training in a clean interpreter
reproduces both committed SHA-256s; training after `load_models()` in the same interpreter gives different SHA-256s
for both bundles, with **identical predictions on the full offline frame** (`np.array_equal`). So the model does not
change, only the pickle bytes, and those depend on what the process loaded earlier. The OpenMP thread count (8) and
the `world` fixture were checked and ruled out. Fix: the test trains in a fresh subprocess, as `cli train` does, and asserts the same
SHA-256 equality. No comparison or bound was loosened. It passes in the failing order (68 passed) and in the full suite.

## 9. Open questions

1. **Ego graph vs `linked_orders_24h`.** Demo 2's graph shows 3 of the 4 linked orders, because the brief's ego graph
   stops at directly linked accounts and the fourth order comes from a two-hop member. If the Phase 8 panel prints
   "4 linked orders" next to a graph showing 3, a judge may notice. Two small options: (a) include reliable-component
   members up to two hops, which Demo 2 would still fit under the 40-node cap; (b) keep the ego graph and have the UI caption say
   "directly linked". I did neither. Your call.
2. **Probe logging on malformed requests.** Rows are written only for calls that pass validation, because a malformed
   device id may be raw PII. A prober sending garbage is therefore not counted. Acceptable for the prototype?
3. **Queue `action` filter** uses the *current* action (what is in effect after overrides), and metrics'
   `action_distribution` uses the *recommended* action (system activity). Both are recorded in #34. Say if you want
   them aligned the other way.
4. **Customer-summary cost.** The detail route rebuilds one account's history per request (a few ms). It is fine at
   demo scale, and noted in case Phase 8 polls the detail page.

## 10. Gate

The full suite is green (820 passed, slow included) and `npm run build` passes, both before the Part 2 commit. `git status -sb` and
`git log --oneline -5` immediately after the Part 2 commit, and its hash, are recorded by the follow-up docs commit,
never by amending.

Part 2 committed as `d76f2c1` and pushed. State immediately after that commit:

```
## main...origin/main
```
```
d76f2c1 phase 7: api
3dfbf20 phase 6: follow-ups
e4a47e5 docs: record the actual phase 6 commit hash in the report and progress log
d4881da phase 6: db, audit and scoring service
7fb75f0 phase 5: follow-ups
```
