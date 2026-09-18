"""Read side of the reviewer API (§4 GET /orders, GET /orders/{id}, GET /audit-events; Phase 7 brief §B).

Everything is read from the database as recorded. The customer summary and the RULE_BASED baseline need
account history as of the order's t0; it is rebuilt from the account's own HISTORY orders and events strictly
before t0 and read with the same point-in-time functions the FeatureBuilder uses (tabular_features), so the
detail page and the decision can never disagree about what was visible. Baselines come from
policy/baselines.py; nothing is re-implemented.
"""
from __future__ import annotations

import json
import math
import sqlite3

from sentinel.api.schemas import (Action, AuditEventOut, AuditEventsResponse, BaselineOutcome,
                                  CustomerSummary, GraphPayload, OrderDetailResponse,
                                  OrderLineIn, OrderSummary, QueueFilters, QueueItem, QueueResponse)
from sentinel.api.services.errors import NotFound
from sentinel.api.services.graph_view import empty_graph_payload
from sentinel.api.services.scoring import response_from_db
from sentinel.db.models import parse_utc
from sentinel.features.graph_state import GraphState, to_micros
from sentinel.features.tabular_features import account_age_days, clv_inr, count_in_window, matured_return_counts
from sentinel.money import make_money
from sentinel.policy.baselines import fixed_threshold, rule_based
from sentinel.policy.config import PolicyConfig

STRONG_SIGNAL_WEIGHT = 0.3                  # §9.2 / G4 weak-evidence weight
GRAPH_SIGNALS = frozenset({"DEVICE", "PAYMENT_TOKEN", "ADDRESS", "TEMPORAL_BURST"})
CLAIM_WINDOW_DAYS = 180


# ── graph evidence classes (queue filter) ────────────────────────────────────
def graph_evidence_class(summary: dict) -> str:
    """NONE: no relationship signal present. STRONG: a present relationship signal that counts for
    corroboration with weight >= 0.3. WEAK_ONLY: relationship signals present, none of them strong."""
    present = [s for s in summary["signals"] if s["present"] and s["signal"] in GRAPH_SIGNALS]
    if not present:
        return "NONE"
    if any(s["counts_for_corroboration"] and s["weight"] >= STRONG_SIGNAL_WEIGHT for s in present):
        return "STRONG"
    return "WEAK_ONLY"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def graph_risk_summary(summary: dict, degraded: bool) -> str:
    if degraded:
        return "No relationship evidence (degraded mode)"
    confirmed = summary["confirmed_abusive_accounts_in_component"]
    counted = [s for s in summary["signals"]
               if s["present"] and s["counts_for_corroboration"] and s["signal"] in GRAPH_SIGNALS]
    if confirmed:
        return (f"Linked group of {_plural(summary['component_size_reliable_90d'], 'account', 'accounts')}, "
                f"{confirmed} confirmed abusive")
    if counted:
        kinds = ", ".join(s["signal"].replace("_", " ").lower() for s in counted)
        return f"Relationship evidence: {kinds}"
    if summary["discounted_links"]:
        link = summary["discounted_links"][0]
        return f"Shared {link['kind'].replace('_', ' ').lower()} discounted: {link['reason'].replace('_', ' ').lower()}"
    return "No relationship evidence"


# ── queue ────────────────────────────────────────────────────────────────────
_QUEUE_SQL = """
SELECT d.decision_id, d.order_id, d.scored_at, d.p_return, d.p_abuse, d.recommended_action, d.current_action,
       d.status, d.source, d.degraded_mode, d.graph_summary_json, d.costs_json, o.order_value_inr
FROM decisions d JOIN orders o USING (order_id)
"""


def _allow_cost(costs_json: str) -> float | None:
    for c in json.loads(costs_json):
        if c["action"] == "ALLOW":
            return c["expected_cost"]["inr"]
    return None


def queue(conn: sqlite3.Connection, f: QueueFilters) -> QueueResponse:
    rows = []
    for r in conn.execute(_QUEUE_SQL):
        summary = json.loads(r["graph_summary_json"])
        if f.action is not None and r["current_action"] != f.action.value:
            continue
        if f.status is not None and r["status"] != f.status:
            continue
        if f.source is not None and r["source"] != f.source:
            continue
        if f.min_p_abuse is not None and (r["p_abuse"] is None or r["p_abuse"] < f.min_p_abuse):
            continue
        if f.min_value_inr is not None and r["order_value_inr"] < f.min_value_inr:
            continue
        if f.graph_evidence != "ANY" and graph_evidence_class(summary) != f.graph_evidence:
            continue
        rows.append((r, summary))

    def key(item):
        r, _ = item
        missing = float("-inf")
        if f.sort == "p_abuse_desc":
            primary = r["p_abuse"] if r["p_abuse"] is not None else missing
        elif f.sort == "value_desc":
            primary = r["order_value_inr"]
        elif f.sort == "exposure_desc":                 # expected cost of letting the order through (ALLOW)
            exposure = _allow_cost(r["costs_json"])
            primary = exposure if exposure is not None else missing
        else:
            primary = to_micros(parse_utc(r["scored_at"]))
        return (-primary if primary != missing else math.inf, r["order_id"])

    rows.sort(key=key)
    counts = {a: 0 for a in Action}
    for r, _ in rows:
        counts[Action(r["current_action"])] += 1
    items = [QueueItem(
        order_id=r["order_id"], decision_id=r["decision_id"], scored_at=parse_utc(r["scored_at"]),
        order_value=make_money(r["order_value_inr"]), p_return=r["p_return"], p_abuse=r["p_abuse"],
        recommended_action=r["recommended_action"], current_action=r["current_action"], status=r["status"],
        graph_risk_summary=graph_risk_summary(s, bool(r["degraded_mode"])),
        corroborating_signal_count=s["corroborating_signal_count"], source=r["source"])
        for r, s in rows[f.offset:f.offset + f.limit]]
    return QueueResponse(items=items, total=len(rows), counts_by_action=counts)


# ── audit events ─────────────────────────────────────────────────────────────
def audit_event_out(row: sqlite3.Row) -> AuditEventOut:
    return AuditEventOut(
        seq=row["seq"], event_id=row["event_id"], event_type=row["event_type"],
        occurred_at=parse_utc(row["occurred_at"]), order_id=row["order_id"], actor_type=row["actor_type"],
        actor_id=row["actor_id"], previous_action=row["previous_action"], new_action=row["new_action"],
        policy_version=row["policy_version"], return_model_version=row["return_model_version"],
        abuse_model_version=row["abuse_model_version"], payload=json.loads(row["payload_json"]),
        prev_hash=row["prev_hash"], event_hash=row["event_hash"])


def audit_events(conn: sqlite3.Connection, limit: int, offset: int, order_id: str | None) -> AuditEventsResponse:
    where, args = ("WHERE order_id = ?", (order_id,)) if order_id is not None else ("", ())
    total = conn.execute(f"SELECT COUNT(*) FROM audit_events {where}", args).fetchone()[0]
    rows = conn.execute(f"SELECT * FROM audit_events {where} ORDER BY seq LIMIT ? OFFSET ?", (*args, limit, offset))
    return AuditEventsResponse(items=[audit_event_out(r) for r in rows], total=total)


# ── order detail ─────────────────────────────────────────────────────────────
def account_history(conn: sqlite3.Connection, account_id: str, t0: str) -> GraphState:
    """The account's own HISTORY orders and events strictly before t0, replayed in time order (orders before
    events at one timestamp, as the FeatureBuilder does). Live orders never enter it (#30)."""
    created = conn.execute("SELECT created_at FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    state = GraphState({account_id: to_micros(parse_utc(created["created_at"]))}, {})
    orders = [(to_micros(parse_utc(r["placed_at"])), 0, r["order_id"], r["order_value_inr"]) for r in conn.execute(
        "SELECT order_id, placed_at, order_value_inr FROM orders WHERE account_id = ? AND source = 'HISTORY' "
        "AND placed_at < ?", (account_id, t0))]
    events = [(to_micros(parse_utc(r["occurred_at"])), 1, r["order_id"], r["event_type"], r["event_id"])
              for r in conn.execute(
                  "SELECT e.event_id, e.order_id, e.event_type, e.occurred_at FROM order_events e JOIN orders o "
                  "USING (order_id) WHERE o.account_id = ? AND o.source = 'HISTORY' AND e.occurred_at < ?",
                  (account_id, t0))]
    for item in sorted([*orders, *events], key=lambda x: (x[0], x[1], x[2], x[-1] if x[1] else 0)):
        if item[1] == 0:
            state.add_order(item[2], account_id, item[0], float(item[3]), frozenset(), [])
        else:
            state.apply_event(item[2], item[3], item[0])
    return state


def _clv_basis(clv: float, cfg: PolicyConfig) -> str:
    if clv <= cfg.clv.new_customer_floor_inr:
        return "NEW_CUSTOMER_FLOOR"
    if clv >= cfg.clv.cap_inr:
        return "CAPPED"
    return "HISTORY"


def order_detail(conn: sqlite3.Connection, order_id: str, cfg: PolicyConfig,
                 fixed_threshold_taus: tuple[float, float]) -> OrderDetailResponse:
    d = conn.execute("SELECT * FROM decisions WHERE order_id = ?", (order_id,)).fetchone()
    if d is None:
        raise NotFound(f"no decision for order {order_id}")
    o = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    lines = conn.execute("SELECT * FROM order_lines WHERE order_id = ? ORDER BY line_no", (order_id,)).fetchall()
    decision = response_from_db(conn, order_id, cfg, idempotent_replay=False)
    t0_text, t0 = d["features_as_of"], parse_utc(d["features_as_of"])
    t0_us = to_micros(t0)

    state = account_history(conn, o["account_id"], t0_text)
    acc = state.accounts.get(o["account_id"])
    age = account_age_days(state, o["account_id"], t0_us)
    returns, matured = matured_return_counts(state, o["account_id"], t0_us)
    degraded = bool(d["degraded_mode"])
    clv = (cfg.clv.new_customer_floor_inr if degraded                   # what the G6 context carried (#14)
           else clv_inr(state, o["account_id"], t0_us, gross_margin_rate=cfg.economics.gross_margin_rate,
                        floor_inr=cfg.clv.new_customer_floor_inr, cap_inr=cfg.clv.cap_inr))
    customer = CustomerSummary(
        account_id=o["account_id"], account_age_days=math.floor(age),
        prior_orders=len(acc.orders) if acc else 0,
        matured_return_rate=returns / matured if matured else None,
        prior_suspicious_claims_180d=count_in_window(acc.flag_times, t0_us, CLAIM_WINDOW_DAYS) if acc else 0,
        clv_used_by_policy=make_money(clv), clv_basis=_clv_basis(clv, cfg))

    order = OrderSummary(
        order_id=order_id, placed_at=parse_utc(o["placed_at"]), order_value=make_money(o["order_value_inr"]),
        discount_pct=o["discount_pct"],
        lines=[OrderLineIn(sku_id=ln["sku_id"], product_id=ln["product_id"], variant=ln["variant"],
                           category=ln["category"], unit_price_inr=ln["unit_price_inr"], quantity=ln["quantity"])
               for ln in lines],
        payment_method=o["payment_method"], delivery_speed=o["delivery_speed"])

    baselines: list[BaselineOutcome] = []
    if d["p_abuse"] is not None:                         # a degraded decision has no score to threshold
        tau_review, tau_block = fixed_threshold_taus
        baselines.append(fixed_threshold(d["p_abuse"], tau_block=tau_block, tau_review=tau_review))
    baselines.append(rule_based(returns / matured if matured else None, returns, age, o["order_value_inr"],
                                o["payment_method"]))

    graph = (GraphPayload.model_validate_json(d["graph_payload_json"]) if d["graph_payload_json"] is not None
             else empty_graph_payload(t0))
    events = conn.execute("SELECT * FROM audit_events WHERE order_id = ? ORDER BY seq", (order_id,)).fetchall()
    appeals = [json.loads(e["payload_json"])["appeal"]["appeal_reference"] for e in events
               if e["event_type"] == "APPEAL_OPENED"]
    return OrderDetailResponse(order=order, customer=customer, decision=decision, graph=graph, baselines=baselines,
                               audit_events=[audit_event_out(e) for e in events],
                               current_action=d["current_action"], appeal_reference=appeals[-1] if appeals else None)


def current_action(conn: sqlite3.Connection, order_id: str) -> Action:
    row = conn.execute("SELECT current_action FROM decisions WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise NotFound(f"no decision for order {order_id}")
    return Action(row["current_action"])

