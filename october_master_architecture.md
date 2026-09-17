# Sentinel — October Master Architecture & Operating Manual

**Role of this file:** ground-truth *operating* instruction for every agent node in the October canvas.
**It is not the specification.** It points at the specification and never restates it.

| Ground truth | File | Rule |
|---|---|---|
| The contract | `docs/ARCHITECTURE.md` (1,799 lines) | **Frozen. Never edit.** |
| Accepted changes | `docs/DEVIATIONS.md` (#1–#27, plus the "Carried-forward TODOs" section) | Overrides the contract where they conflict. Append only. |
| Build status | `README.md` (top) | Updated by whoever commits a stage. |
| This file | `october_master_architecture.md` | Roles, scope, protocol, current state. Architect writes; others read. |

> A previous session replaced `ARCHITECTURE.md` with a 60-line summary and silently weakened a guardrail. Any agent that summarises, truncates or "cleans up" a ground-truth file has caused a defect. Cite sections; never restate them.

---

## Section A — Core system identity & tech stack

### A1. Purpose

Sentinel is a merchant-side **return-abuse risk manager** built for hackathon Track 02 (AI Risk Manager). It separates two things that conventional systems conflate:

1. **Return probability** — a normal cost of doing business.
2. **Abuse probability** — wardrobing, empty-box and item-not-received claims, and coordinated rings operating across accounts.

The founding principle is **a prediction is not a decision**:

- Models output `p_return` and `p_abuse` plus explanations. **Never an action.**
- A deterministic **policy engine** computes the expected monetary cost of ALLOW, PREPAID_ONLY, MANUAL_REVIEW and BLOCK, and selects the cheapest action that the guardrails permit.
- Every decision writes a hash-chained audit event; a human reviewer can override with a recorded reason.

All data is synthetic. Every surface carries this notice verbatim:

> Synthetic data is used to validate the architecture, policy behaviour, auditability, and coordinated-pattern detection. Real deployment would require merchant-specific historical data and prospective validation.

### A2. Tech stack — exact pins

Backend (`backend/pyproject.toml`, `backend/requirements.lock`; `requires-python = "==3.12.*"`, venv at `backend/.venv`):

| Package | Version | Package | Version |
|---|---|---|---|
| fastapi | 0.141.1 | pandas | 3.0.5 |
| uvicorn[standard] | 0.53.0 | numpy | 2.5.3 |
| pydantic | 2.13.5 | scikit-learn | 1.9.1 |
| sqlalchemy | 2.0.53 | networkx | 3.6.1 |
| pyarrow | 25.0.1 | joblib | 1.6.0 |
| pytest (dev) | 9.1.1 | httpx (dev) | 0.28.1 |

Frontend (`frontend/package.json`, exact pins, `.npmrc` has `save-exact=true`, install with `npm ci`):

| Package | Version | Package | Version |
|---|---|---|---|
| react / react-dom | 19.3.0 | vite | 6.4.3 |
| react-router-dom | 7.18.4 | typescript | 5.8.3 |
| @xyflow/react | 12.11.6 | tailwindcss + @tailwindcss/vite | 4.3.3 |
| recharts | 2.15.4 | @vitejs/plugin-react | 4.7.0 |

Storage: SQLite (schema in `backend/sentinel/db/schema.sql`, append-only triggers). Model artifacts: joblib bundles committed under `backend/artifacts/`. Offline data: Parquet under `backend/data/` (git-ignored).

**No package may be added, removed or re-pinned without Architect approval.** Model artifacts load only under the pinned scikit-learn version; the registry verifies SHA-256 and version on load.

### A3. Architecture pattern & data flow

Offline (deterministic, seed `20260901`, fixed `DEMO_CLOCK = 2026-09-01T10:30+05:30`):

```
generate → build-features → train → evaluate
synthetic event log → chronological replay → point-in-time features + policy inputs
                   → return model + abuse model (calibrated) → artifacts + evaluation.json
```

Online (in-process; no public model endpoint):

```
POST /score-order → FeatureBuilder.features_for_request(t0)
                  → calibrated p_return, p_abuse  (models: probabilities only)
                  → ablation attributions → reason codes
                  → policy engine: expected cost of 4 actions → guardrails remove actions
                                 → cheapest permitted action
                  → audit event (SHA-256 chain) → SQLite
                  → reviewer dashboard → optional human override
Public surface:  POST /checkout/decision → business outcome only (no scores, reasons, costs)
```

Layer rules:

- `data/` → `features/` → `models/` → `policy/` → `api/`. Dependencies point one way.
- `policy/` is pure: no clock, no I/O, no settings import. Inputs arrive in `DecisionContext` / `SignalInputs`.
- `models/` never imports `policy/` and never names an Action.
- `features/`, `models/`, `policy/`, `api/` never import `data/generator`, `data/archetypes`, `data/labels`, and never read `order_labels` or `sim_ground_truth` (AST-enforced test).
- One `FeatureBuilder` code path serves both training and live scoring.
- Money is formatted once, server-side (`sentinel/money.py`); the UI renders server strings.

---

## Section B — Strict coding guidelines & constraints

### B1. Unbreakable rules (Builder and Fixer)

**Contract**
1. `docs/ARCHITECTURE.md` is frozen. Deviations go in `docs/DEVIATIONS.md` with reason and measurement; append, never rewrite history.
2. No feature, screen, route, service or dependency beyond what the active stage brief asks for.
3. Endpoint paths, field names, table names, action names, guardrail ids (G1–G6) and reason codes are fixed vocabulary.

**Decision integrity**
4. Models emit probabilities and explanations only. Policy chooses actions.
5. `p_return` is never an input to action selection (G1). `action_costs()` has no such parameter; a test enforces it.
6. Guardrails may only *remove* actions. PREPAID_ONLY and MANUAL_REVIEW are always feasible.
7. BLOCK requires `p_abuse ≥ 0.70` **and** ≥ 2 corroborating signals including at least one of DEVICE, PAYMENT_TOKEN, ACCOUNT_CLAIMS.
8. Every decision stores `cost_optimal_action` and `selected_action` separately, plus the rule that fired.

**Data integrity**
9. Point-in-time only: strict `occurred_at < t0`; confirmations counted by confirmation time; matured history only. Never read a label in serving code.
10. Splits are chronological; the calibrator is fit on CALIBRATION only; demo accounts and hand-authored peers are split `RECENT` and never trained or evaluated on.
11. Determinism: same seed → same event-log SHA-256; same training run → same artifact SHA-256.

**Honesty**
12. Never hard-code a probability, special-case a demo id, or loosen a test, band or bound to make something pass. If a target is unreachable, stop and escalate with numbers.
13. Explanations are deterministic templates filled from recorded evidence. **No SHAP, no LLM-generated text.**
14. Customer-facing responses carry outcome only. ALLOW and MANUAL_REVIEW return identical bodies.
15. No claim of real-world effectiveness. Synthetic backtest numbers are labelled as such.

**Code style**
16. Python 3.12, full type annotations on public functions, `from __future__ import annotations` where needed, frozen dataclasses for value objects, Pydantic v2 contracts with `extra="forbid"`.
17. Errors: raise explicit exceptions with actionable messages; never `assert` for an invariant that must hold in production (`python -O` strips it); never swallow an exception to keep a demo alive except in the declared degraded-mode path, which must set `degraded_mode=True` and record it.
18. TypeScript `strict`, `noUnusedLocals`, `noUnusedParameters`; API types generated from OpenAPI, never hand-written after Phase 7; no `any`.
19. Tests accompany the code in the same commit. Every stage brief lists required tests; all must pass, `slow` included, before commit. `pytest -m "not slow"` is for iteration only.
20. Commits: new commits only, never amend/rebase/force-push; message `phase N: <what>`; **no Claude co-author trailer** (operator preference); artifacts committed with the phase that produces them.

### B2. Directory structure (do not reorganise)

```
sentinel/
├── october_master_architecture.md      # this file
├── README.md                           # build status
├── docs/ARCHITECTURE.md  DEVIATIONS.md
├── backend/
│   ├── pyproject.toml  requirements.lock
│   ├── artifacts/                      # COMMITTED: models/*.joblib, model_registry.json, reports/evaluation.json
│   ├── data/                           # git-ignored parquet world + sentinel.db
│   └── sentinel/
│       ├── cli.py  settings.py  money.py
│       ├── config/     policy_v1_0.toml, reason_codes.toml
│       ├── data/       archetypes.py generator.py labels.py demo_orders.py      [offline only]
│       ├── features/   identifiers.py graph_state.py graph_features.py
│       │               tabular_features.py builder.py definitions.py
│       ├── models/     train.py calibrate.py registry.py __init__.py
│       │               + attribution.py reason_codes.py        [Stage 6 adds]
│       ├── policy/     config.py costs.py guardrails.py engine.py baselines.py
│       ├── evaluation/ splits.py metrics.py cohorts.py backtest.py report.py demos.py
│       ├── db/         schema.sql models.py                     [Stage 7]
│       ├── audit/      chain.py service.py                      [Stage 7]
│       └── api/        main.py deps.py schemas.py routers/ services/
│   └── tests/  unit/ leakage/ model/ scenarios/ api/
└── frontend/src/  api/ lib/ components/ pages/
```

---

## Section C — Roadmap state (15 stages)

The specification's build order is Phase 0–12 (`ARCHITECTURE.md` §12). Stages 14 and 15 are operator-facing and not in the spec.

| Stage | Spec phase | Name | Status |
|---|---|---|---|
| 1 | 0 | Skeleton and pins | **[COMPLETED]** |
| 2 | 1 | Policy engine | **[COMPLETED]** |
| 3 | 2 | Synthetic generator | **[COMPLETED]** |
| 4 | 3 | Feature builder | **[COMPLETED]** |
| 5 | 4 | Train, calibrate, evaluate | **[COMPLETED]** — `1c2259c`, follow-ups `53158b2` |
| 6 | 5 | Explanations | **[ACTIVE: BUILDER]** — unblocked; stage 5 has landed |
| 7 | 6 | DB, audit, scoring service | [PENDING] |
| 8 | 7 | API | [PENDING] |
| 9 | 8 | Frontend: order detail | [PENDING] |
| 10 | 9 | Frontend: queue | [PENDING] |
| 11 | 10 | Frontend: overview | [PENDING] |
| — | — | *Cut line: stages 1–11 are the Definition of Done* | |
| 12 | 11 | Backtest depth | [PENDING] |
| 13 | 12 | Hardening | [PENDING] |
| 14 | — | Demo rehearsal & fallback video | [PENDING] |
| 15 | — | Pitch & submission | [PENDING] |

### C1. Completed capabilities (stages 1–4)

**Stage 1 — Skeleton** (`01d2c77`): pinned toolchain, `settings.py` with the fixed demo clock, `config/policy_v1_0.toml` (every monetary assumption), `reason_codes.toml`, full Pydantic contract set, SQLite DDL with append-only triggers, React shell with three routes.

**Stage 2 — Policy engine** (`53dffaa`, `c811cee`, `42569bc`): `action_costs()` (no `p_return`), guardrails G1–G6, `decide()` returning cost-optimal and selected action with a rendered explanation, baselines (fixed-threshold, rule-based, allow-all), config validator including the slope-order check. All three demo cost tables reproduce to ±₹0.01.

**Stage 3 — Synthetic generator** (`5208112`, `530656e`): ~2,940 accounts, ~10,150 orders, return rate ~23 %, confirmed abuse ~3.5 %. Rings R1–R4 (R1/R2 recruit in waves; R3 is a cold-start ring confined to TEST; R4 is hand-scheduled for Demo 2). Hard negatives: households, offices/hostels, refurbished devices, high-value genuine carts, unconfirmed abusers. Labels derived from events only (`ld-1.0`), demo world truncated at `DEMO_CLOCK`.

**Stage 4 — Feature builder** (`58e977d`, `7e1e525`): chronological event replay; NetworkX graph with edge reliability, time decay, multi-tenant/sequential-device/high-fanout discounting; §6.2/§6.3 feature sets with the exclusions enforced in `definitions.py`; `SignalInputs`, discounted links and point-in-time CLV as policy inputs; leakage suite P1–P7 green; all three demo feature rows asserted. Build time ~2 s for 10k orders.

**Measured evidence the design works** (stage 5 run, pre-commit): abuse TEST PR-AUC **0.814** with graph features vs **0.527** without; cold-start ring R3 recall **0.727** vs 0.143; hard-negative archetypes have a genuine block rate of **0.0**.

### C2. Stage 5 — **[COMPLETED]** — Train, calibrate, evaluate

Committed as `1c2259c` (models and evaluation) and `53158b2` (follow-ups). **567 tests pass**, slow included. Artifacts committed under `backend/artifacts/`.

What exists: two calibrated models (return: isotonic; abuse: sigmoid, both with monotonic constraints on evidence features), a registry that verifies SHA-256 and scikit-learn version on load, `evaluation.json` with model metrics, risk-band calibration, cohorts, a four-strategy realized-cost backtest, cost and label sensitivity sweeps, and the `guardrail_cost` section. CLI: `train`, `evaluate`, `score-demos`.

Headline measurements to preserve and never tune away:

| Result | Value |
|---|---|
| Abuse TEST PR-AUC, with graph features | **0.814** |
| Same model without graph features | 0.527 |
| Cold-start ring R3 recall (full vs no-graph) | **0.727** vs 0.143 |
| Hard-negative archetypes, genuine block rate | **0.0** |
| Tuned fixed-threshold baseline vs Sentinel, realized cost / 1,000 | ₹1,60,112 vs ₹1,95,313 |
| Guardrail price per genuine block avoided | ₹9,211, i.e. **2.05×** the policy's own modelled false-block cost |
| New-account (<30 d) friction vs older cohorts | **0.3611** vs 0.0479–0.0586 (block rate 0.0074) |

Two findings that shape later stages: the confirmed-neighbour features are **redundant, not absent** (individually predictive, zero splits in the full model, because `account_age_days`, `component_size_reliable_90d` and `primary_category` identify the same rows first), which is why deviation #27 makes reason codes evidence-based; and Demo 3 is reviewed because **cost** says so (BLOCK ₹4,051.94 vs MANUAL_REVIEW ₹1,858.14 at p = 0.6913), not because guardrail G3 forbade blocking. MANUAL_REVIEW is cost-optimal for 0.0930 < p < 0.8413.

Historical file ownership for this stage (now merged to main; listed so later stages know what stage 5 owns):

```
backend/sentinel/models/{train,calibrate,registry}.py, __init__.py
backend/sentinel/evaluation/{splits,metrics,cohorts,backtest,report,demos}.py
backend/sentinel/data/{archetypes,demo_orders,generator}.py
backend/sentinel/features/{builder,tabular_features}.py
backend/sentinel/policy/baselines.py, backend/sentinel/cli.py
backend/tests/{model,scenarios,unit}/ (stage-5 files)
backend/artifacts/**
```

How it closed: the CALIBRATION positives bound was lowered to ≥ 35 (measured 37); the "model responds to confirmed-neighbour evidence" test was dropped as unreachable from the data side and replaced by a ≥ 20 data-health count (measured 21); the ring wave-widening experiment was reverted, keeping R3 recall at 0.727; §11's Demo 3 device fact was amended to three concurrent peers, with one peer order moved inside the 24-hour window to give `linked_orders_24h = 1`. Details in #25 and #26.

Open debts recorded in `DEVIATIONS.md` under "Carried-forward TODOs": the account-age cohort friction table must appear in the stage 12 dashboard work, and the stage 13 model card must state the new-account friction disparity plainly.

### C3. Stage 6 — **[ACTIVE: BUILDER TASK]** — Explanations

**Dependency satisfied:** stage 5 landed at `53158b2`, so the committed artifacts are stable and the Builder may start. Work from `main` at or after that commit. Do not retrain or modify `backend/artifacts/models/*.joblib`; the reference vector is produced by a separate CLI step (see below).

Files to create (Builder is the only writer):

```
backend/sentinel/models/attribution.py
backend/sentinel/models/reason_codes.py
backend/sentinel/config/reason_codes.toml          (extend; keep existing codes)
backend/tests/unit/test_attribution.py
backend/tests/unit/test_reason_codes.py
backend/tests/scenarios/test_demo_explanations.py
```

Logic:

1. **Ablation attribution** on the calibrated model. Reference vector = per-feature median over **genuine CALIBRATION** orders, computed once and stored in the model bundle (not recomputed at request time). For feature *j*: `Δj = p(x) − p(x with x_j := ref_j)`, one batched `predict_proba` per order, target < 20 ms.
2. **Group ablation**: all graph features set to reference → `p_abuse_without_graph_evidence`, labelled in the UI as *"Counterfactual: relationship features set to typical values"*, never as a separate model.
3. Contributions are reported in **probability points**, never summed, never presented as additive.
4. **Reason codes fire** only when the catalog predicate is true **and** `|Δj| ≥ min_attribution_pp` in the stated direction. Mitigating (DECREASES) codes are produced too.
5. **Three explanation levels**, deterministic templates: prediction explanation (chosen by dominant group: graph / account / order), order-level reason list sorted by |Δ|, and the policy explanation already produced by `policy/engine.py` (do not duplicate it).
6. Internal-only. Nothing from this module may reach a customer-facing response.

Tests: attribution determinism; group ablation matches the sum of setting those features individually to reference only in sign, not value (assert non-additivity is not claimed); a code never fires when its predicate is false; a code never fires when attribution is below threshold; monotone features produce non-negative Δ; all three demo orders produce the expected code sets — Demo 1 mitigating codes with no graph codes, Demo 2 `GRAPH_DEVICE_CONFIRMED_LINK` + `GRAPH_TOKEN_REUSE` + `TEMPORAL_BURST`, Demo 3 `ACCOUNT_PRIOR_SUSPICIOUS_CLAIM` + a device code; rendered text contains no raw feature names, no thresholds and no model version; latency budget.

Gate: full suite green, commit `phase 5: explanations`, report, stop.

### C4. Stages 7–15 — [PENDING]

| Stage | One-line scope |
|---|---|
| 7 | SQLite persistence, hash-chained append-only audit service, `ScoringService`, demo DB seeding with ~250 backtest-replay decisions. |
| 8 | FastAPI routes: score-order (idempotent), orders + detail, audit events + verify, metrics, override, appeal, public checkout, demo reset; internal-key dependency; OpenAPI → TypeScript types. |
| 9 | Order detail page: two separate score cards, expected-cost bars with infeasible actions hatched, relationship graph with dashed discounted links, reasons, audit timeline, override dialog. |
| 10 | Review queue with filters and the "Simulate checkout" presets for the three demo orders. |
| 11 | Overview: decision activity tiles and the synthetic backtest panel, kept visually separate. |
| 12 | Backtest depth: cost/label sensitivity, cohort friction table, R3 cold-start panel (data already produced in stage 5). |
| 13 | Hardening: demo reset, degraded-mode toggle, audit verify in the UI, `docs/MODEL_CARD.md` (must state the new-account friction disparity), drift placeholder. |
| 14 | `docs/DEMO_SCRIPT.md`, two cold-start rehearsals, and a recorded fallback video. |
| 15 | Pitch narrative and submission, reviewed against the honesty rules in B1. |

---

## Section D — Agent handoff protocols

Written for October as it exists today: agents are separate processes with their own working directory; the Bus provides identity, discovery, messaging, delegation, shared tasks with claims/progress/dependencies, and human escalation; **local delivery is pull-based and a running agent cannot be interrupted**; the spec is draft 0.1, so treat tool names as unstable and keep the repo as the durable record.

### D1. Node roles

| Node | Reads | Writes | Never |
|---|---|---|---|
| **Architect** | everything | `october_master_architecture.md`, review verdicts, stage briefs | production code, tests, artifacts |
| **Fixer** | everything | only the owned files of the **active** stage (C2) | files owned by the Builder; `ARCHITECTURE.md` |
| **Builder** | everything | only the files listed for its stage (C3) | files owned by the Fixer; `ARCHITECTURE.md` |

### D2. Session start — every node, every time

1. Read this file, then `docs/ARCHITECTURE.md` and `docs/DEVIATIONS.md` in full. Never summarise them into another file.
2. `git status -sb` and `git log --oneline -8`. Continue from uncommitted work; never discard, reset or stash it without operator approval.
3. `pytest -m "not slow"` in `backend/` to confirm the baseline; report if it isn't green.
4. Claim your Bus task before writing anything. If the task is already claimed by another node, stop and escalate.

### D3. Avoiding conflicting edits

1. **Worktree isolation is mandatory when two nodes are active.** Fixer works in the primary tree on `main`; Builder works in its own worktree on a branch named `stage-<n>-build`. Merge only through the operator after the Fixer's stage commit lands.
2. **Single-writer files.** `docs/DEVIATIONS.md`, `README.md`, `backend/sentinel/cli.py`, `pyproject.toml` and `frontend/package.json` are shared. Only the node that is committing the active stage may edit them; the other node requests the edit over the Bus and waits.
3. **Ownership is by file, declared in C2/C3.** Touching a file you do not own is a protocol violation: stop, revert that change, escalate.
4. `backend/artifacts/**` is owned exclusively by the node running `train`. Two nodes must never train at once.
5. Never run `generate` while another node is mid-test: it rewrites `backend/data/`.

### D4. Dependencies between stages

Declare on the Bus, as a task dependency: **Stage 6 (Builder) depends on Stage 5 (Fixer) commit.** Until that commit exists, the Builder is limited to reading and drafting text (C3). Phases 5→6→7→8 form a strict chain (models → explanations → scoring service → API) and must not be parallelised. Genuine parallel opportunities appear later: stage 9 against stage 12, and stage 13 docs against anything.

### D5. Check-in cadence (because delivery is pull-based)

A node checks its Bus inbox and re-reads this file:

- at session start,
- after each completed sub-task in its brief,
- before any commit,
- before any escalation.

A node that runs long without a check-in cannot be steered. Keep sub-tasks under ~30 minutes.

### D6. Escalation — stop and ask the operator when

- an instruction conflicts with the frozen contract or an accepted deviation,
- a bound, band or metric cannot be met without weakening a test, a demo fact or the data,
- a decision requires a value judgement about monetary assumptions, fairness or honesty,
- two nodes need the same file,
- the gate fails.

Escalate with: the measured numbers, the smallest fix you can propose, and the alternatives you rejected with reasons. **Do not iterate past a stop condition.**

### D7. Completion report — format for every stage

1. files changed
2. test results (counts, slow included) and command timings
3. the stage's own measurements (world stats, metrics, backtest, demo scores — whatever the brief names)
4. deviations added or updated
5. open questions
6. `git status -sb` and `git log --oneline -5`

Report to the Operator, then stop. **Do not start the next stage.** The Architect reviews and issues the next brief.

### D8. Definition of done for the whole project

An order is submitted → return probability and abuse probability are produced separately → suspicious relationships are shown as graph evidence with discounted links visible → all four actions are priced → a proportionate action is selected and explained → an audit event is chained → a human can override with a recorded reason → and no customer-facing surface ever exposes a score, a threshold or a cost.
