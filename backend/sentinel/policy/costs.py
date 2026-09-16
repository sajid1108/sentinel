"""Expected-cost function (§8). Pure: no I/O, no clock, and no p_return parameter (guardrail G1)."""
from dataclasses import dataclass

from sentinel.api.schemas import Action
from sentinel.policy.config import PolicyConfig


@dataclass(frozen=True)
class CostBreakdown:
    abusive: float      # already multiplied by p
    genuine: float      # already multiplied by (1 - p)
    operational: float

    @property
    def total(self) -> float:
        return self.abusive + self.genuine + self.operational


def clamp_clv(clv: float, cfg: PolicyConfig) -> float:
    return min(max(clv, cfg.clv.new_customer_floor_inr), cfg.clv.cap_inr)


def action_costs(p_abuse: float, order_value_inr: float, clv_inr: float,
                 cfg: PolicyConfig) -> dict[Action, CostBreakdown]:
    """Pure function. p_return is intentionally not a parameter (guardrail G1)."""
    p, q, v = p_abuse, 1.0 - p_abuse, order_value_inr
    clv = clamp_clv(clv_inr, cfg)
    e, pp, mr, bl = cfg.economics, cfg.prepaid_only, cfg.manual_review, cfg.block

    margin = e.gross_margin_rate * v
    loss_allow = v * (1 - cfg.allow.abuse_recovery_rate) + e.reverse_logistics_cost_inr
    loss_prepaid = v * (1 - pp.abuse_recovery_rate) + e.reverse_logistics_cost_inr
    false_block = margin + bl.genuine_clv_churn_rate * clv + bl.genuine_support_cost_inr

    return {
        Action.ALLOW: CostBreakdown(p * loss_allow, 0.0, 0.0),
        Action.PREPAID_ONLY: CostBreakdown(
            p * (1 - pp.abuser_deterrence_rate) * loss_prepaid,
            q * (pp.genuine_abandonment_rate * margin
                 + pp.genuine_clv_churn_rate * clv + pp.genuine_friction_cost_inr),
            0.0),
        Action.MANUAL_REVIEW: CostBreakdown(
            p * (1 - mr.reviewer_detection_rate) * loss_allow,
            q * (mr.genuine_delay_abandonment_rate * margin
                 + mr.genuine_false_cancel_rate * false_block),
            mr.review_cost_inr),
        Action.BLOCK: CostBreakdown(0.0, q * false_block, 0.0),
    }
