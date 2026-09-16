"""Deterministic policy engine (§9.1): costs first, guardrails remove actions, cost picks among the rest."""
from sentinel.api.schemas import SEVERITY, Action, ActionCost, GuardrailResult, PolicyDecision
from sentinel.money import format_inr, make_money
from sentinel.policy.config import PolicyConfig
from sentinel.policy.costs import CostBreakdown, action_costs
from sentinel.policy.guardrails import GUARDRAILS, DecisionContext, g1_return_probability_excluded, g6_degraded_mode

__all__ = ["DecisionContext", "argmin_with_tiebreak", "decide", "decision_status"]


def argmin_with_tiebreak(totals: dict[Action, float], feasible: set[Action], cfg: PolicyConfig) -> Action:
    """Cheapest feasible action; anything within tie_tolerance_inr of it is a tie, and ties go to the least severe.

    Totals are the cent-rounded expected costs, so the choice matches the Money values recorded in the decision.
    """
    best = min(totals[a] for a in feasible)
    tied = [a for a in feasible if totals[a] - best <= cfg.policy.tie_tolerance_inr]
    return min(tied, key=SEVERITY.__getitem__)


def decision_status(action: Action) -> str:
    """§9.4: MANUAL_REVIEW waits for a reviewer; everything else is applied (and still overridable)."""
    return "PENDING_REVIEW" if action is Action.MANUAL_REVIEW else "AUTO_APPLIED"


def _cost_rows(costs: dict[Action, CostBreakdown], totals: dict[Action, float],
               results: list[GuardrailResult]) -> list[ActionCost]:
    ranked = sorted(Action, key=lambda a: (totals[a], SEVERITY[a]))
    rows = []
    for action in Action:
        excluded_by = [r.guardrail_id for r in results if action in r.removed_actions]
        c = costs[action]
        rows.append(ActionCost(
            action=action,
            expected_cost=make_money(c.total),
            abusive_branch=make_money(c.abusive),
            genuine_branch=make_money(c.genuine),
            operational=make_money(c.operational),
            feasible=not excluded_by,
            excluded_by=excluded_by,
            rank_by_cost=ranked.index(action) + 1,
        ))
    return rows


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def render_policy_explanation(totals: dict[Action, float], selected: Action, cost_optimal: Action,
                              results: list[GuardrailResult], cfg: PolicyConfig) -> str:
    version = cfg.policy.version
    ranked = sorted(Action, key=lambda a: (totals[a], SEVERITY[a]))
    removed = {a: [r for r in results if a in r.removed_actions] for a in Action}

    def blocked_by(action: Action) -> str:
        return " ".join(r.detail for r in removed[action])

    def cost(action: Action) -> str:
        return format_inr(totals[action])

    if selected == cost_optimal:
        others = [a for a in ranked if a != selected]
        ties = [a for a in others if totals[a] - totals[selected] <= cfg.policy.tie_tolerance_inr]
        if ties:
            text = (f"{selected.value} was selected because its expected cost ({cost(selected)}) is within "
                    f"{format_inr(cfg.policy.tie_tolerance_inr)} of {_join([f'{a.value} ({cost(a)})' for a in ties])}, "
                    f"and ties go to the less severe action under policy {version}.")
        else:
            text = (f"{selected.value} was selected because its expected cost ({cost(selected)}) is lower than "
                    f"{_join([f'{a.value} ({cost(a)})' for a in others])} under policy {version}.")
        extra = [a for a in ranked if removed[a]]
    else:
        text = (f"{cost_optimal.value} had the lowest expected cost ({cost(cost_optimal)}) but was not permitted: "
                f"{blocked_by(cost_optimal)} {selected.value} was selected as the lowest-cost permitted action "
                f"({cost(selected)}) under policy {version}.")
        extra = [a for a in ranked if removed[a] and a != cost_optimal]
    for action in extra:
        text += f" {action.value} was also not permitted: {blocked_by(action)}"
    return text


def _decision(cfg: PolicyConfig, cost_optimal: Action | None, selected: Action, rule: str,
              rows: list[ActionCost], results: list[GuardrailResult], explanation: str) -> PolicyDecision:
    return PolicyDecision(
        policy_version=cfg.policy.version,
        policy_config_sha256=cfg.config_sha256,
        cost_optimal_action=cost_optimal,
        selected_action=selected,
        selected_rule=rule,
        costs=rows,
        guardrails=results,
        policy_explanation=explanation,
        assumptions_notice=cfg.policy.notice,
    )


def degraded_fallback(ctx: DecisionContext, cfg: PolicyConfig) -> PolicyDecision:
    """G6. No model score exists, so no expected cost is computed or shown."""
    g6, selected = g6_degraded_mode(ctx, cfg)
    results = [g1_return_probability_excluded(ctx, cfg), g6]
    return _decision(cfg, None, selected, "DEGRADED_MODE_FALLBACK", [], results, g6.detail)


def decide(ctx: DecisionContext, cfg: PolicyConfig) -> PolicyDecision:
    if ctx.degraded:                                   # model or graph state unavailable
        return degraded_fallback(ctx, cfg)             # G6

    costs = action_costs(ctx.p_abuse, ctx.order_value_inr, ctx.clv_inr, cfg)
    totals = {a: make_money(c.total).inr for a, c in costs.items()}
    cost_optimal = argmin_with_tiebreak(totals, set(Action), cfg)

    results = [g(ctx, cfg) for g in GUARDRAILS]
    removed = {a for r in results for a in r.removed_actions}
    feasible = set(Action) - removed
    if not {Action.PREPAID_ONLY, Action.MANUAL_REVIEW} <= feasible:   # invariant: never empty; survives -O
        raise RuntimeError("invariant violated: PREPAID_ONLY and MANUAL_REVIEW must remain feasible")

    selected = argmin_with_tiebreak(totals, feasible, cfg)
    rule = "MIN_EXPECTED_COST" if selected == cost_optimal else "MIN_EXPECTED_COST_WITHIN_GUARDRAILS"
    rows = _cost_rows(costs, totals, results)
    explanation = render_policy_explanation(totals, selected, cost_optimal, results, cfg)
    return _decision(cfg, cost_optimal, selected, rule, rows, results, explanation)
