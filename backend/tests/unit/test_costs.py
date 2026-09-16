"""§8 expected-cost function: golden values, G1 structure, friction placement."""
import inspect
from dataclasses import replace

import pytest

from sentinel.api.schemas import Action
from sentinel.policy.config import load_policy_config
from sentinel.policy.costs import action_costs, clamp_clv

CFG = load_policy_config()


@pytest.mark.parametrize("v, clv, p, expected", [
    (4500, 30000, 0.03, (119.25, 766.26, 905.32, 18866.50)),    # Demo 1
    (24000, 2000, 0.91, (18700.50, 7797.69, 4045.45, 765.00)),  # Demo 2
    (12000, 15000, 0.45, (4657.50, 2277.15, 1490.05, 6985.00)), # Demo 3
])
def test_golden_costs(v, clv, p, expected):
    costs = action_costs(p, v, clv, CFG)
    actual = tuple(costs[a].total for a in (Action.ALLOW, Action.PREPAID_ONLY, Action.MANUAL_REVIEW, Action.BLOCK))
    assert actual == pytest.approx(expected, abs=0.01)


def test_action_costs_has_no_return_parameter():
    params = inspect.signature(action_costs).parameters
    assert not [name for name in params if "return" in name.lower()]
    assert list(params) == ["p_abuse", "order_value_inr", "clv_inr", "cfg"]


@pytest.mark.parametrize("p", [0.0, 0.03, 0.5, 0.91, 1.0])
@pytest.mark.parametrize("v, clv", [(500, 100000), (4500, 30000), (24000, 2000)])
def test_allow_genuine_branch_is_zero(p, v, clv):
    allow = action_costs(p, v, clv, CFG)[Action.ALLOW]
    assert allow.genuine == 0.0
    assert allow.operational == 0.0


@pytest.mark.parametrize("p", [0.03, 0.45, 0.91])
def test_prepaid_abusive_branch_has_no_friction(p):
    changed = replace(CFG, prepaid_only=replace(CFG.prepaid_only, genuine_friction_cost_inr=5000))
    base = action_costs(p, 12000, 15000, CFG)[Action.PREPAID_ONLY]
    more = action_costs(p, 12000, 15000, changed)[Action.PREPAID_ONLY]
    assert more.abusive == base.abusive
    assert more.genuine == pytest.approx(base.genuine + (1 - p) * (5000 - 30))


def test_review_fee_is_charged_regardless_of_truth():
    for p in (0.0, 1.0):
        assert action_costs(p, 12000, 15000, CFG)[Action.MANUAL_REVIEW].operational == 250


def test_clv_is_clamped():
    assert clamp_clv(0, CFG) == 2000
    assert clamp_clv(15000, CFG) == 15000
    assert clamp_clv(10**7, CFG) == 100000
    assert action_costs(0.5, 24000, 0, CFG) == action_costs(0.5, 24000, 2000, CFG)
