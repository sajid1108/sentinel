"""GET /metrics (§4 MetricsResponse; Phase 7 brief §D).

Two sources, never mixed (Appendix A C8):
- `activity` is counted from the database: decisions have no labels, so nothing here is a realized outcome.
  `model_estimated_cost_avoided` = Σ EC(ALLOW) − EC(selected) over non-degraded decisions, an estimate under
  the policy's own cost model.
- `backtest`, `models`, `cold_start_ring_recall` and `sensitivity` are copied unchanged from the offline
  `evaluation.json` (synthetic TEST labels). Nothing is computed from the live queue.
"""
from __future__ import annotations

import json
import sqlite3

from sentinel.api.schemas import Action, DecisionActivity, MetricsResponse
from sentinel.money import make_money

DATA_NOTICE = ("Synthetic data is used to validate the architecture, policy behaviour, auditability, "
               "and coordinated-pattern detection. Real deployment would require merchant-specific "
               "historical data and prospective validation.")
FRICTION_ACTIONS = (Action.PREPAID_ONLY, Action.MANUAL_REVIEW)


def _expected_cost(costs: list[dict], action: str) -> float:
    return next(c["expected_cost"]["inr"] for c in costs if c["action"] == action)


def _traceable(row: sqlite3.Row) -> bool:
    """Every version a reader needs to reproduce the decision, present and matching the row's columns."""
    p = json.loads(row["payload_json"])
    v = p.get("model_versions") or {}
    return bool(p.get("policy_version") and p.get("policy_config_sha256") and v.get("return_model")
                and v.get("abuse_model") and v.get("feature_set")
                and p["policy_version"] == row["policy_version"] and v["return_model"] == row["return_model_version"]
                and v["abuse_model"] == row["abuse_model_version"])


def activity(conn: sqlite3.Connection) -> DecisionActivity:
    decisions = conn.execute("SELECT decision_id, recommended_action, degraded_mode, costs_json, "
                             "graph_summary_json FROM decisions").fetchall()
    n = len(decisions)
    distribution = {a: 0 for a in Action}
    avoided = 0.0
    weak = 0
    for d in decisions:
        distribution[Action(d["recommended_action"])] += 1
        if not d["degraded_mode"]:
            costs = json.loads(d["costs_json"])
            avoided += _expected_cost(costs, "ALLOW") - _expected_cost(costs, d["recommended_action"])
        weak += bool(json.loads(d["graph_summary_json"])["weak_evidence_only"])
    overridden = conn.execute("SELECT COUNT(DISTINCT decision_id) FROM audit_events "
                              "WHERE event_type = 'OVERRIDE_APPLIED'").fetchone()[0]
    created = conn.execute("SELECT payload_json FROM audit_events WHERE event_type = 'DECISION_CREATED'").fetchall()
    payloads = [json.loads(e["payload_json"]) for e in created]
    explained = sum(1 for p in payloads if p["prediction_explanation"] and p["policy_explanation"])
    events = conn.execute("SELECT payload_json, policy_version, return_model_version, abuse_model_version "
                          "FROM audit_events").fetchall()
    return DecisionActivity(
        orders_evaluated=n, action_distribution=distribution,
        friction_orders=sum(distribution[a] for a in FRICTION_ACTIONS),
        manual_review_volume=distribution[Action.MANUAL_REVIEW],
        override_rate=overridden / n if n else 0.0,
        model_estimated_cost_avoided=make_money(avoided),
        explanation_coverage=explained / n if n else 0.0,
        version_traceability=sum(map(_traceable, events)) / len(events) if events else 0.0,
        weak_evidence_decisions=weak)


def metrics(conn: sqlite3.Connection, evaluation: dict) -> MetricsResponse:
    return MetricsResponse(
        activity=activity(conn), backtest=evaluation["backtest"], models=evaluation["models"],
        cold_start_ring_recall=evaluation["cold_start_ring_recall"], sensitivity=evaluation["sensitivity"],
        drift_monitoring="PLACEHOLDER_NOT_COMPUTED", data_notice=DATA_NOTICE)
