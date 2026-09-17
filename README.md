# SENTINEL — Return Abuse Detection with Cost-Weighted Decisioning

**Build status:** Phases 1–4 complete and committed. **Phase 1** (policy engine), including the review fixes (decision-time G4, degraded mode without scores, Python 3.12, exact frontend pins). **Phase 2** (synthetic generator), including the review fixes (rings hidden at account level, investigation coverage, high-value genuine carts, `features/identifiers.py`, demo isolation): `python -m sentinel.cli generate` writes the seeded world, ground truth and ld-1.0 labels to `backend/data/`, and `world-stats` prints prevalence and ring diagnostics. **Phase 3** (feature builder): one chronological-replay `FeatureBuilder` for offline and serving; `build-features` writes `backend/data/features.parquet` (feature set `fs-1.0-0ad43d7f`) and `policy_inputs.parquet`; leakage tests P1–P7 green. **Phase 4** (models and evaluation): calibrated return and abuse models with committed artifacts under `backend/artifacts/`, the offline backtest and `evaluation.json`, and the three §11 demo orders scored end to end by the real models and the real policy (`train --force`, `evaluate`, `score-demos`). Measured on TEST: abuse PR-AUC **0.814** with graph features against **0.527** without, cold-start ring R3 recall **0.727** against 0.143, hard-negative cohorts at a **0.0** genuine block rate. Full suite 567 passing, slow included. **Phase 5** (explanations) is pending and will be briefed in the new multi-agent workspace. Attributions, reason codes, the demo database and the API routes are not built yet.

> **A prediction is not a decision.**

Sentinel is a hackathon prototype demonstrating responsible, cost-aware fraud decisioning for e-commerce return abuse. It builds two separate ML predictions (return probability and abuse probability), feeds them into a deterministic policy engine that selects the minimum-cost proportionate action, and provides a reviewer dashboard with full audit trail.

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

The frontend proxies API requests to `http://127.0.0.1:8000`.

### Run Tests

```bash
cd backend
python -m pytest tests/ -m "not slow" # while iterating: skips world generation, training and model checks
python -m pytest tests/               # the full suite, including slow tests: run before every commit
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
