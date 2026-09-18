"""Phase 1 review fixes: decision-time G4 (A1), purity (C2), present-vs-counted (B2), degraded mode (B4),
G3 boundary text (B6), invariant without assert (B7), demo explanation wording (C7)."""
import ast
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import sentinel.policy
from sentinel.api.schemas import Action, GuardrailResult, PolicyDecision
from sentinel.money import make_money
from sentinel.policy import engine
from sentinel.policy.config import load_policy_config
from sentinel.policy.engine import decide
from sentinel.policy.guardrails import SignalInputs, corroborating_signals
from sentinel.settings import DEMO_CLOCK

from .policy_helpers import DEMO_1, DEMO_2, DEMO_2_SIGNALS, DEVICE, by_action, ctx, degraded_ctx

CFG = load_policy_config()


def _guardrail(decision, gid: str) -> GuardrailResult:
    return next(g for g in decision.guardrails if g.guardrail_id == gid)


# ── C1: G4 uses decision time, not the demo clock ──────────────────────────
BACKTEST_TIME = DEMO_CLOCK - timedelta(days=26)


def test_c1_backtest_decision_with_fresh_graph_can_block():
    d = decide(ctx(0.91, **DEMO_2, signals=DEMO_2_SIGNALS, decided_at=BACKTEST_TIME,
                   graph_state_as_of=BACKTEST_TIME), CFG)
    assert d.selected_action is Action.BLOCK
    assert not _guardrail(d, "G4").triggered


def test_c1_graph_older_than_decision_by_25h_removes_block():
    d = decide(ctx(0.91, **DEMO_2, signals=DEMO_2_SIGNALS, decided_at=BACKTEST_TIME,
                   graph_state_as_of=BACKTEST_TIME - timedelta(hours=25)), CFG)
    g4 = _guardrail(d, "G4")
    assert g4.triggered and "more than 24 hours older than the decision time" in g4.detail
    assert d.selected_action is Action.MANUAL_REVIEW
    assert d.selected_rule == "MIN_EXPECTED_COST_WITHIN_GUARDRAILS"


def test_c1_graph_state_after_decision_time_rejected():
    with pytest.raises(ValueError, match="later than decided_at"):
        ctx(0.91, **DEMO_2, decided_at=BACKTEST_TIME, graph_state_as_of=BACKTEST_TIME + timedelta(seconds=1))


def test_c1_decided_at_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        ctx(0.5, **DEMO_2, decided_at=DEMO_CLOCK.replace(tzinfo=None), graph_state_as_of=DEMO_CLOCK)


# ── C2: policy stays pure ───────────────────────────────────────────────────
POLICY_FILES = sorted(Path(sentinel.policy.__file__).parent.glob("*.py"))


@pytest.mark.parametrize("path", POLICY_FILES, ids=lambda p: p.name)
def test_c2_policy_has_no_settings_or_clock_access(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "sentinel.settings" or (node.module == "sentinel" and
                                                       any(a.name == "settings" for a in node.names)):
                offenders.append(f"line {node.lineno}: from {node.module} import ...")
            if node.module == "time" and any(a.name == "time" for a in node.names):
                offenders.append(f"line {node.lineno}: from time import time")
        elif isinstance(node, ast.Import):
            offenders += [f"line {node.lineno}: import {a.name}" for a in node.names if a.name == "sentinel.settings"]
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if (node.value.id, node.attr) in {("datetime", "now"), ("datetime", "utcnow"), ("date", "today"),
                                              ("time", "time")}:
                offenders.append(f"line {node.lineno}: {node.value.id}.{node.attr}")
    assert offenders == []


def test_c2_scan_covers_the_policy_modules():
    assert {"costs.py", "guardrails.py", "engine.py", "baselines.py", "config.py"} <= {p.name for p in POLICY_FILES}


# ── C3: present but not counted ─────────────────────────────────────────────
def _signal(inputs: SignalInputs, name: str):
    return next(s for s in corroborating_signals(inputs) if s.signal == name)


def test_c3_burst_via_address_is_present_not_counted_and_keeps_weight():
    inputs = SignalInputs(linked_orders_24h=4, burst_link_kinds=frozenset({"ADDRESS"}), burst_weight=0.6)
    burst = _signal(inputs, "TEMPORAL_BURST")
    assert (burst.present, burst.counts_for_corroboration, burst.weight) == (True, False, 0.6)
    assert burst.detail == "Observed through address links only; not counted."


def test_c3_device_plus_address_only_burst_cannot_block():
    inputs = SignalInputs(device_confirmed_abuse_weight=1.5, device_weight=0.75,
                          linked_orders_24h=4, burst_link_kinds=frozenset({"ADDRESS"}), burst_weight=0.6)
    d = decide(ctx(0.95, **DEMO_2, signals=inputs), CFG)
    g2 = _guardrail(d, "G2")
    assert not by_action(d)[Action.BLOCK].feasible and g2.triggered
    assert "DEVICE" in g2.detail and "TEMPORAL_BURST" not in g2.detail


def test_c3_multi_tenant_address_is_present_not_counted():
    address = _signal(SignalInputs(address_confirmed_abuse_weight=0.8, address_is_multi_tenant=True,
                                   address_weight=0.1), "ADDRESS")
    assert (address.present, address.counts_for_corroboration, address.weight) == (True, False, 0.1)
    assert address.detail == "Multi-tenant address; not counted."


def test_c3_g4_weakness_ignores_non_counted_signals():
    inputs = SignalInputs(device_confirmed_abuse_weight=1.0, device_weight=0.2,
                          address_confirmed_abuse_weight=0.8, address_is_multi_tenant=True, address_weight=0.8)
    d = decide(ctx(0.95, **DEMO_2, signals=inputs), CFG)
    g4 = _guardrail(d, "G4")
    assert g4.triggered and "every counted signal" in g4.detail


# ── C4: degraded mode never invents a probability ──────────────────────────
@pytest.mark.parametrize("v, expected", [(6000, Action.MANUAL_REVIEW), (4000, Action.ALLOW)])
def test_c4_degraded_decision_has_no_costs(v, expected):
    d = decide(degraded_ctx(v), CFG)
    assert d.costs == [] and d.cost_optimal_action is None
    assert d.selected_action is expected and d.selected_action is not Action.BLOCK
    assert d.policy_explanation == _guardrail(d, "G6").detail
    assert "no model score" in d.policy_explanation


@pytest.mark.parametrize("p_abuse, p_return", [(None, 0.3), (0.3, None), (None, None)])
def test_c4_non_degraded_context_requires_scores(p_abuse, p_return):
    with pytest.raises(ValueError, match="required unless degraded"):
        ctx(p_abuse, **DEMO_2, p_return=p_return)


def test_c4_degraded_context_rejects_scores():
    with pytest.raises(ValueError, match="carry no scores"):
        ctx(0.5, **DEMO_2, p_return=None, degraded=True)


def _cost(action: Action):
    return dict(action=action, expected_cost=make_money(1), abusive_branch=make_money(0),
                genuine_branch=make_money(1), operational=make_money(0), feasible=True,
                excluded_by=[], rank_by_cost=list(Action).index(action) + 1)


def _decision_payload(**overrides):
    base = dict(policy_version="v1.0", policy_config_sha256=CFG.config_sha256,
                cost_optimal_action=Action.ALLOW, selected_action=Action.ALLOW,
                selected_rule="MIN_EXPECTED_COST", costs=[_cost(a) for a in Action], guardrails=[],
                policy_explanation="x", assumptions_notice=CFG.policy.notice)
    base.update(overrides)
    return base


def test_c4_degraded_policy_decision_with_costs_rejected():
    with pytest.raises(ValidationError, match="degraded decisions carry no costs"):
        PolicyDecision(**_decision_payload(selected_rule="DEGRADED_MODE_FALLBACK", cost_optimal_action=None))


def test_c4_degraded_policy_decision_with_cost_optimal_rejected():
    with pytest.raises(ValidationError, match="no cost_optimal_action"):
        PolicyDecision(**_decision_payload(selected_rule="DEGRADED_MODE_FALLBACK", costs=[]))


def test_c4_non_degraded_policy_decision_without_costs_rejected():
    with pytest.raises(ValidationError, match="all four actions"):
        PolicyDecision(**_decision_payload(costs=[]))


def test_c4_non_degraded_policy_decision_without_cost_optimal_rejected():
    with pytest.raises(ValidationError, match="cost_optimal_action is required"):
        PolicyDecision(**_decision_payload(cost_optimal_action=None))


def test_c4_duplicate_cost_rows_rejected():
    with pytest.raises(ValidationError, match="exactly once"):
        PolicyDecision(**_decision_payload(costs=[_cost(a) for a in Action] + [_cost(Action.ALLOW)]))


def test_c4_valid_payload_accepted():
    assert PolicyDecision(**_decision_payload()).selected_action is Action.ALLOW


# ── C5: G3 boundary text never shows the threshold as reached ──────────────
# The figures are now the page's own format (Phase 9 brief 1.3). At one decimal a score just below the
# threshold can round onto it, so G3 says "just under" rather than printing the same number twice.
@pytest.mark.parametrize("p, shown", [(0.6951, "69.5%"), (0.6999, "just under 70.0%")])
def test_c5_g3_detail_below_threshold(p, shown):
    d = decide(ctx(p, **DEMO_2, signals=DEMO_2_SIGNALS), CFG)
    g3 = _guardrail(d, "G3")
    assert "this order scored 70.0%" not in g3.detail and f"scored {shown}." in g3.detail
    assert not by_action(d)[Action.BLOCK].feasible


# ── C6: the feasibility invariant is not an assert ─────────────────────────
def test_c6_invariant_raises_runtime_error(monkeypatch):
    def removes_review(ctx, cfg):
        return GuardrailResult(guardrail_id="G5", name="broken", triggered=True, effect="REMOVED_ACTIONS",
                               removed_actions=[Action.MANUAL_REVIEW], detail="broken guardrail")

    monkeypatch.setattr(engine, "GUARDRAILS", engine.GUARDRAILS + (removes_review,))
    with pytest.raises(RuntimeError, match="invariant violated"):
        decide(ctx(0.5, **DEMO_2, signals=DEVICE), CFG)


def test_c6_engine_source_has_no_assert():
    tree = ast.parse(Path(engine.__file__).read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]


# ── C7: demo explanations, word for word ────────────────────────────────────
def test_c7_demo_2_explanation_mentions_allow_removed_by_g5():
    d = decide(ctx(0.91, **DEMO_2, signals=DEMO_2_SIGNALS), CFG)
    assert d.policy_explanation == (
        "BLOCK was selected because its expected cost (₹765) is lower than MANUAL_REVIEW (₹4,045), "
        "PREPAID_ONLY (₹7,798) and ALLOW (₹18,701) under policy v1.0. "
        "ALLOW was also not permitted: G5 removes ALLOW when the abuse probability is at least 40.0% "
        "and the order value is at least ₹10,000.")


def test_c7_demo_1_explanation():
    """§6.5 style: removed actions are always reported, even when they were not contenders."""
    d = decide(ctx(0.03, **DEMO_1, p_return=0.75), CFG)
    assert d.policy_explanation == (
        "ALLOW was selected because its expected cost (₹119) is lower than PREPAID_ONLY (₹766), "
        "MANUAL_REVIEW (₹905) and BLOCK (₹18,867) under policy v1.0. "
        "BLOCK was also not permitted: G2 requires two corroborating signals; none was found. "
        "G3 requires an abuse probability of at least 70.0%; this order scored 3.0%.")
