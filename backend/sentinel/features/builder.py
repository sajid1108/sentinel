"""FeatureBuilder: ONE code path for the offline build and for serving (§6, §7.2 P1-P3).

Serving:  builder = FeatureBuilder.replay(world, as_of); builder.features_for_request(request, t0)
Offline:  for row in FeatureBuilder(world).iter_order_features(): ...

Policy inputs (SignalInputs, CLV, raw return history, payment method) come from the same replay. They feed
the policy and the baselines in the backtest and are never model features.

Both drive the same chronological replay. Orders and outcome events are merged by timestamp; at
one timestamp the features of every order placed then are computed first, and only afterwards are
that timestamp's order edges and events applied. So an order never sees its own edges, and state
visible at t0 is exactly what happened strictly before t0.

`world` is any mapping with the tables accounts, identifiers, orders, order_lines, order_events.
Labels and ground truth are never read here (P11).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Iterator

import pandas as pd

from sentinel.api.schemas import DiscountedLink, ScoreOrderRequest
from sentinel.features import definitions
from sentinel.features.graph_features import EgoView, GraphAnalysis, analyse, ego_view
from sentinel.features.graph_state import (GraphState, IdentifierMeta, from_micros, series_to_micros,
                                           to_micros, visible)
from sentinel.features.tabular_features import (OrderQuery, QueryLine, clv_inr, matured_return_counts,
                                                order_value_inr, tabular_features)
from sentinel.policy.config import PolicyConfig, load_policy_config
from sentinel.policy.guardrails import SignalInputs

WORLD_TABLES = ("accounts", "identifiers", "orders", "order_lines", "order_events")
_END = float("inf")

# One row per order in policy_inputs.parquet: policy and baseline inputs, never model features.
SIGNAL_INPUT_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(SignalInputs))
POLICY_INPUT_COLUMNS: tuple[str, ...] = (*SIGNAL_INPUT_COLUMNS, "clv_inr", "graph_state_as_of", "matured_return_rate",
                                         "matured_returns", "payment_method", "order_value_inr")
# Evidence-only values for reviewer text (#28), written beside the policy inputs. Neither a model feature
# nor a policy input: definitions.py never lists them and nothing in policy/ reads them.
EVIDENCE_COLUMNS: tuple[str, ...] = ("device_confirmed_peer_count", "device_most_recent_confirmation_days")


@dataclass(frozen=True)
class OrderFeatures:
    order_id: str
    split: str | None
    t0: datetime
    features: dict[str, float | int | str]
    policy_inputs: dict | None = None


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

    def iter_order_features(self, policy_inputs: bool = False) -> Iterator[OrderFeatures]:
        """Offline entry point: every historical order's features (and optionally its policy inputs)
        as of its own placed_at."""
        for t, q, split, features in self._run(until=None, compute=True):
            inputs = self._policy_inputs(q, t) if policy_inputs else None
            yield OrderFeatures(q.order_id, split, from_micros(t), features, inputs)

    def iter_points_in_time(self, order_ids) -> Iterator[tuple[OrderQuery, int]]:
        """Replay once; pause at each wanted historical order at its own t0, before its edges and that
        timestamp's events are applied, so `self.state` holds exactly what was visible then (#32)."""
        wanted = frozenset(order_ids)
        for t, q, _, _ in self._run(until=None, compute=False, visit=wanted):
            yield q, t

    def _run(self, until: int | None, compute: bool, visit: frozenset[str] | None = None):
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
            elif visit is not None:
                for _, q, split in batch:
                    if q.order_id in visit:
                        yield t, q, split, None
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
        return self._signal_inputs(query_from_request(request), t)

    def _signal_inputs(self, q: OrderQuery, t0: int) -> SignalInputs:
        tab, graph = self._analysis(q, t0)
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

    def _policy_inputs(self, q: OrderQuery, t0: int) -> dict:
        inputs = asdict(self._signal_inputs(q, t0))
        inputs["burst_link_kinds"] = sorted(inputs["burst_link_kinds"])
        returns, matured = matured_return_counts(self.state, q.account_id, t0)
        row = {**inputs,
               "clv_inr": clv_inr(self.state, q.account_id, t0, gross_margin_rate=self._margin_rate,
                                  floor_inr=self._clv_floor, cap_inr=self._clv_cap),
               "graph_state_as_of": from_micros(t0),       # offline replay: state holds everything before t0
               "matured_return_rate": returns / matured if matured else None,
               "matured_returns": returns,
               "payment_method": q.payment_method,
               "order_value_inr": order_value_inr(q),
               **self._analysis(q, t0)[1].evidence}
        return {name: row[name] for name in (*POLICY_INPUT_COLUMNS, *EVIDENCE_COLUMNS)}

    def evidence_values(self, request: ScoreOrderRequest, t0: datetime | None = None) -> dict:
        """Reviewer evidence for the query order (EVIDENCE_COLUMNS). Never a model feature (#28)."""
        t = self._check_t0(t0, request)
        return dict(self._analysis(query_from_request(request), t)[1].evidence)

    def discounted_links(self, request: ScoreOrderRequest, t0: datetime | None = None) -> list[DiscountedLink]:
        t = self._check_t0(t0, request)
        return list(self._analysis(query_from_request(request), t)[1].discounted)

    def discounted_links_at(self, q: OrderQuery, t0: int) -> list[DiscountedLink]:
        """Discounted links for a historical order paused by iter_points_in_time (seeding, #32)."""
        return list(self._analysis(q, t0)[1].discounted)

    def ego_view(self, q: OrderQuery, t0: int) -> EgoView:
        """The reviewer graph's raw material for `q` as of t0 (#32). State must hold nothing at or after t0."""
        if self.state.last_applied is not None and not visible(self.state.last_applied, t0):
            raise ValueError("graph state already contains events at or after t0; replay to an earlier time")
        return ego_view(self.state, q, t0)

    def clv_inr(self, account_id: str, t0: datetime) -> float:
        """Point-in-time CLV (policy input, never a model feature)."""
        return clv_inr(self.state, account_id, to_micros(t0), gross_margin_rate=self._margin_rate,
                       floor_inr=self._clv_floor, cap_inr=self._clv_cap)


def _utc(values) -> pd.Series:
    return pd.to_datetime(values, utc=True).astype("datetime64[us, UTC]")


def build_tables(world, policy_config: PolicyConfig | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One replay, two tables with one row per historical order:
    features (order_id, split, t0, feature_set_version, every feature) and
    policy inputs (order_id, split, t0, POLICY_INPUT_COLUMNS, then the evidence-only EVIDENCE_COLUMNS)."""
    feature_rows, policy_rows = [], []
    for row in FeatureBuilder(world, policy_config).iter_order_features(policy_inputs=True):
        feature_rows.append({"order_id": row.order_id, "split": row.split, "t0": row.t0,
                             "feature_set_version": definitions.FEATURE_SET_VERSION, **row.features})
        policy_rows.append({"order_id": row.order_id, "split": row.split, "t0": row.t0, **row.policy_inputs})
    features = pd.DataFrame(feature_rows,
                            columns=["order_id", "split", "t0", "feature_set_version", *definitions.all_features()])
    features["t0"] = _utc(features["t0"])
    policy = pd.DataFrame(policy_rows, columns=["order_id", "split", "t0", *POLICY_INPUT_COLUMNS, *EVIDENCE_COLUMNS])
    for column in ("t0", "graph_state_as_of"):
        policy[column] = _utc(policy[column])
    policy["matured_return_rate"] = policy["matured_return_rate"].astype("float64")
    policy["device_most_recent_confirmation_days"] = policy["device_most_recent_confirmation_days"].astype("float64")
    return features, policy


def build_feature_table(world, policy_config: PolicyConfig | None = None) -> pd.DataFrame:
    return build_tables(world, policy_config)[0]


def signal_inputs_from_row(row) -> SignalInputs:
    """Rebuild SignalInputs from one policy_inputs.parquet row (any mapping)."""
    defaults = SignalInputs()
    values = {}
    for name in SIGNAL_INPUT_COLUMNS:
        default = getattr(defaults, name)
        if isinstance(default, frozenset):
            values[name] = frozenset(row[name])
        else:
            values[name] = type(default)(row[name])
    return SignalInputs(**values)
