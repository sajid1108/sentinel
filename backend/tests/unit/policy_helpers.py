"""Builders shared by the policy tests. Time is anchored to DEMO_CLOCK, never the wall clock."""
from datetime import datetime, timedelta

from sentinel.policy.engine import DecisionContext
from sentinel.policy.guardrails import SignalInputs, corroborating_signals
from sentinel.settings import DEMO_CLOCK

VIA_DEVICE_AND_TOKEN = frozenset({"DEVICE", "PAYMENT_TOKEN"})

DEMO_1 = dict(order_value_inr=4500, clv_inr=30000)
DEMO_2 = dict(order_value_inr=24000, clv_inr=2000)
DEMO_3 = dict(order_value_inr=12000, clv_inr=15000)

DEVICE = SignalInputs(device_confirmed_abuse_weight=1.5, device_other_accounts_30d=5, device_weight=0.75)
DEMO_2_SIGNALS = SignalInputs(
    device_confirmed_abuse_weight=1.5, device_other_accounts_30d=5, device_weight=0.75,
    token_other_accounts_30d=3, token_weight=0.8,
    linked_orders_24h=4, linked_same_sku_7d=3, burst_link_kinds=VIA_DEVICE_AND_TOKEN, burst_weight=0.7,
)
DEMO_3_SIGNALS = SignalInputs(prior_suspicious_claims_180d=1)

_FRESH = object()


def ctx(p_abuse: float | None, order_value_inr: float, clv_inr: float, signals: SignalInputs = SignalInputs(),
        p_return: float | None = 0.3, decided_at: datetime = DEMO_CLOCK, graph_state_as_of=_FRESH,
        degraded: bool = False) -> DecisionContext:
    """graph_state_as_of defaults to 5 minutes before decided_at (fresh)."""
    if graph_state_as_of is _FRESH:
        graph_state_as_of = decided_at - timedelta(minutes=5)
    return DecisionContext(
        p_abuse=p_abuse, p_return=p_return, order_value_inr=order_value_inr, clv_inr=clv_inr,
        signals=tuple(corroborating_signals(signals)), decided_at=decided_at,
        graph_state_as_of=graph_state_as_of, degraded=degraded,
    )


def degraded_ctx(order_value_inr: float, graph_state_as_of=None) -> DecisionContext:
    return ctx(None, order_value_inr=order_value_inr, clv_inr=2000, p_return=None,
               graph_state_as_of=graph_state_as_of, degraded=True)


def by_action(decision):
    return {c.action: c for c in decision.costs}
