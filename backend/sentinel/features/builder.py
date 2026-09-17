"""FeatureBuilder: ONE code path for the offline build and for serving (§6, §7.2 P1-P3).

Serving:  builder = FeatureBuilder.replay(world, as_of); builder.features_for_request(request, t0)
Offline:  for row in FeatureBuilder(world).iter_order_features(): ...

Both drive the same chronological replay. Orders and outcome events are merged by timestamp; at
one timestamp the features of every order placed then are computed first, and only afterwards are
that timestamp's order edges and events applied. So an order never sees its own edges, and state
visible at t0 is exactly what happened strictly before t0.

`world` is any mapping with the tables accounts, identifiers, orders, order_lines, order_events.
Labels and ground truth are never read here (P11).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

import pandas as pd

from sentinel.api.schemas import DiscountedLink, ScoreOrderRequest
from sentinel.features import definitions
from sentinel.features.graph_features import GraphAnalysis, analyse
from sentinel.features.graph_state import (GraphState, IdentifierMeta, from_micros, series_to_micros,
                                           to_micros, visible)
from sentinel.features.tabular_features import OrderQuery, QueryLine, clv_inr, order_value_inr, tabular_features
from sentinel.policy.config import PolicyConfig, load_policy_config
from sentinel.policy.guardrails import SignalInputs

WORLD_TABLES = ("accounts", "identifiers", "orders", "order_lines", "order_events")
_END = float("inf")


@dataclass(frozen=True)
class OrderFeatures:
    order_id: str
    split: str | None
    t0: datetime
    features: dict[str, float | int | str]


def query_from_request(request: ScoreOrderRequest) -> OrderQuery:
    return OrderQuery(
        order_id=request.order_id, account_id=request.account_id, placed_at=to_micros(request.placed_at),
        lines=tuple(QueryLine(ln.sku_id, ln.product_id, ln.variant, ln.category, float(ln.unit_price_inr),
                              int(ln.quantity)) for ln in request.lines),
        discount_pct=float(request.discount_pct), delivery_speed=request.delivery_speed,
        payment_method=request.payment_method, device_id=request.device_id, address_id=request.address_id,
        payment_token_id=request.payment_token_id)


class FeatureBuilder:
    def __init__(self, world, policy_config: PolicyConfig | None = None):
        cfg = policy_config or load_policy_config()
        self._margin_rate = cfg.economics.gross_margin_rate
        self._clv_floor, self._clv_cap = cfg.clv.new_customer_floor_inr, cfg.clv.cap_inr

        accounts = world["accounts"]
        created = dict(zip(accounts["account_id"], series_to_micros(accounts["created_at"])))
        ident = world["identifiers"]
        metas = {i: IdentifierMeta(k, s, lbl) for i, k, s, lbl in zip(
            ident["identifier_id"], ident["kind"], series_to_micros(ident["multi_tenant_set_at"]),
            ident["display_label"])}
        self.state = GraphState(created, metas)

        lines: dict[str, list[QueryLine]] = {}
        ol = world["order_lines"].sort_values(["order_id", "line_no"], kind="stable")
        for oid, sku, prod, var, cat, price, qty in zip(ol["order_id"], ol["sku_id"], ol["product_id"],
                                                       ol["variant"], ol["category"], ol["unit_price_inr"],
                                                       ol["quantity"]):
            lines.setdefault(oid, []).append(QueryLine(sku, prod, var, cat, float(price), int(qty)))

        orders = world["orders"].sort_values(["placed_at", "order_id"], kind="stable")
        tokens = orders["payment_token_id"].astype(object).where(orders["payment_token_id"].notna(), None)
        splits = orders["split"].astype(object).where(orders["split"].notna(), None)
        self._orders: list[tuple[int, OrderQuery, str | None]] = []
        for t, oid, acc, disc, speed, method, dev, adr, tok, split in zip(
                series_to_micros(orders["placed_at"]), orders["order_id"], orders["account_id"],
                orders["discount_pct"], orders["delivery_speed"], orders["payment_method"], orders["device_id"],
                orders["address_id"], tokens, splits):
            q = OrderQuery(oid, acc, t, tuple(lines.get(oid, ())), float(disc), speed, method, dev, adr, tok)
            self._orders.append((t, q, split))

        events = world["order_events"].sort_values(["occurred_at", "event_id"], kind="stable")
        self._events = list(zip(series_to_micros(events["occurred_at"]), events["order_id"], events["event_type"]))
        self._next_order = self._next_event = 0
        self._as_of: int | None = None
        self._cache: tuple | None = None

    # ── replay ──
    @classmethod
    def replay(cls, world, as_of: datetime, policy_config: PolicyConfig | None = None) -> "FeatureBuilder":
        """A builder whose graph state holds everything with timestamp < as_of (serving entry point)."""
        builder = cls(world, policy_config)
        for _ in builder._run(until=to_micros(as_of), compute=False):
            pass
        return builder

    def iter_order_features(self) -> Iterator[OrderFeatures]:
        """Offline entry point: every historical order's features as of its own placed_at."""
        for t, q, split, features in self._run(until=None, compute=True):
            yield OrderFeatures(q.order_id, split, from_micros(t), features)

    def _run(self, until: int | None, compute: bool):
        orders, events = self._orders, self._events
        while True:
            t_order = orders[self._next_order][0] if self._next_order < len(orders) else _END
            t_event = events[self._next_event][0] if self._next_event < len(events) else _END
            t = min(t_order, t_event)
            if t == _END or (until is not None and not visible(t, until)):
                break
            end = self._next_order
            while end < len(orders) and orders[end][0] == t:
                end += 1
            batch = orders[self._next_order:end]
            if compute:                                     # 1. features for every order placed at t
                for _, q, split in batch:
                    yield t, q, split, self._features(q, t)
            for _, q, _ in batch:                           # 2. then that timestamp's order edges
                self.state.add_order(q.order_id, q.account_id, t, order_value_inr(q), q.skus, q.identifiers)
            self._next_order = end
            while self._next_event < len(events) and events[self._next_event][0] == t:   # 3. and its events
                _, order_id, event_type = events[self._next_event]
                self.state.apply_event(order_id, event_type, t)
                self._next_event += 1
            self._as_of = t
        if until is not None:
            self._as_of = until

    @property
    def graph_state_as_of(self) -> datetime | None:
        """The replay time: state includes everything strictly before it."""
        return None if self._as_of is None else from_micros(self._as_of)

    # ── features ──
    def _analysis(self, q: OrderQuery, t0: int) -> tuple[dict, GraphAnalysis]:
        key = (q, t0, self.state.last_applied)
        if self._cache is None or self._cache[0] != key:
            self._cache = (key, tabular_features(self.state, q, t0), analyse(self.state, q, t0))
        return self._cache[1], self._cache[2]

    def _features(self, q: OrderQuery, t0: int) -> dict[str, float | int | str]:
        tab, graph = self._analysis(q, t0)
        merged = {**tab, **graph.features}
        return {name: merged[name] for name in definitions.all_features()}

    def _check_t0(self, t0: datetime | None, request: ScoreOrderRequest) -> int:
        t = to_micros(t0 if t0 is not None else request.placed_at)
        if self.state.last_applied is not None and not visible(self.state.last_applied, t):
            raise ValueError("graph state already contains events at or after t0; replay to an earlier time")
        return t

    def features_for_request(self, request: ScoreOrderRequest, t0: datetime | None = None) -> dict:
        t = self._check_t0(t0, request)
        return self._features(query_from_request(request), t)

    def signal_inputs(self, request: ScoreOrderRequest, t0: datetime | None = None) -> SignalInputs:
        """§9.2 policy inputs: feature values plus the weight of the links carrying each signal."""
        t = self._check_t0(t0, request)
        tab, graph = self._analysis(query_from_request(request), t)
        f, s = graph.features, graph.signal_fields
        return SignalInputs(
            device_confirmed_abuse_weight=f["device_confirmed_abuse_weight"],
            device_other_accounts_30d=f["device_other_accounts_30d"],
            device_weight=s["device_weight"],
            token_other_accounts_30d=f["token_other_accounts_30d"],
            token_weight=s["token_weight"],
            address_is_multi_tenant=s["address_is_multi_tenant"],
            address_confirmed_abuse_weight=s["address_confirmed_abuse_weight"],
            address_weight=s["address_weight"],
            linked_orders_24h=f["linked_orders_24h"],
            linked_same_sku_7d=f["linked_same_sku_7d"],
            burst_link_kinds=s["burst_link_kinds"],
            burst_weight=s["burst_weight"],
            prior_suspicious_claims_180d=tab["prior_suspicious_claims_180d"],
        )

    def discounted_links(self, request: ScoreOrderRequest, t0: datetime | None = None) -> list[DiscountedLink]:
        t = self._check_t0(t0, request)
        return list(self._analysis(query_from_request(request), t)[1].discounted)

    def clv_inr(self, account_id: str, t0: datetime) -> float:
        """Point-in-time CLV (policy input, never a model feature)."""
        return clv_inr(self.state, account_id, to_micros(t0), gross_margin_rate=self._margin_rate,
                       floor_inr=self._clv_floor, cap_inr=self._clv_cap)


def build_feature_table(world, policy_config: PolicyConfig | None = None) -> pd.DataFrame:
    """One row per historical order: order_id, split, t0, feature_set_version and every feature."""
    rows = []
    for row in FeatureBuilder(world, policy_config).iter_order_features():
        rows.append({"order_id": row.order_id, "split": row.split, "t0": row.t0,
                     "feature_set_version": definitions.FEATURE_SET_VERSION, **row.features})
    df = pd.DataFrame(rows, columns=["order_id", "split", "t0", "feature_set_version", *definitions.all_features()])
    df["t0"] = pd.to_datetime(df["t0"], utc=True).astype("datetime64[us, UTC]")
    return df
