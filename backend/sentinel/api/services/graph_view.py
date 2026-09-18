"""Reviewer relationship graph (§4 GraphPayload, §11b layout notes; Phase 7 brief §C).

An ego graph around the order's account, point-in-time at t0:
    current account (centre) - its order - its identifiers (ring 1) - the other accounts linked through
    those identifiers (ring 2) - their orders in [t0 - 24 h, t0) as satellites.

At most 40 nodes, kept by priority: current -> identifiers -> confirmed-abuse accounts -> by edge weight.
The layout is radial, computed here, deterministic (angular order by (kind, id), no randomness, no force
layout): the same input gives byte-identical output.

Labels are masked. Identifier nodes use the identifiers table's display label ("Device ••7f3a") and an id
derived from a digest of the pseudonymised identifier, so no identifier hash appears anywhere in the payload.
Linked accounts and orders are labelled by the last four characters of their id (Appendix D: reviewers see
linked accounts only as masked ids plus risk state).
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime

from sentinel.api.schemas import GraphEdge, GraphNode, GraphPayload
from sentinel.features.graph_features import EgoView, IdentifierView, Link
from sentinel.features.graph_state import MICROS_PER_DAY, RELIABLE_MIN_WEIGHT, RELIABLE_WINDOW_DAYS, EDGE_KIND
from sentinel.features.tabular_features import OrderQuery

MAX_NODES = 40
RING_1 = 200.0                 # identifiers
RING_2 = 440.0                 # linked accounts
CURRENT_ORDER_RADIUS = 100.0
SATELLITE_OFFSET = 90.0        # a linked order sits this far outside its account
SATELLITE_SPREAD_DEG = 9.0
NOT_IN_COMPONENT = "NOT_IN_RELIABLE_COMPONENT"
_PREFIX = {"DEVICE": "DEV", "ADDRESS": "ADR", "PAYMENT_TOKEN": "TOK"}
KIND_LABEL = {"DEVICE": "Device", "ADDRESS": "Address", "PAYMENT_TOKEN": "Payment token"}


def identifier_node_id(kind: str, ident_node: str) -> str:
    """An opaque, stable id for an identifier node: never the identifier hash itself."""
    return f"{_PREFIX[kind]}:{hashlib.sha256(ident_node.encode('utf-8')).hexdigest()[:16]}"


def account_node_id(account_id: str) -> str:
    return f"ACC:{account_id}"


def order_node_id(order_id: str) -> str:
    return f"ORD:{order_id}"


def masked(kind_label: str, raw_id: str) -> str:
    return f"{kind_label} ••{raw_id[-4:]}"


def _r(value: float) -> float:
    return round(float(value), 4)


def _link_discount(view: IdentifierView, link: Link, t0: int) -> str | None:
    """Why another account's edge is not counted as evidence, or None when it is. Same precedence as the
    identifier-level discount (features.graph_features._discounted_link)."""
    if view.high_fanout:
        return "HIGH_FANOUT_IDENTIFIER"
    if view.multi_tenant:
        return "MULTI_TENANT_ADDRESS"
    if view.discount is not None and view.discount.reason == "HOUSEHOLD_PATTERN":
        return "HOUSEHOLD_PATTERN"
    if link.sequential:
        return "SEQUENTIAL_DEVICE_USE"
    if link.weight < RELIABLE_MIN_WEIGHT or link.last_seen < t0 - RELIABLE_WINDOW_DAYS * MICROS_PER_DAY:
        return "STALE_RELATIONSHIP"
    return None


def _pos(radius: float, degrees: float) -> tuple[float, float]:
    a = math.radians(degrees)
    return round(radius * math.cos(a), 2), round(radius * math.sin(a), 2)


def build_graph_payload(view: EgoView, q: OrderQuery, t0: int, as_of: datetime) -> GraphPayload:
    current = account_node_id(q.account_id)
    current_order = order_node_id(q.order_id)

    # ── candidates ────────────────────────────────────────────────────────────
    ident_nodes: dict[str, dict] = {}
    for v in sorted(view.identifiers, key=lambda v: (v.kind, identifier_node_id(v.kind, v.node))):
        ident_nodes[identifier_node_id(v.kind, v.node)] = {"view": v}

    accounts: dict[str, dict] = {}                     # linked account id -> facts
    edges: list[GraphEdge] = []
    for nid, entry in ident_nodes.items():
        v: IdentifierView = entry["view"]
        own_counted = not (v.multi_tenant or v.high_fanout)
        edges.append(GraphEdge(
            id=f"{current}|{nid}", source=current, target=nid, kind=EDGE_KIND[v.kind], age_days=0.0,
            reliability=_r(v.own_reliability), decayed_weight=_r(v.own_reliability), counted_as_evidence=own_counted,
            discount_reason=None if own_counted else ("HIGH_FANOUT_IDENTIFIER" if v.high_fanout
                                                      else "MULTI_TENANT_ADDRESS")))
        for link in v.links:
            reason = _link_discount(v, link, t0)
            acc = accounts.setdefault(link.account_id, {"confirmed": link.confirmed, "weight": 0.0,
                                                        "counted": False, "first_kind": v.kind, "first_ident": nid,
                                                        "sequential": False, "reasons": []})
            acc["weight"] = max(acc["weight"], link.weight)
            acc["counted"] = acc["counted"] or reason is None
            acc["sequential"] = acc["sequential"] or link.sequential
            if reason is not None:
                acc["reasons"].append(reason)
            if link.sequential:
                entry["sequential"] = True
            entry["counted"] = entry.get("counted", False) or reason is None
            edges.append(GraphEdge(
                id=f"{account_node_id(link.account_id)}|{nid}", source=account_node_id(link.account_id), target=nid,
                kind=EDGE_KIND[v.kind], age_days=_r(max(0.0, (t0 - link.last_seen) / MICROS_PER_DAY)),
                reliability=_r(link.reliability), decayed_weight=_r(link.weight),
                counted_as_evidence=reason is None, discount_reason=reason))

    orders: dict[str, dict] = {}                       # linked order id -> facts
    for account_id, placed in sorted(view.recent_orders.items()):
        if account_id not in accounts:
            continue
        for order_id, placed_at in placed:
            orders[order_id] = {"account": account_id, "placed_at": placed_at}

    # ── cap: current -> identifiers -> confirmed accounts -> by edge weight ───
    def account_rank(a: str) -> tuple:
        return (not accounts[a]["confirmed"], -accounts[a]["weight"], account_node_id(a))

    ranked_accounts = sorted(accounts, key=account_rank)
    ranked_orders = sorted(orders, key=lambda o: (*account_rank(orders[o]["account"]), -orders[o]["placed_at"],
                                                  order_node_id(o)))
    budget = MAX_NODES - 2 - len(ident_nodes)
    kept_accounts = ranked_accounts[:max(budget, 0)]
    budget -= len(kept_accounts)
    kept_set = set(kept_accounts)
    kept_orders = [o for o in ranked_orders if orders[o]["account"] in kept_set][:max(budget, 0)]
    total = 2 + len(ident_nodes) + len(accounts) + len(orders)
    shown = 2 + len(ident_nodes) + len(kept_accounts) + len(kept_orders)

    # ── layout ───────────────────────────────────────────────────────────────
    nodes: list[GraphNode] = [GraphNode(id=current, kind="ACCOUNT", label=q.account_id, state="CURRENT", flags=[],
                                        x=0.0, y=0.0)]
    n_ident = len(ident_nodes)
    order_angle = -90.0 + 180.0 / max(n_ident, 1)       # between the first two identifiers
    ox, oy = _pos(CURRENT_ORDER_RADIUS, order_angle)
    nodes.append(GraphNode(id=current_order, kind="ORDER", label=q.order_id, state="CURRENT", flags=[], x=ox, y=oy))
    edges.append(GraphEdge(id=f"{current_order}|{current}", source=current_order, target=current, kind="PLACED_BY",
                           age_days=0.0, reliability=1.0, decayed_weight=1.0, counted_as_evidence=True,
                           discount_reason=None))
    for i, (nid, entry) in enumerate(ident_nodes.items()):
        v = entry["view"]
        flags = [f for f, on in (("MULTI_TENANT", v.multi_tenant), ("SEQUENTIAL_DEVICE", entry.get("sequential")),
                                 ("HIGH_FANOUT", v.high_fanout)) if on]
        x, y = _pos(RING_1, -90.0 + 360.0 * i / n_ident)
        label = v.label or masked(KIND_LABEL[v.kind], v.node)       # identifier first seen in a live request
        nodes.append(GraphNode(id=nid, kind=v.kind, label=label,
                               state="LINKED" if entry.get("counted") else "NEUTRAL", flags=flags, x=x, y=y))

    ring_2 = sorted(kept_accounts, key=lambda a: (accounts[a]["first_kind"], accounts[a]["first_ident"],
                                                  account_node_id(a)))
    angle_of: dict[str, float] = {}
    for i, a in enumerate(ring_2):
        facts = accounts[a]
        angle = -90.0 + 360.0 * (i + 0.5) / len(ring_2)
        angle_of[a] = angle
        x, y = _pos(RING_2, angle)
        state = "CONFIRMED_ABUSE" if facts["confirmed"] else ("LINKED" if facts["counted"] else "NEUTRAL")
        flags = [f for f, on in (("SEQUENTIAL_DEVICE", facts["sequential"]),
                                 ("RECENT_24H", any(orders[o]["account"] == a for o in kept_orders))) if on]
        nodes.append(GraphNode(id=account_node_id(a), kind="ACCOUNT", label=masked("Account", a), state=state,
                               flags=flags, x=x, y=y))

    by_account: dict[str, list[str]] = {}
    for o in sorted(kept_orders, key=lambda o: (orders[o]["placed_at"], order_node_id(o))):
        by_account.setdefault(orders[o]["account"], []).append(o)
    for a, own in sorted(by_account.items()):
        facts = accounts[a]
        counted = a in view.component
        reason = None if counted else (sorted(set(facts["reasons"]))[0] if facts["reasons"] else NOT_IN_COMPONENT)
        for j, o in enumerate(own):
            angle = angle_of[a] + (j - (len(own) - 1) / 2) * SATELLITE_SPREAD_DEG
            x, y = _pos(RING_2 + SATELLITE_OFFSET, angle)
            oid = order_node_id(o)
            nodes.append(GraphNode(id=oid, kind="ORDER", label=masked("Order", o),
                                   state="LINKED" if counted else "NEUTRAL", flags=["RECENT_24H"], x=x, y=y))
            edges.append(GraphEdge(
                id=f"{oid}|{account_node_id(a)}", source=oid, target=account_node_id(a), kind="PLACED_BY",
                age_days=_r((t0 - orders[o]["placed_at"]) / MICROS_PER_DAY), reliability=1.0, decayed_weight=1.0,
                counted_as_evidence=counted, discount_reason=reason))

    shown_ids = {n.id for n in nodes}
    kept_edges = sorted((e for e in edges if e.source in shown_ids and e.target in shown_ids), key=lambda e: e.id)
    return GraphPayload(nodes=nodes, edges=kept_edges, truncated=shown < total, hidden_node_count=total - shown,
                        as_of=as_of)


def empty_graph_payload(as_of: datetime) -> GraphPayload:
    """No graph state existed when the decision was made (degraded mode, #14): nothing is drawn."""
    return GraphPayload(nodes=[], edges=[], truncated=False, hidden_node_count=0, as_of=as_of)
