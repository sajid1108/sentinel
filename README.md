# SENTINEL — Return Abuse Detection with Cost-Weighted Decisioning

**Build status:** Phases 1–9 complete and committed; the Definition of Done (§12 cut line) is met. **Phase 1** (policy engine), including the review fixes (decision-time G4, degraded mode without scores, Python 3.12, exact frontend pins). **Phase 2** (synthetic generator), including the review fixes (rings hidden at account level, investigation coverage, high-value genuine carts, `features/identifiers.py`, demo isolation): `python -m sentinel.cli generate` writes the seeded world, ground truth and ld-1.0 labels to `backend/data/`, and `world-stats` prints prevalence and ring diagnostics. **Phase 3** (feature builder): one chronological-replay `FeatureBuilder` for offline and serving; `build-features` writes `backend/data/features.parquet` (feature set `fs-1.0-0ad43d7f`) and `policy_inputs.parquet`; leakage tests P1–P7 green. **Phase 4** (models and evaluation): calibrated return and abuse models with committed artifacts under `backend/artifacts/`, the offline backtest and `evaluation.json`, and the three §11 demo orders scored end to end by the real models and the real policy (`train --force`, `evaluate`, `score-demos`). Measured on TEST: abuse PR-AUC **0.814** with graph features against **0.527** without, cold-start ring R3 recall **0.727** against 0.143, hard-negative cohorts at a **0.0** genuine block rate. **Phase 5** (explanations): ablation attributions, evidence-based reason codes ordered by evidence strength, count-aware reviewer text and the three explanation levels. **Phase 6** (database, audit, scoring service): `python -m sentinel.cli seed-db` recreates `backend/data/sentinel.db` with the as-of-`DEMO_CLOCK` world and exactly 250 backtest-replay decisions, each with a SHA-256 hash-chained audit event; `reset-demo` deletes the file and seeds again (DEMO_MODE only). `ScoringService` scores orders in-process against a frozen history, idempotently, with G6 degraded mode; `ReviewService` records overrides and appeals. **Phase 7** (API): `python -m sentinel.cli serve` serves the internal reviewer routes under `/api/v1/internal` (score-order, queue, order detail with a deterministic point-in-time relationship graph and both baselines, override, appeal, audit events and chain verification, metrics, demo presets and reset; all require `X-Internal-Key`) and the outcome-only public route `POST /api/v1/public/checkout/decision`; `export-openapi` writes `frontend/src/api/openapi.json` and `npm run gen:types` generates `types.ts`. **Phase 8** (frontend: order detail): `/orders/:orderId` is the screen the demo happens on — the two probabilities as two separate cards that are never combined, the four actions priced as horizontal bars in a fixed order with guardrail-removed actions hatched and chipped, the point-in-time relationship graph at the server's coordinates with discounted links dashed, evidence and model attribution as two separate panels, the hash-chained audit timeline with live chain verification, the baseline contrast, and override and appeal dialogs. Every number comes from the API: money is rendered from the server's `display` strings, the guardrail thresholds and the "Demonstration assumptions" panel come from `GET /api/v1/internal/policy`, and a test scans `src/` for any numeric literal equal to a policy config value. `npm test` runs the vitest suite against payloads recorded from the real backend. Screenshots of all three demo scenarios are in `docs/reports/phase-8/`. **Phase 9** (Phase 8 follow-ups and the MVP): the abuse meter is one neutral token at every value, probabilities in reviewer-facing server text are formatted exactly as the page formats them ("G3 requires an abuse probability of at least 70.0%; this order scored 69.1%"), every timestamp renders in IST, and `RECENT_24H` is stated once in the graph legend. `/queue` is the review queue — one row per decision with the return and abuse probabilities as two separate columns that are never combined and never red, filters bound to the URL query, `limit` 50 pagination, and counts labelled "current action (after review)" because the queue counts what is in effect while `/metrics` counts what the system recommended. Above it, "Simulate checkout" posts each `GET /demo/presets` entry back unmodified and opens its decision, and "Reset demo" rebuilds the database behind an inline confirmation; neither renders when `DEMO_MODE` is off. `/` is the Overview: decision activity and the synthetic backtest as two separately labelled sections, with **no row highlighted or marked best** — the tuned fixed-threshold baseline's realized cost (₹1,60,112 / 1,000) is lower than AegisShift's (₹1,95,313) and the table shows that plainly. **The whole demo now runs end to end in the browser** (reset → queue → simulate checkout → order detail → override → overview), which is the Definition of Done (§12 cut line). `npm test` runs 164 vitest tests; screenshots are in `docs/reports/phase-9/`. The calibration chart, the sensitivity sweep and the cohort tables are Phase 11.

> **A prediction is not a decision.**

AegisShift is a hackathon prototype demonstrating responsible, cost-aware fraud decisioning for e-commerce return abuse. It builds two separate ML predictions (return probability and abuse probability), feeds them into a deterministic policy engine that selects the minimum-cost proportionate action, and provides a reviewer dashboard with full audit trail.

## Core Principle

Models predict. Policy decides. The system separates ML predictions from business decisions:

1. **Return model** → P(return)
2. **Abuse model** → P(abuse), enhanced by graph-based coordination detection
3. **Policy engine** → Expected cost for each action → selects the cheapest proportionate action
4. **Guardrails** → Structural constraints (e.g., BLOCK requires corroboration)
5. **Audit** → Every decision is recorded with a tamper-evident hash chain

## Actions

| Action | Meaning |
|---|---|
| **ALLOW** | Order proceeds normally |
| **PREPAID_ONLY** | Prepaid payment required; refund after warehouse inspection |
| **MANUAL_REVIEW** | Routed to a human reviewer |
| **BLOCK** | Order cannot proceed (requires high confidence + corroboration) |

## Quick Start

### Prerequisites

- Python 3.12
- Node.js 20+
- pip (exact versions in `backend/requirements.lock`)

### Backend

```bash
cd backend

# Install dependencies (Windows: .venv\Scripts\python.exe)
py -3.12 -m venv .venv
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .

# Generate synthetic data
python -m sentinel.cli generate

# Build features
python -m sentinel.cli build-features

# Train models
python -m sentinel.cli train

# Evaluate
python -m sentinel.cli evaluate

# Seed the demo database
python -m sentinel.cli seed-db

# Start the API server
python -m sentinel.cli serve
```

### Frontend

```bash
cd frontend

npm ci
npm run dev
```

The frontend proxies API requests to `http://127.0.0.1:8000`, injecting `X-Internal-Key`, so the UI and the
API share one origin and no key reaches the bundle. With the API running, score the three presets and open
`http://localhost:5173/orders/ORD-DEMO-002` for the order-detail screen.

### Run Tests

```bash
cd backend
python -m pytest tests/ -m "not slow" # while iterating: skips world generation, training and model checks
python -m pytest tests/               # the full suite, including slow tests: run before every commit

cd ../frontend
npm test                              # vitest: the order-detail page against recorded API payloads
npm run build                         # tsc -b && vite build
```

## Demo Scenarios

Three seeded orders demonstrate the system's key behaviors:

1. **Legitimate Frequent Returner** → ALLOW
   *"Frequent returns do not automatically imply abuse."*

2. **Coordinated Abuse Ring** → BLOCK
   *"Graph evidence reveals coordination invisible at the account level."*

3. **Uncertain Middle** → MANUAL_REVIEW
   *"Uncertainty receives proportionate friction, not automatic refusal."*

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the complete frozen architecture.

## Technology

| Layer | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite |
| ML | scikit-learn HistGradientBoosting, pandas, NetworkX, joblib |
| Frontend | React, TypeScript, Vite, Tailwind CSS v4, @xyflow/react, Recharts |

## Limitations

> **Synthetic data is used to validate the architecture, policy behaviour, auditability, and coordinated-pattern detection. Real deployment would require merchant-specific historical data and prospective validation.**

- No authentication platform (static internal key)
- No SHAP (ablation attributions + reason-code catalog)
- No Neo4j or GNN (in-memory NetworkX)
- No live retraining (offline CLI only)
- No cloud deployment
- Monetary values are demonstration assumptions (policy v1.0)
