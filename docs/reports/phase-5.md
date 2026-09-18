# Phase 5 — Explanations: gate report

*Spec phase 5 (`docs/ARCHITECTURE.md` §12); `october_master_architecture.md` calls it stage 6.*

```
PROGRESS  phase 5 of 12  [#####-----]  6/11 stages to Definition of Done (55%)
          this phase: G. gate — 6 of 6 sections done  |  elapsed 2h11m
```

Full suite green, committed, pushed. Phase 6 not started.

---

## 1. Files changed

| File | Change |
|---|---|
| `backend/sentinel/models/attribution.py` | **new** — ablation attributions, group counterfactual |
| `backend/sentinel/models/reason_codes.py` | **new** — catalog, predicates, evidence, rendering |
| `backend/sentinel/models/explain.py` | **new** — §6.5 levels 1–2, `explain_order` |
| `backend/sentinel/models/registry.py` | reference vector save / verified load |
| `backend/sentinel/models/__init__.py` | exports `explain_order` |
| `backend/sentinel/config/reason_codes.toml` | `GRAPH_DEVICE_SHARED`; device fallback template |
| `backend/sentinel/api/schemas.py` | `ReasonCode.attribution_note`, optional |
| `backend/sentinel/cli.py` | `build-reference` command |
| `backend/artifacts/models/reference_medians.json` | **new, committed** |
| `backend/tests/unit/test_attribution.py` | **new** — 15 tests |
| `backend/tests/unit/test_reason_codes.py` | **new** — 35 tests |
| `backend/tests/scenarios/test_demo_explanations.py` | **new** — 24 tests (slow) |
| `docs/DEVIATIONS.md` | #27 updated; #28, #29 added; stage-7 TODO |
| `docs/PROGRESS.md`, `docs/briefs/`, `docs/reports/` | progress row; brief and report tracked |
| `.gitignore` | `.october/` |

Nothing under `data/`, `features/`, `policy/` or `evaluation/` was touched. No retraining, no regeneration:
the committed model bundles and their SHA-256s are unchanged.

## 2. Test results and latency

| Run | Result | Time |
|---|---|---|
| Baseline `-m "not slow"` | 441 passed, 126 deselected | 24.4 s |
| `test_attribution.py` | 15 passed | 3.0 s |
| `test_reason_codes.py` | 35 passed | 2.2 s |
| `test_demo_explanations.py` | 24 passed | 6.8 s |
| **Full suite incl. slow (gate)** | **644 passed** | **2 m 27 s** |

567 → 644, +77 tests.

**Latency**, both models plus the group call, per order, 60 warmed runs:

| | |
|---|---|
| median | **16.39 ms** (budget < 20 ms) |
| p95 | 27.32 ms |
| max | 36.77 ms |

The test asserts the **median**, and that is a deliberate choice worth your eye: a single timing on a
shared machine measures scheduler noise as much as code, and p95 here exceeds the budget. Two things got
it from 84 ms to 16 ms: folding the group ablation into the same batch as the per-feature rows (one
`predict_proba` per model per order — asserted by `test_one_predict_per_model`), and skipping the second
`design_matrix` pass that `train.predict` would have run over a frame already built to the bundle's
schema. The floor is ~15 ms, being two 300-tree models; a budget below that is not reachable without
changing the models.

## 3. Rendered explanations — all three demos

Produced by the committed artifacts and the real `FeatureBuilder`. No probability is set anywhere.

### Demo 1 — `ORD-DEMO-001` · dominant group **account**

```
p_return 0.6154   p_abuse 0.0000   p_abuse_without_graph_evidence 0.0000
group attribution pp:  graph +0.00   account -0.01   order +0.00
```

> **No material abuse evidence was found; the score reflects this account's own history rather than links
> to other accounts.**

| Code | Model | Strength | attribution_pp | Text |
|---|---|---|---|---|
| `RETURN_SIZE_BRACKETING` | RETURN | MODERATE | **31.5385** | "Multiple sizes of the same item in the cart." |
| `RETURN_HIGH_HISTORY` | RETURN | MODERATE | **18.6813** | "The customer returns often (52%). This affects return likelihood, not abuse risk." |

Mitigating:

| Code | Strength | attribution_pp | Text |
|---|---|---|---|
| `MITIGATING_ESTABLISHED_ACCOUNT` | MODERATE | −0.0083 | "Long-standing account with no flagged claims." |
| `MITIGATING_DISCOUNTED_LINKS` | WEAK | *none* | "Shared address discounted: household pattern." |

No graph code fires. No `attribution_note` on any code.

### Demo 2 — `ORD-DEMO-002` · dominant group **graph**

```
p_return 0.3784   p_abuse 0.9507   p_abuse_without_graph_evidence 0.0993
group attribution pp:  graph +85.14   account -3.98   order -0.20
```

> **The abuse score is driven mainly by links to other accounts sharing this order's device, payment
> method or delivery pattern.**

| Code | Strength | attribution_pp | Text | Note |
|---|---|---|---|---|
| `NEW_ACCOUNT_HIGH_VALUE` | WEAK | **94.2864** | "New account placing a high-value order." | |
| `TEMPORAL_BURST` | MODERATE | **4.5465** | "4 linked accounts placed orders in the last 24 hours." | |
| `SAME_SKU_COORDINATION` | MODERATE | **3.7985** | "Linked accounts ordered the same item 3 times this week." | |
| `GRAPH_DEVICE_SHARED` | MODERATE | **3.5849** | "This device was used by 5 other accounts in the last 30 days." | |
| `GRAPH_TOKEN_REUSE` | STRONG | **0.1802** | "The payment method was used by 3 other accounts in the last 30 days." | ⚠ redundant |
| `GRAPH_DEVICE_CONFIRMED_LINK` | STRONG | **0.0** | "This device is linked to other accounts since confirmed for return abuse." | ⚠ redundant |

Mitigating: none.

⚠ = `attribution_note`: *"Redundant with other relationship evidence; the score is already explained by
correlated features."*

This is deviation #27 doing its job, and it is the phase's most interesting output. The two **STRONG**
device and token codes — the very evidence G2 counts to permit BLOCK — have attributions of 0.0 and 0.18
pp, because `component_size_reliable_90d` and friends already carry that signal (the #25 redundancy
finding). Under the original §6.5 rule, which gated firing at |Δ| ≥ 2 pp, **neither would have appeared at
all**, and the reviewer would have seen a ring member with no device evidence listed. They now fire on
evidence and declare their own redundancy.

The group counterfactual is the honest measure of the same thing: **0.9507 → 0.0993**, a drop of 85.14 pp,
against §11's documented "without graph evidence ≈ 0.10".

### Demo 3 — `ORD-DEMO-003` · dominant group **graph**

```
p_return 0.2458   p_abuse 0.6913   p_abuse_without_graph_evidence 0.0008
group attribution pp:  graph +69.06   account -16.56   order +0.00
```

> **The abuse score is driven mainly by links to other accounts sharing this order's device, payment
> method or delivery pattern.**

| Code | Strength | attribution_pp | Text | Note |
|---|---|---|---|---|
| `GRAPH_DEVICE_SHARED` | MODERATE | **39.0493** | "This device was used by 3 other accounts in the last 30 days." | |
| `ACCOUNT_PRIOR_SUSPICIOUS_CLAIM` | MODERATE | **0.0** | "The account had 1 return or delivery claim(s) flagged in the last 6 months." | ⚠ redundant |

Mitigating:

| Code | Strength | attribution_pp | Text |
|---|---|---|---|
| `MITIGATING_DISCOUNTED_LINKS` | WEAK | *none* | "Shared address discounted: stale relationship." |

## 4. Deviations

- **#27 updated** (as the brief requires): records the optional `ReasonCode.attribution_note`, the note
  text and threshold, that `min_attribution_pp` no longer gates firing, and the three measured cases.
- **#28 added** — `GRAPH_DEVICE_CONFIRMED_LINK` cannot fill `{n}` and `{days}`: the confirmed-peer count
  and confirmation date do not exist outside `features/`, which this phase may not change. The §6.5
  template is kept verbatim; a `template_unconfirmed_counts` fallback renders until the values exist, and
  `Evidence` already accepts them so stage 7 can switch it on with no code change. Filling `{n}` from
  `device_other_accounts_30d` would have told the reviewer "5 accounts later confirmed" when 3 were.
- **#29 added** — (a) new code `GRAPH_DEVICE_SHARED` for §9.2's second DEVICE limb, which had no reason
  code, so Demo 3's counted DEVICE signal produced no device reason; (b) `order_value_inr` and
  `primary_category` excluded from the dominance groups — with them in, Demo 2 scored order +94.82 vs
  graph +85.14 and explained a ring member as "an expensive order".
- **TODO added** for manual stage 7: pass the two device values through and #28's fallback retires.

## 5. Open questions

1. **`NEW_ACCOUNT_HIGH_VALUE` is WEAK in the catalog but has the largest attribution on Demo 2 (94.29
   pp).** It sorts first, above every graph code, so the reviewer's top line for a ring member is "new
   account placing a high-value order". The group attribution and the prediction sentence both say graph,
   so the explanation as a whole is right, but the ordering undersells it. Reordering by
   `evidence_strength` before attribution would fix it; I did not, because the brief specifies sorting by
   `|attribution_pp|`. Your call.
2. **`TEMPORAL_BURST`'s §6.5 text says "{n} linked accounts placed orders"** but the feature is
   `linked_orders_24h`, a count of orders, not accounts. Demo 2 renders "4 linked accounts placed orders"
   from 4 linked *orders*. The wording is the contract's own; I kept it per the brief. It is a small
   misstatement to a reviewer and worth a one-word fix ("linked orders were placed") if you agree.
3. **Latency asserts the median, not p95** (§2 above). If you want a hard per-request guarantee, the
   budget needs to be ~40 ms or the models need fewer trees.
4. **`MITIGATING_DISCOUNTED_LINKS` reports `attribution_pp = None`** — it maps to no single feature, since
   a discounted link is a graph-construction fact rather than a feature value. The contract allows null.

## 6. Gate

```
## main...origin/main
```
```
b8f1c6a phase 5: explanations
91a4837 docs: tighten demo 3 band; refresh operating manual
53158b2 phase 4: follow-ups
1c2259c phase 4: models and evaluation
7e1e525 phase 3: review fixes
```
