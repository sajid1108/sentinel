"""Incremental point-in-time graph state (§6.1, §7.2 P2-P4, P7).

An undirected NetworkX graph with ACC:, ORD:, DEV:, ADR:, TOK: nodes. Account-identifier edges carry
first_seen, last_seen and n_orders. ORDER nodes are kept for the last 7 days only (temporal features).
"Accounts shared an identifier" is never stored: it is a two-hop ACC-identifier-ACC path.

Outcome events update account state (confirmation time, flagged claims, returns) and order state
(delivery, return). All times are integer microseconds since the Unix epoch (UTC); every comparison
against a prediction time t0 goes through visible().
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import networkx as nx
import pandas as pd

from sentinel.features.identifiers import is_rejected_id

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ONE_MICRO = timedelta(microseconds=1)
MICROS_PER_DAY = 86_400_000_000
MICROS_PER_HOUR = 3_600_000_000

NODE_PREFIX = {"ACCOUNT": "ACC", "ORDER": "ORD", "DEVICE": "DEV", "ADDRESS": "ADR", "PAYMENT_TOKEN": "TOK"}
EDGE_KIND = {"DEVICE": "USED_DEVICE", "PAYMENT_TOKEN": "USED_TOKEN", "ADDRESS": "SHIPPED_TO"}

# §6.1 evidence weight
BASE_RELIABILITY = {"PAYMENT_TOKEN": 0.9, "DEVICE": 0.8, "ADDRESS": 0.4}
HALF_LIFE_DAYS = {"PAYMENT_TOKEN": 60.0, "DEVICE": 30.0, "ADDRESS": 45.0}
SEQUENTIAL_DEVICE_RELIABILITY = 0.2
SEQUENTIAL_IDLE_DAYS = 60
MULTI_TENANT_RELIABILITY = 0.1
HIGH_FANOUT_ACCOUNTS = 25            # an address with more accounts than this in 90 d is excluded
HIGH_FANOUT_WINDOW_DAYS = 90
RELIABLE_MIN_WEIGHT = 0.25
RELIABLE_WINDOW_DAYS = 90
BFS_MAX_ACCOUNTS = 200
ORDER_NODE_WINDOW_DAYS = 7

FLAGGED_CLAIM_EVENTS = frozenset({"CLAIM_FILED", "QC_FLAGGED"})
RETURN_EVENTS = frozenset({"RETURN_REQUESTED", "EXCHANGE_REQUESTED"})


# ── Time ─────────────────────────────────────────────────────────────────────
def to_micros(ts) -> int:
    """Aware datetime or pandas Timestamp -> integer microseconds since the epoch (UTC)."""
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return (ts - EPOCH) // _ONE_MICRO


def from_micros(us: int) -> datetime:
    return EPOCH + timedelta(microseconds=int(us))


def series_to_micros(s: pd.Series) -> list[int | None]:
    utc = s.dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[us]")
    values = utc.astype("int64").tolist()
    return [None if missing else v for v, missing in zip(values, s.isna().tolist())]


def visible(event_ts: int | None, t0: int) -> bool:
    """P3: the only visibility rule. An event is known at t0 only if it happened strictly before t0."""
    return event_ts is not None and event_ts < t0


def in_window(event_ts: int | None, t0: int, days: float) -> bool:
    """event_ts in [t0 - days, t0)."""
    return visible(event_ts, t0) and event_ts >= t0 - int(days * MICROS_PER_DAY)


def age_days(last_seen: int, t0: int) -> float:
    return max(0.0, (t0 - last_seen) / MICROS_PER_DAY)


def decayed_weight(reliability: float, kind: str, last_seen: int, t0: int) -> float:
    """§6.1: w = reliability x 0.5 ** (age_days / half_life)."""
    return reliability * 0.5 ** (age_days(last_seen, t0) / HALF_LIFE_DAYS[kind])


def is_sequential(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Device use (first_seen, last_seen) of two accounts: the earlier user was idle on the device
    for >= 60 days before the later user's first use."""
    prev, new = (a, b) if a[0] <= b[0] else (b, a)
    return prev[1] + SEQUENTIAL_IDLE_DAYS * MICROS_PER_DAY <= new[0]


def node_id(kind: str, ident: str) -> str:
    return f"{NODE_PREFIX[kind]}:{ident}"


# ── State ────────────────────────────────────────────────────────────────────
@dataclass
class OrderRecord:
    order_id: str
    account_id: str
    placed_at: int
    value_inr: float
    skus: frozenset[str]
    delivered_at: int | None = None
    returned_at: int | None = None           # first RETURN_REQUESTED / EXCHANGE_REQUESTED


@dataclass
class AccountState:
    account_id: str
    created_at: int | None
    orders: list[OrderRecord] = field(default_factory=list)    # placement order
    confirmed_at: int | None = None                             # first ABUSE_CONFIRMED on any order (P4)
    confirmation_times: list[int] = field(default_factory=list)  # every ABUSE_CONFIRMED, ascending (evidence only)
    flag_times: list[int] = field(default_factory=list)         # CLAIM_FILED / QC_FLAGGED, ascending
    return_times: list[int] = field(default_factory=list)       # RETURN / EXCHANGE_REQUESTED, ascending


@dataclass(frozen=True)
class IdentifierMeta:
    kind: str
    multi_tenant_set_at: int | None           # trusted only when visible at t0 (P7)
    display_label: str


class GraphState:
    def __init__(self, account_created: dict[str, int], identifiers: dict[str, IdentifierMeta]):
        self.graph = nx.Graph()
        self.account_created = account_created
        self.identifiers = identifiers
        self.accounts: dict[str, AccountState] = {}
        self.orders: dict[str, OrderRecord] = {}
        self._recent_orders: deque[tuple[int, str]] = deque()
        self.last_applied: int | None = None

    # ── lookups ──
    def account(self, account_id: str) -> AccountState:
        acc = self.accounts.get(account_id)
        if acc is None:
            acc = AccountState(account_id, self.account_created.get(account_id))
            self.accounts[account_id] = acc
        return acc

    def meta(self, ident: str, kind: str) -> IdentifierMeta:
        return self.identifiers.get(ident) or IdentifierMeta(kind, None, "")

    def account_edges(self, account_id: str) -> dict[str, dict]:
        """Identifier node -> edge attributes for one account (ORDER edges excluded)."""
        node = node_id("ACCOUNT", account_id)
        if node not in self.graph:
            return {}
        return {n: d for n, d in self.graph.adj[node].items() if not n.startswith("ORD:")}

    def identifier_accounts(self, ident_node: str) -> dict[str, dict]:
        """Account id -> edge attributes for one identifier node."""
        if ident_node not in self.graph:
            return {}
        return {n[4:]: d for n, d in self.graph.adj[ident_node].items()}

    def recent_orders_of(self, account_id: str) -> list[dict]:
        node = node_id("ACCOUNT", account_id)
        if node not in self.graph:
            return []
        return [self.graph.nodes[n] for n in self.graph.adj[node] if n.startswith("ORD:")]

    # ── updates ──
    def _touch(self, ts: int) -> None:
        if self.last_applied is not None and ts < self.last_applied:
            raise ValueError("graph state must be updated in time order")
        self.last_applied = ts

    def add_order(self, order_id: str, account_id: str, placed_at: int, value_inr: float,
                  skus: frozenset[str], identifiers: list[tuple[str, str | None]]) -> None:
        """Add an order's edges. Call only after the order's features have been computed (P2)."""
        self._touch(placed_at)
        acc = self.account(account_id)
        record = OrderRecord(order_id, account_id, placed_at, value_inr, skus)
        acc.orders.append(record)
        self.orders[order_id] = record
        acc_node = node_id("ACCOUNT", account_id)
        self.graph.add_node(acc_node, kind="ACCOUNT")
        for kind, ident in identifiers:
            if ident is None or is_rejected_id(ident):            # placeholders never become nodes
                continue
            ident_node = node_id(kind, ident)
            if ident_node not in self.graph:
                self.graph.add_node(ident_node, kind=kind)
            edge = self.graph.get_edge_data(acc_node, ident_node)
            if edge is None:
                self.graph.add_edge(acc_node, ident_node, kind=EDGE_KIND[kind], first_seen=placed_at,
                                    last_seen=placed_at, n_orders=1)
            else:
                edge["last_seen"] = placed_at
                edge["n_orders"] += 1
        ord_node = node_id("ORDER", order_id)
        self.graph.add_node(ord_node, kind="ORDER", placed_at=placed_at, skus=skus, account_id=account_id)
        self.graph.add_edge(ord_node, acc_node, kind="PLACED_BY", placed_at=placed_at)
        self._recent_orders.append((placed_at, ord_node))
        self._prune(placed_at)

    def _prune(self, now: int) -> None:
        cutoff = now - ORDER_NODE_WINDOW_DAYS * MICROS_PER_DAY
        while self._recent_orders and self._recent_orders[0][0] < cutoff:
            _, node = self._recent_orders.popleft()
            self.graph.remove_node(node)

    def apply_event(self, order_id: str, event_type: str, occurred_at: int) -> None:
        self._touch(occurred_at)
        record = self.orders.get(order_id)
        if record is None:
            return
        acc = self.accounts[record.account_id]
        if event_type == "DELIVERED":
            record.delivered_at = occurred_at
        elif event_type in RETURN_EVENTS:
            acc.return_times.append(occurred_at)
            if record.returned_at is None:
                record.returned_at = occurred_at
        elif event_type in FLAGGED_CLAIM_EVENTS:
            acc.flag_times.append(occurred_at)
        elif event_type == "ABUSE_CONFIRMED":
            acc.confirmation_times.append(occurred_at)
            if acc.confirmed_at is None:
                acc.confirmed_at = occurred_at
