"""Relationship features (§6.1, §6.3) and the evidence the policy needs (§9.2), as of t0.

One GraphAnalysis per (order, t0). The order's own identifiers are the query keys: the account's
use of them is treated as happening at t0 (age 0), but they are never written to the graph here.
Two accounts are linked through an identifier as a two-hop path; the link weight is the other
account's edge weight (reliability x decay), with sequential device use at 0.2 and multi-tenant
addresses at 0.1. Neighbour abuse counts only use confirmations visible at t0 (P4, P10), and only
those of OTHER accounts: the query account's own confirmation never counts as graph evidence.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sentinel.api.schemas import DiscountedLink
from sentinel.features.graph_state import (BASE_RELIABILITY, BFS_MAX_ACCOUNTS, HIGH_FANOUT_ACCOUNTS,
                                           HIGH_FANOUT_WINDOW_DAYS, MICROS_PER_DAY, MULTI_TENANT_RELIABILITY,
                                           RELIABLE_MIN_WEIGHT, RELIABLE_WINDOW_DAYS,
                                           SEQUENTIAL_DEVICE_RELIABILITY, GraphState, decayed_weight, in_window,
                                           is_sequential, node_id, visible)
from sentinel.features.identifiers import is_rejected_id
from sentinel.features.tabular_features import OrderQuery, count_in_window

DEVICE_OTHER_ACCOUNTS_CAP = 25
PROXIMITY_MAX_HOPS = 6
HOUSEHOLD_MAX_OTHER_ACCOUNTS = 3
COMPONENT_PRIOR_CONFIRMED = 1
COMPONENT_PRIOR_ACCOUNTS = 10
KIND_OF_PREFIX = {"DEV": "DEVICE", "ADR": "ADDRESS", "TOK": "PAYMENT_TOKEN"}


@dataclass(frozen=True)
class Link:
    """Another account's use of one identifier, seen from the query account at t0."""
    account_id: str
    kind: str
    ident_node: str
    first_seen: int
    last_seen: int
    reliability: float
    weight: float
    sequential: bool
    confirmed: bool              # ABUSE_CONFIRMED visible at t0


@dataclass
class Reached:
    depth: int                   # account hops from the query account
    kinds: frozenset[str]        # identifier kinds on the BFS path
    bottleneck: float            # smallest edge weight on the BFS path
    via_account: str | None = None   # the account this one was first reached from
    via_ident: str | None = None     # the identifier node that link goes through


@dataclass
class GraphAnalysis:
    features: dict[str, float | int]
    signal_fields: dict = field(default_factory=dict)
    discounted: list[DiscountedLink] = field(default_factory=list)
    component: dict[str, Reached] = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)      # reviewer evidence only, never model features (#28)


class _Context:
    def __init__(self, state: GraphState, q: OrderQuery, t0: int):
        self.state, self.q, self.t0 = state, q, t0
        self.account = q.account_id
        self._fanout: dict[str, bool] = {}
        # the query account's identifier uses: existing edges plus the order's own identifiers at t0
        self.self_edges: dict[str, tuple[int, int]] = {
            n: (d["first_seen"], d["last_seen"]) for n, d in state.account_edges(self.account).items()}
        self.query_nodes: list[tuple[str, str]] = []
        for kind, ident in q.identifiers:
            if ident is None or is_rejected_id(ident):
                continue
            n = node_id(kind, ident)
            first = self.self_edges.get(n, (t0, t0))[0]
            self.self_edges[n] = (first, t0)
            self.query_nodes.append((kind, n))

    # ── identifier context ──
    def multi_tenant(self, n: str) -> bool:
        if not n.startswith("ADR:"):
            return False
        return visible(self.state.meta(n[4:], "ADDRESS").multi_tenant_set_at, self.t0)       # P7

    def high_fanout(self, n: str) -> bool:
        if not n.startswith("ADR:"):
            return False
        if n not in self._fanout:
            accounts = {a for a, d in self.state.identifier_accounts(n).items()
                        if in_window(d["last_seen"], self.t0, HIGH_FANOUT_WINDOW_DAYS)}
            if n in self.self_edges:
                accounts.add(self.account)
            self._fanout[n] = len(accounts) > HIGH_FANOUT_ACCOUNTS
        return self._fanout[n]

    def edges_of(self, account_id: str) -> dict[str, tuple[int, int]]:
        if account_id == self.account:
            return self.self_edges
        return {n: (d["first_seen"], d["last_seen"]) for n, d in self.state.account_edges(account_id).items()}

    def reliability(self, kind: str, n: str, sequential: bool) -> float:
        if kind == "DEVICE" and sequential:
            return SEQUENTIAL_DEVICE_RELIABILITY
        if kind == "ADDRESS" and self.multi_tenant(n):
            return MULTI_TENANT_RELIABILITY
        return BASE_RELIABILITY[kind]

    def confirmed(self, account_id: str) -> bool:
        acc = self.state.accounts.get(account_id)
        return acc is not None and visible(acc.confirmed_at, self.t0)                     # P4

    def links(self, n: str, from_account: str | None = None) -> list[Link]:
        """Other accounts on identifier n, seen from from_account (default: the query account)."""
        source = from_account or self.account
        kind = KIND_OF_PREFIX[n[:3]]
        own = self.edges_of(source).get(n)
        out = []
        for other, d in sorted(self.state.identifier_accounts(n).items()):
            if other == source:
                continue
            use = (d["first_seen"], d["last_seen"])
            if other == self.account:
                use = self.self_edges.get(n, use)
            sequential = kind == "DEVICE" and own is not None and is_sequential(own, use)
            rel = self.reliability(kind, n, sequential)
            out.append(Link(other, kind, n, use[0], use[1], rel,
                            decayed_weight(rel, kind, use[1], self.t0), sequential, self.confirmed(other)))
        return out

    def reliable(self, kind: str, n: str, last_seen: int, weight: float) -> bool:
        if self.multi_tenant(n) or self.high_fanout(n):
            return False
        # last_seen <= t0 always: graph edges are visible, and the query's own uses are at t0
        return weight >= RELIABLE_MIN_WEIGHT and last_seen >= self.t0 - RELIABLE_WINDOW_DAYS * MICROS_PER_DAY


def _component(ctx: _Context) -> dict[str, Reached]:
    """BFS over the reliable subgraph from the query account, capped at 200 accounts (§6.1)."""
    reached = {ctx.account: Reached(0, frozenset(), 1.0)}
    queue = deque([ctx.account])
    while queue:
        a = queue.popleft()
        here = reached[a]
        for n, (first, last) in sorted(ctx.edges_of(a).items()):
            kind = KIND_OF_PREFIX[n[:3]]
            w_a = decayed_weight(BASE_RELIABILITY[kind] if not (kind == "ADDRESS" and ctx.multi_tenant(n))
                                 else MULTI_TENANT_RELIABILITY, kind, last, ctx.t0)
            if not ctx.reliable(kind, n, last, w_a):
                continue
            for link in ctx.links(n, from_account=a):
                if link.account_id in reached or link.sequential:
                    continue
                if not ctx.reliable(kind, n, link.last_seen, link.weight):
                    continue
                if len(reached) >= BFS_MAX_ACCOUNTS:
                    return reached
                reached[link.account_id] = Reached(here.depth + 1, here.kinds | {kind},
                                                   min(here.bottleneck, w_a, link.weight),
                                                   via_account=a, via_ident=n)
                queue.append(link.account_id)
    return reached


def _discounted_link(ctx: _Context, kind: str, n: str, links: list[Link]) -> DiscountedLink | None:
    """At most one discount per identifier, by precedence."""
    if not links:
        return None
    label = ctx.state.meta(n[4:], kind).display_label
    strongest = max(link.weight for link in links)

    def record(reason: str, weight: float) -> DiscountedLink:
        return DiscountedLink(identifier_label=label, kind=kind, reason=reason, weight=round(weight, 4))

    if kind == "ADDRESS":
        if ctx.high_fanout(n):
            return record("HIGH_FANOUT_IDENTIFIER", 0.0)
        if ctx.multi_tenant(n):
            return record("MULTI_TENANT_ADDRESS", strongest)
        if len(links) <= HOUSEHOLD_MAX_OTHER_ACCOUNTS and not any(link.confirmed for link in links):
            return record("HOUSEHOLD_PATTERN", strongest)
    if kind == "DEVICE":
        sequential = [link for link in links if link.sequential]
        if sequential:
            return record("SEQUENTIAL_DEVICE_USE", max(link.weight for link in sequential))
    stale = [link for link in links if link.reliability >= RELIABLE_MIN_WEIGHT and link.weight < RELIABLE_MIN_WEIGHT]
    if stale:
        return record("STALE_RELATIONSHIP", max(link.weight for link in stale))
    return None


@dataclass(frozen=True)
class IdentifierView:
    """One of the query order's identifiers and every other account's use of it, as of t0."""
    kind: str
    node: str
    label: str                   # masked display label from the identifiers table
    multi_tenant: bool           # flag set before t0 (P7)
    high_fanout: bool
    own_reliability: float       # the query account's own edge (age 0 at t0)
    links: tuple[Link, ...]
    discount: DiscountedLink | None


@dataclass(frozen=True)
class PathEdge:
    """One account's use of one identifier on a reliable path from the query account to an account the
    reviewer graph must draw (Phase 8 brief 1.1). Only hops beyond the query order's own identifiers
    appear here; the query order's identifiers are already in `EgoView.identifiers`."""
    account_id: str
    kind: str
    ident_node: str
    ident_label: str
    multi_tenant: bool
    high_fanout: bool
    last_seen: int
    reliability: float
    weight: float
    confirmed: bool              # the account holding this edge, confirmed before t0
    discount_reason: str | None  # None when the edge counts as evidence


@dataclass(frozen=True)
class EgoView:
    """What the reviewer graph (api/services/graph_view.py) is drawn from: the query order's identifiers,
    the accounts linked through them, the orders of reliable-component accounts in [t0 - 24 h, t0), and
    which accounts sit in the reliable component. Point-in-time: only state visible at t0.

    `must_draw`, `path_edges` and `depth_of` carry the accounts whose evidence is counted next to the
    graph — every account behind `linked_orders_24h` and every account behind `device_confirmed_peer_count` —
    together with the identifier hops that connect them, even two account hops out (Phase 8 brief 1.1)."""
    identifiers: tuple[IdentifierView, ...]
    component: frozenset[str]
    recent_orders: dict[str, tuple[tuple[str, int], ...]]      # account -> ((order_id, placed_at), ...)
    depth_of: dict[str, int]                                   # component account -> account hops from the query
    parent_of: dict[str, tuple[str, str]]                      # account -> (account it was reached from, identifier)
    path_edges: tuple[PathEdge, ...]
    must_draw: frozenset[str]                                  # accounts that outrank unrelated ones under the cap
    confirmed_device_peers: frozenset[str]                     # counted in device_confirmed_peer_count


def _path_edge(ctx: _Context, account_id: str, ident_node: str) -> PathEdge:
    """One endpoint of a reliable component hop. The BFS never crosses a sequential device link, a
    multi-tenant or high-fanout address, or a stale edge, so these edges count as evidence; the same
    precedence is applied here rather than assumed."""
    kind = KIND_OF_PREFIX[ident_node[:3]]
    last_seen = ctx.edges_of(account_id)[ident_node][1]
    reliability = ctx.reliability(kind, ident_node, False)
    weight = decayed_weight(reliability, kind, last_seen, ctx.t0)
    if ctx.high_fanout(ident_node):
        reason = "HIGH_FANOUT_IDENTIFIER"
    elif ctx.multi_tenant(ident_node):
        reason = "MULTI_TENANT_ADDRESS"
    elif not ctx.reliable(kind, ident_node, last_seen, weight):
        reason = "STALE_RELATIONSHIP"
    else:
        reason = None
    return PathEdge(account_id, kind, ident_node, ctx.state.meta(ident_node[4:], kind).display_label,
                    ctx.multi_tenant(ident_node), ctx.high_fanout(ident_node), last_seen, reliability, weight,
                    ctx.confirmed(account_id), reason)


def ego_view(state: GraphState, q: OrderQuery, t0: int) -> EgoView:
    ctx = _Context(state, q, t0)
    views = []
    for kind, n in ctx.query_nodes:
        links = tuple(link for link in ctx.links(n) if visible(link.first_seen, t0))
        views.append(IdentifierView(
            kind=kind, node=n, label=state.meta(n[4:], kind).display_label, multi_tenant=ctx.multi_tenant(n),
            high_fanout=ctx.high_fanout(n), own_reliability=ctx.reliability(kind, n, False), links=links,
            discount=_discounted_link(ctx, kind, n, list(links))))
    component = _component(ctx)

    # Every order counted in linked_orders_24h: reliable-component accounts other than the query account
    # (the same set `analyse` counts), not only the directly linked ones.
    recent: dict[str, tuple[tuple[str, int], ...]] = {}
    for a in sorted(component):
        if a == ctx.account:
            continue
        node = node_id("ACCOUNT", a)
        if node not in state.graph:
            continue
        orders = sorted((o[4:], d["placed_at"]) for o, d in state.graph.adj[node].items()
                        if o.startswith("ORD:") and in_window(d["placed_at"], t0, 1))
        if orders:
            recent[a] = tuple(orders)

    device_links = [link for v in views if v.kind == "DEVICE" for link in v.links]
    confirmed_peers = frozenset(link.account_id for link in device_links if link.confirmed)

    # Walk each required account back to the query account, collecting the hops the graph must draw. A hop
    # through one of the query order's own identifiers is already drawn from `identifiers`; any other hop -
    # an account reached two hops out, or one sharing a token this account used on an earlier order - needs
    # its identifier node and both endpoints' edges.
    query_idents = {n for _, n in ctx.query_nodes}
    must_draw = (set(recent) | set(confirmed_peers)) - {ctx.account}
    path_edges: dict[tuple[str, str], PathEdge] = {}
    pending = sorted(a for a in must_draw if a in component)
    while pending:
        a = pending.pop()
        parent, ident = component[a].via_account, component[a].via_ident
        if parent is None or ident is None:
            continue
        if ident not in query_idents:
            for holder in (parent, a):
                if (holder, ident) not in path_edges:
                    path_edges[(holder, ident)] = _path_edge(ctx, holder, ident)
        if parent != ctx.account and parent not in must_draw:
            must_draw.add(parent)
            pending.append(parent)

    return EgoView(tuple(views), frozenset(component), recent,
                   {a: r.depth for a, r in component.items()},
                   {a: (r.via_account, r.via_ident) for a, r in component.items()
                    if r.via_account is not None and r.via_ident is not None},
                   tuple(sorted(path_edges.values(), key=lambda e: (e.ident_node, e.account_id))),
                   frozenset(must_draw), confirmed_peers)


def analyse(state: GraphState, q: OrderQuery, t0: int) -> GraphAnalysis:
    ctx = _Context(state, q, t0)
    by_kind: dict[str, tuple[str, list[Link]]] = {kind: (n, ctx.links(n)) for kind, n in ctx.query_nodes}

    # device
    device_links = by_kind.get("DEVICE", (None, []))[1]
    device_other = len({link.account_id for link in device_links
                        if not link.sequential and in_window(link.last_seen, t0, 30)})
    device_confirmed_weight = sum(link.weight for link in device_links if link.confirmed)
    # Evidence for the reviewer text, not features: how many other accounts on this device were confirmed
    # before t0, and how long ago the most recent of those confirmations was (#28).
    confirmed_peers = {link.account_id for link in device_links if link.confirmed}
    latest_confirmation = max((t for a in confirmed_peers for t in state.accounts[a].confirmation_times
                               if visible(t, t0)), default=None)

    # payment token (COD: the account's prior tokens)
    if "PAYMENT_TOKEN" in by_kind:
        token_links = by_kind["PAYMENT_TOKEN"][1]
    else:
        token_links = [link for n in sorted(ctx.self_edges) if n.startswith("TOK:") for link in ctx.links(n)]
    token_other = len({link.account_id for link in token_links if in_window(link.last_seen, t0, 30)})

    # address (high-fanout addresses carry no weight)
    address_node, address_links = by_kind.get("ADDRESS", (None, []))
    fanout = address_node is not None and ctx.high_fanout(address_node)
    address_weighted = 0.0 if fanout else sum(link.weight for link in address_links
                                              if in_window(link.last_seen, t0, 30))
    address_confirmed_weight = 0.0 if fanout else sum(link.weight for link in address_links if link.confirmed)

    # reliable component. The query account's own confirmation is account history, not graph
    # evidence: it is left out of the confirmed count (the component size still includes the account).
    component = _component(ctx)
    size = min(len(component), BFS_MAX_ACCOUNTS)
    confirmed = sorted(a for a in component if a != ctx.account and ctx.confirmed(a))
    hops = [component[a].depth for a in confirmed if component[a].depth <= PROXIMITY_MAX_HOPS]
    proximity = 1.0 / (1 + min(hops)) if hops else 0.0

    skus = q.skus
    orders_24h = same_sku_7d = 0
    burst_kinds: set[str] = set()
    burst_weight = 0.0
    recent_claims = 0
    for a in sorted(component):
        acc = state.accounts.get(a)
        if acc is not None:
            recent_claims += count_in_window(acc.flag_times, t0, 30)
        if a == ctx.account:
            continue
        contributes = False
        for o in state.recent_orders_of(a):
            if in_window(o["placed_at"], t0, 1):                 # [t0 - 24 h, t0)
                orders_24h += 1
                contributes = True
            if in_window(o["placed_at"], t0, 7) and o["skus"] & skus:
                same_sku_7d += 1
                contributes = True
        if contributes:
            burst_kinds |= component[a].kinds
            burst_weight = max(burst_weight, component[a].bottleneck)

    reuse = 0
    for _, n in ctx.query_nodes:
        reuse += sum(1 for d in state.identifier_accounts(n).values() if in_window(d["first_seen"], t0, 7))
    device_node = by_kind.get("DEVICE", (None, None))[0]
    new_device = int(device_node is None or device_node not in state.account_edges(ctx.account))

    features = {
        "device_other_accounts_30d": min(device_other, DEVICE_OTHER_ACCOUNTS_CAP),
        "device_confirmed_abuse_weight": device_confirmed_weight,
        "token_other_accounts_30d": token_other,
        "address_other_accounts_weighted_30d": address_weighted,
        "component_size_reliable_90d": size,
        "component_abuse_ratio_smoothed": (len(confirmed) + COMPONENT_PRIOR_CONFIRMED) / (size + COMPONENT_PRIOR_ACCOUNTS),
        "confirmed_abuse_proximity": proximity,
        "linked_orders_24h": orders_24h,
        "linked_same_sku_7d": same_sku_7d,
        "identifier_reuse_velocity_7d": reuse,
        "component_recent_claims_30d": recent_claims,
        "new_device_for_account": new_device,
    }
    signal_fields = {
        "device_weight": max((link.weight for link in device_links), default=0.0),
        "token_weight": max((link.weight for link in token_links), default=0.0),
        "address_is_multi_tenant": address_node is not None and ctx.multi_tenant(address_node),
        "address_confirmed_abuse_weight": address_confirmed_weight,
        "address_weight": 0.0 if fanout else max((link.weight for link in address_links), default=0.0),
        "burst_link_kinds": frozenset(burst_kinds),
        "burst_weight": burst_weight,
    }
    discounted = [d for kind in ("DEVICE", "ADDRESS", "PAYMENT_TOKEN") if kind in by_kind
                  for d in [_discounted_link(ctx, kind, *by_kind[kind])] if d is not None]
    evidence = {
        "device_confirmed_peer_count": len(confirmed_peers),
        "device_most_recent_confirmation_days":
            None if latest_confirmation is None else (t0 - latest_confirmation) / MICROS_PER_DAY,
    }
    return GraphAnalysis(features, signal_fields, discounted, component, evidence)
