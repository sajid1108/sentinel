# Phase 6 — DB, audit and scoring service: gate report

*Spec phase 6 (`docs/ARCHITECTURE.md` §12); `october_master_architecture.md` calls it stage 7. Brief:
`docs/briefs/phase-6-db-audit-scoring.md` (Part 1 = Phase 5 follow-ups, Part 2 = Phase 6).*

```
PROGRESS  phase 6 of 12  [######----]  7/11 stages to Definition of Done (64%)
          this phase: gate — 8 of 8 sections done  |  elapsed 0h37m
```

Both commits green on the full suite (slow included), pushed. Phase 7 not started.

| Commit | What |
|---|---|
| `7fb75f0` | `phase 5: follow-ups` (Part 1) |
| `see §10` | `phase 6: db, audit and scoring service` (Part 2) |

---

## 1. Files changed

**Part 1 — `7fb75f0`**

| File | Change |
|---|---|
| `backend/sentinel/features/graph_state.py` | `AccountState.confirmation_times` (every ABUSE_CONFIRMED, so "most recent" is the latest, not the first) |
| `backend/sentinel/features/graph_features.py` | evidence-only `device_confirmed_peer_count`, `device_most_recent_confirmation_days` (1.6) |
| `backend/sentinel/features/builder.py` | `EVIDENCE_COLUMNS`, `evidence_values()`; the two columns appended to `policy_inputs.parquet` |
| `backend/sentinel/models/explain.py` | evidence-strength ordering, `attributions_by_magnitude`, matured-count parameters (1.1, 1.4) |
| `backend/sentinel/models/reason_codes.py` | count-aware `fill()` with `{n:singular\|plural}`; raw matured counts; whole-day confirmation age (1.3, 1.4, 1.6) |
| `backend/sentinel/models/attribution.py` | ablation batch scored on one OpenMP thread (1.5) |
| `backend/sentinel/config/reason_codes.toml` | every count template pluralised; TEMPORAL_BURST wording; RETURN_HIGH_HISTORY counts; `rc-1.1` |
| `backend/tests/unit/test_reason_codes.py`, `test_attribution.py` | ordering, plurals, counts, fallback, p95 |
| `backend/tests/scenarios/test_demo_explanations.py` | exact demo sentences, ordering, attribution view, text safety |
| `backend/tests/leakage/test_point_in_time.py` | evidence values: counts, latest age, P3/P4, offline = serving, not features |
| `backend/tests/model/test_models.py` | policy-inputs column list includes the evidence columns |
| `docs/DEVIATIONS.md` | #27 and #28 updated; #28 TODO closed |
| `docs/briefs/phase-6-db-audit-scoring.md` | brief tracked |

**Part 2 — `see §10`**

| File | Change |
|---|---|
| `backend/sentinel/audit/schemas.py` | **new** — §10.1 payload with #14's optional scores |
| `backend/sentinel/audit/chain.py` | **new** — canonical JSON, rounding before hashing, SHA-256 chain, `verify` |
| `backend/sentinel/audit/service.py` | **new** — `append_event` (inside BEGIN IMMEDIATE), `verify_chain`, readers |
| `backend/sentinel/api/services/scoring.py` | **new** — `ScoringService`, shared assessment core, idempotency, degraded mode |
| `backend/sentinel/api/services/review.py` | **new** — `ReviewService.apply_override`, `open_appeal` |
| `backend/sentinel/api/services/errors.py`, `__init__.py` | **new** — `RequestRejected` / `Conflict` / `NotFound` |
| `backend/sentinel/db/seed.py` | **new** — `seed_database`, `reset_demo` |
| `backend/sentinel/db/models.py` | `immediate_transaction`, `read_connection`, `utc_iso`, `parse_utc`, `busy_timeout` |
| `backend/sentinel/models/explain.py` | `feature_attributions_pp` for the audit record |
| `backend/sentinel/cli.py` | `seed-db`, `reset-demo` implemented |
| `backend/tests/unit/test_chain.py` | **new** — 13 tests |
| `backend/tests/unit/test_services_purity.py` | **new** — 6 tests |
| `backend/tests/unit/test_db.py` | +3 tests (fresh DB tables/triggers, rollback, append outside a transaction) |
| `backend/tests/scenarios/test_db_audit_scoring.py` | **new** — 40 tests (slow) |
| `docs/DEVIATIONS.md` | #30, #31 added |
| `docs/PROGRESS.md`, `docs/reports/phase-6.md`, `README.md` | progress row, this report, build status |

`schema.sql` was not changed: #14's nullable `p_return`, `p_abuse`, `cost_optimal_action` and the degraded-mode CHECK
were already applied (verified against #14). No model artifact, no generator code and no policy code changed.
`features.parquet` and every pre-existing `policy_inputs.parquet` column are byte-identical after the rebuild.

## 2. Test results and timings

| Run | Result | Time |
|---|---|---|
| Baseline `-m "not slow"` (session start) | 493 passed, **1 failed** (`test_attribution_latency_budget`, intermittent) | 31.7 s |
| Part 1 gate, full suite incl. slow | **678 passed** | 2 m 45 s |
| Part 2 new scenario file alone | 40 passed | 42.5 s |
| **Part 2 gate, full suite incl. slow** | **740 passed** | **3 m 34 s** |

644 (Phase 5) → 678 (Part 1) → 740 (Part 2).

| Measurement | Value |
|---|---|
| `seed-db` | **6.7–6.9 s** in-process (9.9 s wall with interpreter start); budget 30 s |
| `ScoringService.start` (load, verify, replay from DB) | **1.02–1.18 s** (3 cold starts) |
| `score()` per demo order, warm | median **18.9 ms**, p95 **23.0 ms** over 96 new orders, both DB transactions included; the first call after startup ~100 ms once |
| Attribution latency (both models + group), 60 warmed calls ×4 rounds | median **12.4–14.4 ms** (< 20), **p95 15.4–18.8 ms** (< 40) |

**Latency, worth your eye.** The baseline failure was real drift, not a flaky test: at session start the median sat
at 18.4–20.2 ms, straddling the 20 ms budget, with the machine ~34 % busy with other work. I did not move the bound.
The ~20-row ablation batch was being fanned out over all 8 OpenMP threads, which costs more than the trees on a batch
that small. Scoring it on one thread (`threadpoolctl`, already installed and pinned in `requirements.lock` as a
scikit-learn dependency; nothing added) took the median from 18.6 to 12.4–14.4 ms and p95 from 24.7 to 15.4–18.8 ms (7 rounds, two sessions).
Predictions are unchanged (the baseline row still equals `train.predict` to 1e-12, and the demo p_abuse values
below are identical to Phase 5's to the last printed digit).

## 3. Re-rendered Part 1 text — all three demos

Committed artifacts, real FeatureBuilder, evidence values supplied as the scoring service supplies them. Scores are
unchanged from Phase 5. `reasons` are now in evidence order; `attributions_by_magnitude` is the model-attribution view.

### Demo 1 — `ORD-DEMO-001` · p_return 0.6154 · p_abuse 0.0000 · matured history 28 of 48

> No material abuse evidence was found; the score reflects this account's own history rather than links to other accounts.

| Code | Model | Strength | attribution_pp | Text |
|---|---|---|---|---|
| `RETURN_SIZE_BRACKETING` | RETURN | MODERATE | 31.5385 | "Multiple sizes of the same item in the cart." |
| `RETURN_HIGH_HISTORY` | RETURN | MODERATE | 18.6813 | "The customer returned 28 of 48 delivered orders. This affects return likelihood, not abuse risk." |

Mitigating: `MITIGATING_ESTABLISHED_ACCOUNT` "Long-standing account with no flagged claims." (−0.0083);
`MITIGATING_DISCOUNTED_LINKS` "Shared address discounted: household pattern." (no attribution).

1.4: was "The customer returns often (52%)" from the smoothed rate; the actual matured history is 28 of 48 = 58 %
(§11 says 0.58).

### Demo 2 — `ORD-DEMO-002` · p_abuse 0.9507 · without graph evidence 0.0993

> The abuse score is driven mainly by links to other accounts sharing this order's device, payment method or delivery pattern.

| # | Code | Strength | attribution_pp | Text | Note |
|---|---|---|---|---|---|
| 1 | `GRAPH_TOKEN_REUSE` | STRONG | 0.1802 | "The payment method was used by 3 other accounts in the last 30 days." | redundant |
| 2 | `GRAPH_DEVICE_CONFIRMED_LINK` | STRONG | 0.0 | "This device was used by 3 accounts later confirmed for return abuse, most recently 3 days ago." | redundant |
| 3 | `TEMPORAL_BURST` | MODERATE | 4.5465 | "Linked accounts placed 4 orders in the last 24 hours." | |
| 4 | `SAME_SKU_COORDINATION` | MODERATE | 3.7985 | "Linked accounts ordered the same item 3 times this week." | |
| 5 | `GRAPH_DEVICE_SHARED` | MODERATE | 3.5849 | "This device was used by 5 other accounts in the last 30 days." | |
| 6 | `NEW_ACCOUNT_HIGH_VALUE` | WEAK | 94.2864 | "New account placing a high-value order." | |

`attributions_by_magnitude`: NEW_ACCOUNT_HIGH_VALUE, TEMPORAL_BURST, SAME_SKU_COORDINATION, GRAPH_DEVICE_SHARED,
GRAPH_TOKEN_REUSE, GRAPH_DEVICE_CONFIRMED_LINK. Mitigating: none.

1.1: the top line was the WEAK new-account code; it is now STRONG token and device evidence. 1.2: was "4 linked accounts
placed orders". 1.6: the device sentence now has real values: 3 confirmed peers, the latest confirmation 3.75 days
before t0, rendered as whole days elapsed ("3 days ago", never rounded up to a day not yet reached).

### Demo 3 — `ORD-DEMO-003` · p_abuse 0.6913 · without graph evidence 0.0008

> The abuse score is driven mainly by links to other accounts sharing this order's device, payment method or delivery pattern.

| Code | Strength | attribution_pp | Text | Note |
|---|---|---|---|---|
| `GRAPH_DEVICE_SHARED` | MODERATE | 39.0493 | "This device was used by 3 other accounts in the last 30 days." | |
| `ACCOUNT_PRIOR_SUSPICIOUS_CLAIM` | MODERATE | 0.0 | "The account had 1 flagged return or delivery claim in the last 6 months." | redundant |

Mitigating: `MITIGATING_DISCOUNTED_LINKS` "Shared address discounted: stale relationship."

1.3: was "The account had 1 return or delivery claim(s) flagged in the last 6 months."

## 4. Seeded decisions

`python -m sentinel.cli seed-db`, as-of-`DEMO_CLOCK` world: accounts 2,942, identifiers 9,805, orders 10,152,
order_lines 13,588, order_events **17,130** (17,709 in the full log; the 579 at or after `DEMO_CLOCK` dropped).

| | Count |
|---|---|
| TEST orders considered | 1,878 |
| SENTINEL non-ALLOW (all included) | **160** |
| ALLOW drawn to fill (seed 20260901) | **90** |
| **Total** | **250** |

| By action | | By source | |
|---|---|---|---|
| ALLOW | 90 | BACKTEST_REPLAY | 250 |
| PREPAID_ONLY | 15 | DEMO | 0 (demo requests arrive through scoring) |
| MANUAL_REVIEW | 126 | LIVE | 0 |
| BLOCK | 19 | | |

Non-ALLOW did not exceed 250, so the descending-p_abuse cut was not needed. Every seeded action equals the backtest's
SENTINEL action for that order (test builds the backtest rows independently, as `evaluation/report.py` does). Two
seeds give identical `decisions` and `audit_events` tables, every `event_hash` included.

## 5. The three demo `ScoreOrderResponse`s

Scored through `ScoringService.score(request, "DEMO")` on a freshly seeded database. `decision_id` and
`audit_event_id` are uuid4 for live decisions and differ run to run; everything else is deterministic.

```json
{
  "ORD-DEMO-001": {
    "decision_id": "37efffe0-7cd8-4228-8f49-cf515f83f690",
    "order_id": "ORD-DEMO-001",
    "scored_at": "2026-09-01T05:00:00Z",
    "features_as_of": "2026-09-01T04:55:00Z",
    "scores": {
      "p_return": 0.6153846153846154,
      "p_abuse": 4.407411157210499e-05,
      "p_abuse_without_graph_evidence": 4.407411157210499e-05,
      "return_model_version": "return-hgb-fs1.0-e3c877bc",
      "abuse_model_version": "abuse-hgb-fs1.0-446c817f",
      "feature_set_version": "fs-1.0-0ad43d7f",
      "p_return_used_for_action": false
    },
    "prediction_explanation": "No material abuse evidence was found; the score reflects this account's own history rather than links to other accounts.",
    "reasons": [
      {
        "code": "RETURN_SIZE_BRACKETING",
        "model": "RETURN",
        "direction": "INCREASES",
        "reviewer_text": "Multiple sizes of the same item in the cart.",
        "evidence": {
          "variants": 3
        },
        "attribution_pp": 31.5385,
        "evidence_strength": "MODERATE",
        "attribution_note": null
      },
      {
        "code": "RETURN_HIGH_HISTORY",
        "model": "RETURN",
        "direction": "INCREASES",
        "reviewer_text": "The customer returned 28 of 48 delivered orders. This affects return likelihood, not abuse risk.",
        "evidence": {
          "matured_orders": 48,
          "returns": 28
        },
        "attribution_pp": 18.6813,
        "evidence_strength": "MODERATE",
        "attribution_note": null
      },
      {
        "code": "MITIGATING_ESTABLISHED_ACCOUNT",
        "model": "ABUSE",
        "direction": "DECREASES",
        "reviewer_text": "Long-standing account with no flagged claims.",
        "evidence": {
          "account_age_days": 1280.0,
          "prior_orders": 52
        },
        "attribution_pp": -0.0083,
        "evidence_strength": "MODERATE",
        "attribution_note": "Redundant with other relationship evidence; the score is already explained by correlated features."
      },
      {
        "code": "MITIGATING_DISCOUNTED_LINKS",
        "model": "ABUSE",
        "direction": "DECREASES",
        "reviewer_text": "Shared address discounted: household pattern.",
        "evidence": {
          "kind": "address",
          "reason": "household pattern"
        },
        "attribution_pp": null,
        "evidence_strength": "WEAK",
        "attribution_note": null
      }
    ],
    "graph_summary": {
      "component_size_reliable_90d": 1,
      "confirmed_abusive_accounts_in_component": 0,
      "min_hops_to_confirmed_abuse": null,
      "linked_orders_24h": 0,
      "corroborating_signal_count": 0,
      "signals": [
        {
          "signal": "DEVICE",
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "Device: confirmed-abuse weight 0.00, 0 other concurrent accounts in 30 d."
        },
        {
          "signal": "PAYMENT_TOKEN",
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "Payment token used by 0 other accounts in 30 d."
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
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "0 linked orders in 24 h, 0 same-SKU linked orders in 7 d, via device or token links."
        },
        {
          "signal": "ACCOUNT_CLAIMS",
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "0 suspicious claim(s) on this account in 180 d."
        }
      ],
      "discounted_links": [
        {
          "identifier_label": "Address ••3486",
          "kind": "ADDRESS",
          "reason": "HOUSEHOLD_PATTERN",
          "weight": 0.1299
        }
      ],
      "weak_evidence_only": false
    },
    "policy": {
      "policy_version": "v1.0",
      "policy_config_sha256": "e1744f126c99d32123f31768538768841b188f7ed7ac7509c406760f313915f0",
      "cost_optimal_action": "ALLOW",
      "selected_action": "ALLOW",
      "selected_rule": "MIN_EXPECTED_COST",
      "costs": [
        {
          "action": "ALLOW",
          "expected_cost": {
            "inr": 0.18,
            "display": "₹0"
          },
          "abusive_branch": {
            "inr": 0.18,
            "display": "₹0"
          },
          "genuine_branch": {
            "inr": 0.0,
            "display": "₹0"
          },
          "operational": {
            "inr": 0.0,
            "display": "₹0"
          },
          "feasible": true,
          "excluded_by": [],
          "rank_by_cost": 1
        },
        {
          "action": "PREPAID_ONLY",
          "expected_cost": {
            "inr": 750.36,
            "display": "₹750"
          },
          "abusive_branch": {
            "inr": 0.07,
            "display": "₹0"
          },
          "genuine_branch": {
            "inr": 750.28,
            "display": "₹750"
          },
          "operational": {
            "inr": 0.0,
            "display": "₹0"
          },
          "feasible": true,
          "excluded_by": [],
          "rank_by_cost": 2
        },
        {
          "action": "MANUAL_REVIEW",
          "expected_cost": {
            "inr": 912.09,
            "display": "₹912"
          },
          "abusive_branch": {
            "inr": 0.04,
            "display": "₹0"
          },
          "genuine_branch": {
            "inr": 662.06,
            "display": "₹662"
          },
          "operational": {
            "inr": 250.0,
            "display": "₹250"
          },
          "feasible": true,
          "excluded_by": [],
          "rank_by_cost": 3
        },
        {
          "action": "BLOCK",
          "expected_cost": {
            "inr": 19818.63,
            "display": "₹19,819"
          },
          "abusive_branch": {
            "inr": 0.0,
            "display": "₹0"
          },
          "genuine_branch": {
            "inr": 19818.63,
            "display": "₹19,819"
          },
          "operational": {
            "inr": 0.0,
            "display": "₹0"
          },
          "feasible": false,
          "excluded_by": [
            "G2",
            "G3"
          ],
          "rank_by_cost": 4
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
          "triggered": true,
          "effect": "REMOVED_ACTIONS",
          "removed_actions": [
            "BLOCK"
          ],
          "detail": "G2 requires two corroborating signals; none was found."
        },
        {
          "guardrail_id": "G3",
          "name": "BLOCK needs confidence",
          "triggered": true,
          "effect": "REMOVED_ACTIONS",
          "removed_actions": [
            "BLOCK"
          ],
          "detail": "G3 requires p_abuse of at least 0.70; this order scored 0.000."
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
          "triggered": false,
          "effect": "NONE",
          "removed_actions": [],
          "detail": "Exposure is below the G5 backstop."
        }
      ],
      "policy_explanation": "ALLOW was selected because its expected cost (₹0) is lower than PREPAID_ONLY (₹750), MANUAL_REVIEW (₹912) and BLOCK (₹19,819) under policy v1.0. BLOCK was also not permitted: G2 requires two corroborating signals; none was found. G3 requires p_abuse of at least 0.70; this order scored 0.000.",
      "assumptions_notice": "Monetary values are demonstration assumptions (policy v1.0)."
    },
    "status": "AUTO_APPLIED",
    "audit_event_id": "b1c31f54-6d3e-4aca-acf4-fc6575000dbd",
    "degraded_mode": false,
    "idempotent_replay": false
  },
  "ORD-DEMO-002": {
    "decision_id": "9df08408-8bad-4e16-af41-282d203dd760",
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
    "audit_event_id": "cbf425fc-e08f-4147-93ca-66a6e7b1f79c",
    "degraded_mode": false,
    "idempotent_replay": false
  },
  "ORD-DEMO-003": {
    "decision_id": "fe499f4e-b498-4763-9a13-b01678d9a385",
    "order_id": "ORD-DEMO-003",
    "scored_at": "2026-09-01T05:00:00Z",
    "features_as_of": "2026-09-01T04:55:00Z",
    "scores": {
      "p_return": 0.2457627118644068,
      "p_abuse": 0.6913106294322455,
      "p_abuse_without_graph_evidence": 0.0007559512270589128,
      "return_model_version": "return-hgb-fs1.0-e3c877bc",
      "abuse_model_version": "abuse-hgb-fs1.0-446c817f",
      "feature_set_version": "fs-1.0-0ad43d7f",
      "p_return_used_for_action": false
    },
    "prediction_explanation": "The abuse score is driven mainly by links to other accounts sharing this order's device, payment method or delivery pattern.",
    "reasons": [
      {
        "code": "GRAPH_DEVICE_SHARED",
        "model": "ABUSE",
        "direction": "INCREASES",
        "reviewer_text": "This device was used by 3 other accounts in the last 30 days.",
        "evidence": {
          "other_accounts_30d": 3
        },
        "attribution_pp": 39.0493,
        "evidence_strength": "MODERATE",
        "attribution_note": null
      },
      {
        "code": "ACCOUNT_PRIOR_SUSPICIOUS_CLAIM",
        "model": "ABUSE",
        "direction": "INCREASES",
        "reviewer_text": "The account had 1 flagged return or delivery claim in the last 6 months.",
        "evidence": {
          "flagged_claims_180d": 1
        },
        "attribution_pp": 0.0,
        "evidence_strength": "MODERATE",
        "attribution_note": "Redundant with other relationship evidence; the score is already explained by correlated features."
      },
      {
        "code": "MITIGATING_DISCOUNTED_LINKS",
        "model": "ABUSE",
        "direction": "DECREASES",
        "reviewer_text": "Shared address discounted: stale relationship.",
        "evidence": {
          "kind": "address",
          "reason": "stale relationship"
        },
        "attribution_pp": null,
        "evidence_strength": "WEAK",
        "attribution_note": null
      }
    ],
    "graph_summary": {
      "component_size_reliable_90d": 4,
      "confirmed_abusive_accounts_in_component": 0,
      "min_hops_to_confirmed_abuse": null,
      "linked_orders_24h": 1,
      "corroborating_signal_count": 2,
      "signals": [
        {
          "signal": "DEVICE",
          "present": true,
          "weight": 0.7895433712688465,
          "counts_for_corroboration": true,
          "detail": "Device: confirmed-abuse weight 0.00, 3 other concurrent accounts in 30 d."
        },
        {
          "signal": "PAYMENT_TOKEN",
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "Payment token used by 0 other accounts in 30 d."
        },
        {
          "signal": "ADDRESS",
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "Confirmed-abuse weight 0.04 on this address (needs 0.30)."
        },
        {
          "signal": "TEMPORAL_BURST",
          "present": false,
          "weight": 0.0,
          "counts_for_corroboration": false,
          "detail": "1 linked orders in 24 h, 0 same-SKU linked orders in 7 d, via device or token links."
        },
        {
          "signal": "ACCOUNT_CLAIMS",
          "present": true,
          "weight": 1.0,
          "counts_for_corroboration": true,
          "detail": "1 suspicious claim(s) on this account in 180 d."
        }
      ],
      "discounted_links": [
        {
          "identifier_label": "Address ••d05f",
          "kind": "ADDRESS",
          "reason": "STALE_RELATIONSHIP",
          "weight": 0.0397
        }
      ],
      "weak_evidence_only": false
    },
    "policy": {
      "policy_version": "v1.0",
      "policy_config_sha256": "e1744f126c99d32123f31768538768841b188f7ed7ac7509c406760f313915f0",
      "cost_optimal_action": "MANUAL_REVIEW",
      "selected_action": "MANUAL_REVIEW",
      "selected_rule": "MIN_EXPECTED_COST",
      "costs": [
        {
          "action": "ALLOW",
          "expected_cost": {
            "inr": 7155.07,
            "display": "₹7,155"
          },
          "abusive_branch": {
            "inr": 7155.07,
            "display": "₹7,155"
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
            "inr": 3171.25,
            "display": "₹3,171"
          },
          "abusive_branch": {
            "inr": 2976.09,
            "display": "₹2,976"
          },
          "genuine_branch": {
            "inr": 195.16,
            "display": "₹195"
          },
          "operational": {
            "inr": 0.0,
            "display": "₹0"
          },
          "feasible": true,
          "excluded_by": [],
          "rank_by_cost": 2
        },
        {
          "action": "MANUAL_REVIEW",
          "expected_cost": {
            "inr": 1858.14,
            "display": "₹1,858"
          },
          "abusive_branch": {
            "inr": 1431.01,
            "display": "₹1,431"
          },
          "genuine_branch": {
            "inr": 177.12,
            "display": "₹177"
          },
          "operational": {
            "inr": 250.0,
            "display": "₹250"
          },
          "feasible": true,
          "excluded_by": [],
          "rank_by_cost": 1
        },
        {
          "action": "BLOCK",
          "expected_cost": {
            "inr": 4051.94,
            "display": "₹4,052"
          },
          "abusive_branch": {
            "inr": 0.0,
            "display": "₹0"
          },
          "genuine_branch": {
            "inr": 4051.94,
            "display": "₹4,052"
          },
          "operational": {
            "inr": 0.0,
            "display": "₹0"
          },
          "feasible": false,
          "excluded_by": [
            "G3"
          ],
          "rank_by_cost": 3
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
          "detail": "Two corroborating signals: DEVICE, ACCOUNT_CLAIMS."
        },
        {
          "guardrail_id": "G3",
          "name": "BLOCK needs confidence",
          "triggered": true,
          "effect": "REMOVED_ACTIONS",
          "removed_actions": [
            "BLOCK"
          ],
          "detail": "G3 requires p_abuse of at least 0.70; this order scored 0.691."
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
      "policy_explanation": "MANUAL_REVIEW was selected because its expected cost (₹1,858) is lower than PREPAID_ONLY (₹3,171), BLOCK (₹4,052) and ALLOW (₹7,155) under policy v1.0. BLOCK was also not permitted: G3 requires p_abuse of at least 0.70; this order scored 0.691. ALLOW was also not permitted: G5 removes ALLOW when p_abuse is at least 0.40 and the order value is at least ₹10,000.",
      "assumptions_notice": "Monetary values are demonstration assumptions (policy v1.0)."
    },
    "status": "PENDING_REVIEW",
    "audit_event_id": "b018b8d7-6134-4a09-a645-3875324226a3",
    "degraded_mode": false,
    "idempotent_replay": false
  }
}
```

## 6. One `OVERRIDE_APPLIED` audit payload

Demo 3, MANUAL_REVIEW → PREPAID_ONLY, `CUSTOMER_VERIFIED` (the §11 live step), with the reviewer clock fixed at
2026-09-01T05:12:40Z as in §10.3's example. Canonical form, keys sorted, exactly as stored and hashed.

```json
{
  "actor": {
    "id": "reviewer-placeholder-01",
    "type": "REVIEWER"
  },
  "appeal": null,
  "audit_event_id": "e6d6d56e-1cba-4adf-8324-a263083dc06b",
  "candidate_actions": [
    {
      "abusive_branch": {
        "display": "₹7,155",
        "inr": 7155.07
      },
      "action": "ALLOW",
      "excluded_by": [
        "G5"
      ],
      "expected_cost": {
        "display": "₹7,155",
        "inr": 7155.07
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
        "display": "₹2,976",
        "inr": 2976.09
      },
      "action": "PREPAID_ONLY",
      "excluded_by": [],
      "expected_cost": {
        "display": "₹3,171",
        "inr": 3171.25
      },
      "feasible": true,
      "genuine_branch": {
        "display": "₹195",
        "inr": 195.16
      },
      "operational": {
        "display": "₹0",
        "inr": 0.0
      },
      "rank_by_cost": 2
    },
    {
      "abusive_branch": {
        "display": "₹1,431",
        "inr": 1431.01
      },
      "action": "MANUAL_REVIEW",
      "excluded_by": [],
      "expected_cost": {
        "display": "₹1,858",
        "inr": 1858.14
      },
      "feasible": true,
      "genuine_branch": {
        "display": "₹177",
        "inr": 177.12
      },
      "operational": {
        "display": "₹250",
        "inr": 250.0
      },
      "rank_by_cost": 1
    },
    {
      "abusive_branch": {
        "display": "₹0",
        "inr": 0.0
      },
      "action": "BLOCK",
      "excluded_by": [
        "G3"
      ],
      "expected_cost": {
        "display": "₹4,052",
        "inr": 4051.94
      },
      "feasible": false,
      "genuine_branch": {
        "display": "₹4,052",
        "inr": 4051.94
      },
      "operational": {
        "display": "₹0",
        "inr": 0.0
      },
      "rank_by_cost": 3
    }
  ],
  "cost_optimal_action": "MANUAL_REVIEW",
  "decision_id": "fe499f4e-b498-4763-9a13-b01678d9a385",
  "degraded_mode": false,
  "event_type": "OVERRIDE_APPLIED",
  "feature_attributions_pp": {
    "account_age_days": -16.6195,
    "address_other_accounts_weighted_30d": 0.0,
    "component_abuse_ratio_smoothed": -5.6744,
    "component_recent_claims_30d": 0.0,
    "component_size_reliable_90d": 63.1376,
    "confirmed_abuse_proximity": 0.0,
    "device_confirmed_abuse_weight": 0.0,
    "device_other_accounts_30d": 39.0493,
    "identifier_reuse_velocity_7d": 23.5292,
    "linked_orders_24h": 32.9329,
    "linked_same_sku_7d": 0.0,
    "new_device_for_account": 0.0,
    "order_value_inr": 69.0556,
    "primary_category": 32.0882,
    "prior_orders": -3.5607,
    "prior_suspicious_claims_180d": 0.0,
    "token_other_accounts_30d": 0.0
  },
  "features_as_of": "2026-09-01T10:25:00+05:30",
  "graph_summary": {
    "component_size_reliable_90d": 4,
    "confirmed_abusive_accounts_in_component": 0,
    "corroborating_signal_count": 2,
    "discounted_links": [
      {
        "identifier_label": "Address ••d05f",
        "kind": "ADDRESS",
        "reason": "STALE_RELATIONSHIP",
        "weight": 0.0397
      }
    ],
    "linked_orders_24h": 1,
    "min_hops_to_confirmed_abuse": null,
    "signals": [
      {
        "counts_for_corroboration": true,
        "detail": "Device: confirmed-abuse weight 0.00, 3 other concurrent accounts in 30 d.",
        "present": true,
        "signal": "DEVICE",
        "weight": 0.789543
      },
      {
        "counts_for_corroboration": false,
        "detail": "Payment token used by 0 other accounts in 30 d.",
        "present": false,
        "signal": "PAYMENT_TOKEN",
        "weight": 0.0
      },
      {
        "counts_for_corroboration": false,
        "detail": "Confirmed-abuse weight 0.04 on this address (needs 0.30).",
        "present": false,
        "signal": "ADDRESS",
        "weight": 0.0
      },
      {
        "counts_for_corroboration": false,
        "detail": "1 linked orders in 24 h, 0 same-SKU linked orders in 7 d, via device or token links.",
        "present": false,
        "signal": "TEMPORAL_BURST",
        "weight": 0.0
      },
      {
        "counts_for_corroboration": true,
        "detail": "1 suspicious claim(s) on this account in 180 d.",
        "present": true,
        "signal": "ACCOUNT_CLAIMS",
        "weight": 1.0
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
      "detail": "Two corroborating signals: DEVICE, ACCOUNT_CLAIMS.",
      "effect": "NONE",
      "guardrail_id": "G2",
      "name": "BLOCK needs corroboration",
      "removed_actions": [],
      "triggered": false
    },
    {
      "detail": "G3 requires p_abuse of at least 0.70; this order scored 0.691.",
      "effect": "REMOVED_ACTIONS",
      "guardrail_id": "G3",
      "name": "BLOCK needs confidence",
      "removed_actions": [
        "BLOCK"
      ],
      "triggered": true
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
  "new_action": "PREPAID_ONLY",
  "occurred_at": "2026-09-01T05:12:40Z",
  "order_id": "ORD-DEMO-003",
  "original_recommendation": "MANUAL_REVIEW",
  "override": {
    "guardrail_conflicts": [],
    "reason_category": "CUSTOMER_VERIFIED",
    "reason_text": "Customer confirmed prior claim was a courier error; offering prepaid with inspection.",
    "reviewed_at": "2026-09-01T05:12:40Z",
    "reviewer_id": "reviewer-placeholder-01"
  },
  "p_abuse": 0.691311,
  "p_abuse_without_graph_evidence": 0.000756,
  "p_return": 0.245763,
  "policy_config_sha256": "e1744f126c99d32123f31768538768841b188f7ed7ac7509c406760f313915f0",
  "policy_explanation": "MANUAL_REVIEW was selected because its expected cost (₹1,858) is lower than PREPAID_ONLY (₹3,171), BLOCK (₹4,052) and ALLOW (₹7,155) under policy v1.0. BLOCK was also not permitted: G3 requires p_abuse of at least 0.70; this order scored 0.691. ALLOW was also not permitted: G5 removes ALLOW when p_abuse is at least 0.40 and the order value is at least ₹10,000.",
  "policy_rule": "MIN_EXPECTED_COST",
  "policy_version": "v1.0",
  "prediction_explanation": "The abuse score is driven mainly by links to other accounts sharing this order's device, payment method or delivery pattern.",
  "previous_action": "MANUAL_REVIEW",
  "reason_codes": [
    "GRAPH_DEVICE_SHARED",
    "ACCOUNT_PRIOR_SUSPICIOUS_CLAIM",
    "MITIGATING_DISCOUNTED_LINKS"
  ],
  "schema_version": "audit-1.0",
  "selected_action": "MANUAL_REVIEW"
}
```

## 7. `verify_chain()`

| Database | Output |
|---|---|
| Freshly seeded | `ChainVerification(valid=True, events_checked=250, first_broken_seq=None)` |
| + three demo decisions + the override above | `ChainVerification(valid=True, events_checked=254, first_broken_seq=None)` |
| Test: trigger dropped, payload at seq 117 edited | `(False, 117, 117)` |

## 8. Deviations added or updated

- **#27 updated** (Part 1): evidence-strength ordering and `attributions_by_magnitude` (1.1); the architect's
  `TEMPORAL_BURST` wording (1.2); count-aware templates (1.3); raw matured counts for return history, with the
  counts-free fallback and how seeding recovers the count (1.4); median + p95 latency and the single-thread fix (1.5);
  catalog `rc-1.1`.
- **#28 updated and its TODO closed** (Part 1, 1.6): the two evidence-only builder values, where they live
  (`evidence_values()`, `EVIDENCE_COLUMNS` in `policy_inputs.parquet`), point-in-time behaviour, whole-day rendering.
- **#30 added**: frozen scoring history, the architect's P14 amendment, with the order-independence measurement.
- **#31 added**: every Phase 6 choice the contract leaves open (files, timestamp format, which clock each record
  uses, requests the service refuses, degraded-mode record, audit rounding and row checks, reviewer-action rules,
  seeding details).

## 9. Open questions

1. **Seeded decisions carry no discounted links.** The offline rows record none, so `MITIGATING_DISCOUNTED_LINKS`
   cannot fire on the 250 `BACKTEST_REPLAY` decisions and their graph summaries list no discounted link, although
   some of those orders have one (households, hostels). Nothing false is stated, but a reviewer sees less than a
   live decision would show. Smallest fix: one more evidence column (the discounted links as JSON) beside #28's two,
   in `features/builder.py`. I did not do it because Part 2 may not touch `features/`. Your call for Phase 7.
2. **Orders placed before the end of the frozen history are refused.** `features_for_request` must not see events
   at or after t0, and the frozen history runs to the last event before `DEMO_CLOCK`, so a live order with an earlier
   `placed_at` cannot be scored honestly against it. The service returns `RequestRejected` (→ 422) rather than
   degrading. The demo orders (`DEMO_CLOCK − 5 min`) are unaffected. If Phase 7 needs arbitrary past timestamps,
   that needs a per-request replay, which the frozen-history amendment rules out.
3. **Unknown accounts are refused.** `accounts.source` allows only SYNTHETIC and DEMO, so the service cannot create a
   live account row. Fine for the demo; say if Phase 7's simulate-checkout presets need new accounts.
4. **Reviewer actions use the wall clock**, decisions use `DEMO_CLOCK`. An override made today reads
   2026-09-18 against a decision at 2026-09-01 10:30 IST. That is the truth, but it may look odd on the audit
   timeline. The clock is injectable if you want reviewer time pinned to `DEMO_CLOCK` plus elapsed session time.
5. **`threadpoolctl` is now imported directly** (it was already installed and pinned as a scikit-learn dependency,
   so nothing was added or re-pinned). If you want it listed in `pyproject.toml`, that is an Architect decision.

## 10. Gate

Full suite green (740 passed, slow included) before the Part 2 commit. `git status -sb` and `git log --oneline -5` after the commit, and the Part 2 hash, are recorded by the follow-up commit below, never by amending.

*(Filled in by the follow-up commit.)*
