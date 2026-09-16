"""§9.2 signals and §9.3 guardrails G1-G6."""
from datetime import timedelta

import pytest

from sentinel.api.schemas import Action
from sentinel.policy.config import load_policy_config
from sentinel.policy.engine import decide
from sentinel.policy.guardrails import SignalInputs, corroborating_signals
from sentinel.settings import DEMO_CLOCK

from .policy_helpers import DEMO_2, DEMO_3, DEVICE, VIA_DEVICE_AND_TOKEN, by_action, ctx, degraded_ctx

CFG = load_policy_config()


def _present(inputs: SignalInputs) -> set[str]:
    return {s.signal for s in corroborating_signals(inputs) if s.present}


def _counted(inputs: SignalInputs) -> set[str]:
    return {s.signal for s in corroborating_signals(inputs) if s.counts_for_corroboration}


def _block_feasible(decision) -> bool:
    return by_action(decision)[Action.BLOCK].feasible


# ── §9.2 signal derivation ──────────────────────────────────────────────────
@pytest.mark.parametrize("inputs, present, counted", [
    (SignalInputs(), set(), set()),
    (SignalInputs(device_confirmed_abuse_weight=0.3), {"DEVICE"}, {"DEVICE"}),
    (SignalInputs(device_confirmed_abuse_weight=0.29, device_other_accounts_30d=2), set(), set()),
    (SignalInputs(device_other_accounts_30d=3), {"DEVICE"}, {"DEVICE"}),
    (SignalInputs(token_other_accounts_30d=2), {"PAYMENT_TOKEN"}, {"PAYMENT_TOKEN"}),
    (SignalInputs(address_confirmed_abuse_weight=0.3), {"ADDRESS"}, {"ADDRESS"}),
    (SignalInputs(address_confirmed_abuse_weight=0.9, address_is_multi_tenant=True), {"ADDRESS"}, set()),
    (SignalInputs(linked_orders_24h=3, burst_link_kinds=frozenset({"DEVICE"})), {"TEMPORAL_BURST"}, {"TEMPORAL_BURST"}),
    (SignalInputs(linked_same_sku_7d=2, burst_link_kinds=frozenset({"PAYMENT_TOKEN"})),
     {"TEMPORAL_BURST"}, {"TEMPORAL_BURST"}),
    (SignalInputs(linked_orders_24h=9, burst_link_kinds=frozenset({"ADDRESS"})), {"TEMPORAL_BURST"}, set()),
    (SignalInputs(prior_suspicious_claims_180d=1), {"ACCOUNT_CLAIMS"}, {"ACCOUNT_CLAIMS"}),
])
def test_signal_presence_and_counting(inputs, present, counted):
    assert _present(inputs) == present
    assert _counted(inputs) == counted


def test_non_present_signals_have_zero_weight_and_do_not_count():
    for s in corroborating_signals(SignalInputs(device_weight=0.9, address_weight=0.9)):
        assert (s.present, s.counts_for_corroboration, s.weight) == (False, False, 0.0)


def test_signals_always_listed_in_order():
    names = [s.signal for s in corroborating_signals(SignalInputs())]
    assert names == ["DEVICE", "PAYMENT_TOKEN", "ADDRESS", "TEMPORAL_BURST", "ACCOUNT_CLAIMS"]


# ── G1 ──────────────────────────────────────────────────────────────────────
def test_g1_invariance_over_p_return():
    for i in range(21):
        p = round(i * 0.05, 2)
        decisions = [decide(ctx(p, **DEMO_3, signals=DEVICE, p_return=r), CFG) for r in (0.0, 0.5, 0.99)]
        assert decisions[0].selected_action == decisions[1].selected_action == decisions[2].selected_action
        assert decisions[0].costs == decisions[1].costs == decisions[2].costs
        assert decisions[0] == decisions[1] == decisions[2]
        g1 = decisions[0].guardrails[0]
        assert (g1.guardrail_id, g1.triggered, g1.removed_actions) == ("G1", False, [])


# ── G2 ──────────────────────────────────────────────────────────────────────
def test_g2_device_only_blocks_block():
    d = decide(ctx(0.95, **DEMO_2, signals=DEVICE), CFG)
    assert not _block_feasible(d)
    assert by_action(d)[Action.BLOCK].excluded_by == ["G2"]


def test_g2_address_plus_burst_via_address_blocks_block():
    signals = SignalInputs(address_confirmed_abuse_weight=0.9, address_weight=0.4,
                           linked_orders_24h=5, linked_same_sku_7d=3,
                           burst_link_kinds=frozenset({"ADDRESS"}), burst_weight=0.4)
    d = decide(ctx(0.95, **DEMO_2, signals=signals), CFG)
    assert not _block_feasible(d)
    assert "G2" in by_action(d)[Action.BLOCK].excluded_by


def test_g2_address_and_burst_without_anchor_blocks_block():
    """Even if the burst counted, ADDRESS + TEMPORAL_BURST has no DEVICE/PAYMENT_TOKEN/ACCOUNT_CLAIMS anchor."""
    signals = SignalInputs(address_confirmed_abuse_weight=0.9, address_weight=0.4,
                           linked_orders_24h=5, burst_link_kinds=VIA_DEVICE_AND_TOKEN, burst_weight=0.6)
    d = decide(ctx(0.95, **DEMO_2, signals=signals), CFG)
    assert _present(signals) == {"ADDRESS", "TEMPORAL_BURST"}
    assert by_action(d)[Action.BLOCK].excluded_by == ["G2"]


def test_g2_device_plus_token_permits_block():
    signals = SignalInputs(device_confirmed_abuse_weight=1.5, device_weight=0.75,
                           token_other_accounts_30d=3, token_weight=0.8)
    d = decide(ctx(0.95, **DEMO_2, signals=signals), CFG)
    assert _block_feasible(d)
    assert d.selected_action is Action.BLOCK


# ── G3 ──────────────────────────────────────────────────────────────────────
def test_g3_three_signals_below_confidence_blocks_block():
    signals = SignalInputs(device_confirmed_abuse_weight=1.5, device_weight=0.75,
                           token_other_accounts_30d=3, token_weight=0.8,
                           prior_suspicious_claims_180d=2)
    d = decide(ctx(0.69, **DEMO_2, signals=signals), CFG)
    assert not _block_feasible(d)
    assert by_action(d)[Action.BLOCK].excluded_by == ["G3"]


# ── G4 ──────────────────────────────────────────────────────────────────────
def test_g4_weak_signals_block_block():
    signals = SignalInputs(device_confirmed_abuse_weight=0.5, device_weight=0.2,
                           token_other_accounts_30d=3, token_weight=0.1)
    d = decide(ctx(0.95, **DEMO_2, signals=signals), CFG)
    assert by_action(d)[Action.BLOCK].excluded_by == ["G4"]


def test_g4_stale_graph_blocks_block():
    stale = DEMO_CLOCK - timedelta(hours=25)
    signals = SignalInputs(device_confirmed_abuse_weight=1.5, device_weight=0.75,
                           token_other_accounts_30d=3, token_weight=0.8)
    d = decide(ctx(0.95, **DEMO_2, signals=signals, graph_state_as_of=stale), CFG)
    assert by_action(d)[Action.BLOCK].excluded_by == ["G4"]


# ── G5 ──────────────────────────────────────────────────────────────────────
def test_g5_high_exposure_removes_allow():
    d = decide(ctx(0.45, **DEMO_3), CFG)
    assert not by_action(d)[Action.ALLOW].feasible
    assert by_action(d)[Action.ALLOW].excluded_by == ["G5"]


@pytest.mark.parametrize("p, v", [(0.39, 12000), (0.45, 9999)])
def test_g5_not_triggered_below_thresholds(p, v):
    d = decide(ctx(p, order_value_inr=v, clv_inr=15000), CFG)
    assert by_action(d)[Action.ALLOW].feasible


# ── G6 ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v", [100, 4999, 5000, 24000, 400000])
def test_g6_degraded_never_blocks(v):
    d = decide(degraded_ctx(v), CFG)
    assert d.selected_action is not Action.BLOCK
    assert d.selected_action is (Action.MANUAL_REVIEW if v >= 5000 else Action.ALLOW)
    assert d.selected_rule == "DEGRADED_MODE_FALLBACK"
    assert [g.guardrail_id for g in d.guardrails] == ["G1", "G6"]
    assert d.guardrails[1].effect == "FALLBACK" and d.guardrails[1].removed_actions == [Action.BLOCK]


def test_prepaid_and_review_never_removed_by_any_guardrail():
    signals = SignalInputs(address_confirmed_abuse_weight=0.9, address_weight=0.1)
    d = decide(ctx(0.5, **DEMO_3, signals=signals, graph_state_as_of=DEMO_CLOCK - timedelta(days=3)), CFG)
    assert by_action(d)[Action.PREPAID_ONLY].feasible and by_action(d)[Action.MANUAL_REVIEW].feasible
