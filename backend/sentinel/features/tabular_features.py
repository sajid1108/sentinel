"""Order-level and account-history features (§6.2, §6.3), as of t0."""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from sentinel.features.graph_state import MICROS_PER_DAY, GraphState, in_window, visible

RETURN_WINDOW_DAYS = 30               # P5: an order's return history is matured at delivered + 30 d
RETURN_RATE_PRIOR_RETURNS = 2
RETURN_RATE_PRIOR_ORDERS = 10


@dataclass(frozen=True)
class QueryLine:
    sku_id: str
    product_id: str
    variant: str
    category: str
    unit_price_inr: float
    quantity: int


@dataclass(frozen=True)
class OrderQuery:
    """The order at prediction time. Its identifiers are the query keys (§6)."""
    order_id: str
    account_id: str
    placed_at: int                    # microseconds, = t0 for historical replay
    lines: tuple[QueryLine, ...]
    discount_pct: float
    delivery_speed: str
    payment_method: str
    device_id: str | None
    address_id: str | None
    payment_token_id: str | None

    @property
    def skus(self) -> frozenset[str]:
        return frozenset(ln.sku_id for ln in self.lines)

    @property
    def identifiers(self) -> list[tuple[str, str | None]]:
        return [("DEVICE", self.device_id), ("ADDRESS", self.address_id), ("PAYMENT_TOKEN", self.payment_token_id)]


def order_value_inr(q: OrderQuery) -> float:
    """Σ line price x qty x (1 - discount). Client totals are never trusted."""
    return round(sum(ln.unit_price_inr * ln.quantity for ln in q.lines) * (1 - q.discount_pct / 100), 2)


def primary_category(q: OrderQuery) -> str:
    value: dict[str, float] = {}
    for ln in q.lines:
        value[ln.category] = value.get(ln.category, 0.0) + ln.unit_price_inr * ln.quantity
    return max(sorted(value), key=lambda c: value[c])


def n_variants_same_product(q: OrderQuery) -> int:
    variants: dict[str, set[str]] = {}
    for ln in q.lines:
        variants.setdefault(ln.product_id, set()).add(ln.variant)
    return max(len(v) for v in variants.values())


def count_in_window(times: list[int], t0: int, days: float) -> int:
    """Events in [t0 - days, t0) from an ascending list."""
    lo = bisect.bisect_left(times, t0 - int(days * MICROS_PER_DAY))
    hi = bisect.bisect_left(times, t0)
    n = hi - lo
    assert n == sum(1 for t in times[lo:hi] if in_window(t, t0, days))
    return n


def account_age_days(state: GraphState, account_id: str, t0: int) -> float:
    created = state.account_created.get(account_id)
    return 0.0 if created is None else (t0 - created) / MICROS_PER_DAY


def matured_return_rate_smoothed(state: GraphState, account_id: str, t0: int) -> float:
    """(returns + 2) / (matured orders + 10); matured = delivered_at + 30 d < t0 (P5)."""
    acc = state.accounts.get(account_id)
    matured = returns = 0
    for o in acc.orders if acc else ():
        if o.delivered_at is None or not visible(o.delivered_at + RETURN_WINDOW_DAYS * MICROS_PER_DAY, t0):
            continue
        matured += 1
        if visible(o.returned_at, t0) and o.returned_at <= o.delivered_at + RETURN_WINDOW_DAYS * MICROS_PER_DAY:
            returns += 1
    return (returns + RETURN_RATE_PRIOR_RETURNS) / (matured + RETURN_RATE_PRIOR_ORDERS)


def tabular_features(state: GraphState, q: OrderQuery, t0: int) -> dict[str, float | int | str]:
    acc = state.accounts.get(q.account_id)
    prior_orders = sum(1 for o in acc.orders if visible(o.placed_at, t0)) if acc else 0
    return {
        "order_value_inr": order_value_inr(q),
        "primary_category": primary_category(q),
        "discount_pct": float(q.discount_pct),
        "n_items": sum(ln.quantity for ln in q.lines),
        "n_variants_same_product": n_variants_same_product(q),
        "account_age_days": account_age_days(state, q.account_id, t0),
        "prior_orders": prior_orders,
        "matured_return_rate_smoothed": matured_return_rate_smoothed(state, q.account_id, t0),
        "prior_returns_90d": count_in_window(acc.return_times, t0, 90) if acc else 0,
        "delivery_speed": q.delivery_speed,
        "payment_method_cod": int(q.payment_method == "COD"),
        "prior_suspicious_claims_180d": count_in_window(acc.flag_times, t0, 180) if acc else 0,
    }


def clv_inr(state: GraphState, account_id: str, t0: int, *, gross_margin_rate: float,
            floor_inr: float, cap_inr: float) -> float:
    """Point-in-time 36-month expected margin, shrunk toward the new-customer floor (policy input only)."""
    acc = state.accounts.get(account_id)
    tenure_days = max(0.0, account_age_days(state, account_id, t0))
    value = 0.0
    for o in acc.orders if acc else ():
        if not in_window(o.placed_at, t0, 365) or o.delivered_at is None:
            continue
        if not visible(o.delivered_at + RETURN_WINDOW_DAYS * MICROS_PER_DAY, t0):
            continue                                            # not matured
        if visible(o.returned_at, t0):
            continue                                            # returned
        value += o.value_inr
    annual_net_margin = gross_margin_rate * value
    if 0 < tenure_days < 365:
        annual_net_margin *= 365 / tenure_days
    shrink = min(1.0, tenure_days / 365)
    clv = shrink * annual_net_margin * 3 + (1 - shrink) * floor_inr
    return min(max(clv, floor_inr), cap_inr)
