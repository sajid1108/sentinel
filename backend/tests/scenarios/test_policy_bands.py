"""§11 / §13.4 policy-only band tests: the demo action holds across the whole probability band, not at a point."""
import pytest

from sentinel.api.schemas import Action
from sentinel.policy.config import load_policy_config
from sentinel.policy.engine import decide
from tests.unit.policy_helpers import DEMO_1, DEMO_2, DEMO_2_SIGNALS, DEMO_3, DEMO_3_SIGNALS, ctx

CFG = load_policy_config()


def _band(lo: float, hi: float, step: float = 0.01) -> list[float]:
    n = round((hi - lo) / step)
    return [round(lo + i * step, 4) for i in range(n + 1)]


@pytest.mark.parametrize("p", _band(0.0, 0.15))
def test_demo_1_allow_band(p):
    d = decide(ctx(p, **DEMO_1, p_return=0.75), CFG)
    assert d.selected_action is Action.ALLOW
    assert d.selected_rule == "MIN_EXPECTED_COST"


@pytest.mark.parametrize("p", _band(0.75, 1.0))
def test_demo_2_block_band(p):
    d = decide(ctx(p, **DEMO_2, signals=DEMO_2_SIGNALS), CFG)
    assert d.selected_action is Action.BLOCK
    assert d.selected_rule == "MIN_EXPECTED_COST"
    g = {r.guardrail_id: r for r in d.guardrails}
    assert not g["G2"].triggered and not g["G3"].triggered and not g["G4"].triggered


@pytest.mark.parametrize("p", _band(0.20, 0.70))
def test_demo_3_manual_review_band(p):
    d = decide(ctx(p, **DEMO_3, signals=DEMO_3_SIGNALS), CFG)
    assert d.selected_action is Action.MANUAL_REVIEW
    assert d.cost_optimal_action is Action.MANUAL_REVIEW
