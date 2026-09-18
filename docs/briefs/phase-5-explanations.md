# Phase 5 brief: Explanations

*(The operator calls this "stage 5 build"; `october_master_architecture.md` calls it stage 6. Same work. Phase numbering here matches `docs/ARCHITECTURE.md` §12.)*

Issued by the Architect. Read `october_master_architecture.md` §C3, `docs/ARCHITECTURE.md` §6.5 and `docs/DEVIATIONS.md` #27 before writing code. **#27 amends §6.5 and takes precedence over it.**

Out of scope: DB, audit, API, UI, anything from manual stage 7 onward. No retraining, no regeneration, and no changes under `data/`, `features/`, `policy/` or `evaluation/`.

Usage note: iterate with `pytest -m "not slow"` (~26 s). Run the full suite (~4–6 min) only before committing.

## A. Reference vector (no retraining)

- New CLI command `build-reference`: per-feature median over **genuine** CALIBRATION orders (`abuse_label = 0`) for both models' feature sets, written to `backend/artifacts/models/reference_medians.json` with `feature_set_version`, the `model_versions` it was built against, row count, and its own sha256. Commit the file.
- Categorical features: most frequent genuine CALIBRATION category.
- `registry` verifies on load that `feature_set_version` and `model_versions` match the loaded bundles; mismatch raises.
- Do **not** modify the committed model bundles.

## B. `models/attribution.py`

- `attributions(bundle, reference, row) -> dict[str, float]`: for each feature *j*, `delta_j = p(x) − p(x with x_j := reference_j)`, in probability points, on the **calibrated** output. One batched `predict_proba` per order.
- `group_attribution(bundle, reference, row, group)`: same with every feature in the group set to reference. Required group: `ABUSE_GRAPH_FEATURES`, producing `p_abuse_without_graph_evidence`.
- Deltas are never summed and never presented as additive. Do not expose a function that sums them.
- Budget: < 20 ms per order for both models plus the group call, asserted in a test.

## C. `models/reason_codes.py` + `config/reason_codes.toml`

Per deviation #27, codes are **evidence statements**:

- A code fires when its catalog predicate is true. Individual attribution does **not** gate firing.
- Each fired code carries: `code`, `model`, `direction`, `reviewer_text` (template filled from recorded evidence values), `evidence` dict, `attribution_pp`, `evidence_strength`.
- When a fired code's `|attribution_pp| < 2.0`, set the new optional field `attribution_note` to: *"Redundant with other relationship evidence; the score is already explained by correlated features."* Adding this optional field to the `ReasonCode` contract is an approved deviation: record it in #27 and keep the field optional.
- Keep every existing code and the §6.5 wording of existing templates.
- Mitigating (DECREASES) codes fire on their predicates too and are returned in a separate list.
- Templates contain no raw feature names, no thresholds, no model versions and no probabilities. Counts and ages are fine.

## D. Explanation levels (deterministic templates only; no LLM text)

- `prediction_explanation(reasons, group_attribution)`: one sentence, template chosen by the dominant evidence group (graph / account / order); dominance decided by group attribution, ties broken by fixed precedence graph > account > order.
- Order-level reasons: fired codes sorted by `|attribution_pp|` descending, then catalog order; mitigating codes listed separately.
- The policy explanation already exists in `policy/engine.py`. Do not duplicate or re-render it.
- `explain_order(...)` returns one structure: scores, `p_abuse_without_graph_evidence`, reasons, mitigating reasons, `prediction_explanation`. It must not import `sentinel.policy` and must not name an `Action`.

## E. Tests

- **Determinism:** same row twice gives identical attributions and identical rendered text.
- **Reference integrity:** tampered `reference_medians.json` raises on load; `feature_set_version` mismatch raises.
- **Firing rules:** a code never fires when its predicate is false; a code **does** fire when the predicate holds and its attribution is 0, and then carries `attribution_note` (use `device_confirmed_abuse_weight` on the Demo 2 row, whose delta is 0.0000 — this is the #27 behaviour and the reason it exists).
- **Group attribution:** on the Demo 2 row, `p_abuse_without_graph_evidence` is at least 0.40 below `p_abuse`.
- **Text safety:** rendered text for all three demos contains none of the feature names in `ABUSE_FEATURES`/`RETURN_FEATURES`, none of the numeric guardrail thresholds, and no model version string.
- **Latency budget** from B.
- **Demo expectations** (slow), through the committed artifacts and the real `FeatureBuilder`:
  - Demo 1: no graph codes fire; at least one mitigating code fires; `prediction_explanation` is account-dominant.
  - Demo 2: `GRAPH_DEVICE_CONFIRMED_LINK`, `GRAPH_TOKEN_REUSE` and `TEMPORAL_BURST` all fire; `prediction_explanation` is graph-dominant; the confirmed-device code carries `attribution_note`.
  - Demo 3: `ACCOUNT_PRIOR_SUSPICIOUS_CLAIM` fires and at least one device-related code fires.
- **Purity:** AST scan confirms `models/` does not import `sentinel.policy` and contains no `Action` names.

## F. Progress reporting (required)

Print a progress line at the start, after each of sections A–E, and in the final report. Format exactly:

```
PROGRESS  phase 5 of 12  [####------]  5/11 stages to Definition of Done (45%)
          this phase: C. reason codes — 3 of 6 steps done  |  elapsed 0h48m
```

Rules:
- The overall bar counts **completed phases** (0–4 done = 5 of the 11 stages that make up the Definition of Done, which ends at phase 10).
- `this phase` names the current section letter and its step count.
- `elapsed` is measured from the start of your session.
- Also update your row in `docs/PROGRESS.md` before committing: what landed, commit hashes, finish time, and actual build time for this phase.

## G. Gate and report

- Full suite including slow; commit as `phase 5: explanations`; push; stop. Do not start manual stage 7.
- Report: files changed; test results and measured latency; the **full rendered explanation output for all three demos** (prediction explanation, every fired code with its `attribution_pp` and any `attribution_note`, mitigating codes, and `p_abuse_without_graph_evidence`); deviations added; open questions; `git status -sb` and `git log --oneline -5`.
