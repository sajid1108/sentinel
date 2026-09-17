"""Offline backtest (§9.5, §4 StrategyBacktest, §14.1).

Every strategy is scored by REALIZED cost: the policy's own cost function evaluated at the true label.
  cost(a | abusive) = action_costs(1.0, V, CLV)[a], its loss (abusive branch) scaled by returned_value_fraction
                      when the order has a return (return_label = 1); operational cost is not scaled
  cost(a | genuine) = action_costs(0.0, V, CLV)[a]
Expected cost is never used to score a strategy.

FIXED_THRESHOLD is tuned on CALIBRATION rows only (P13, asserted in tune_fixed_threshold).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd

from sentinel.api.schemas import Action, StrategyBacktest
from sentinel.features.builder import signal_inputs_from_row
from sentinel.money import make_money
from sentinel.policy.baselines import NEVER, allow_all, fixed_threshold, rule_based
from sentinel.policy.config import PolicyConfig
from sentinel.policy.costs import action_costs
from sentinel.policy.engine import argmin_with_tiebreak, decide
from sentinel.policy.guardrails import DecisionContext, corroborating_signals

ACTIONS: tuple[Action, ...] = (Action.ALLOW, Action.PREPAID_ONLY, Action.MANUAL_REVIEW, Action.BLOCK)
A_INDEX = {a: i for i, a in enumerate(ACTIONS)}
ALLOW, PREPAID, REVIEW, BLOCK = range(4)
STRATEGIES = ("SENTINEL", "FIXED_THRESHOLD", "RULE_BASED", "ALLOW_ALL")
TAU_GRID: tuple[float, ...] = tuple(round(0.05 * k, 2) for k in range(1, 21))      # 0.05 ... 0.95, 1.0 = never
COST_GROUPS = ("economics", "clv", "allow", "prepaid_only", "manual_review", "block")
COST_FACTORS = (0.5, 1.5)
CALIBRATION = "CALIBRATION"


# ── realized costs ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CostMatrix:
    """Realized cost of each action (columns in ACTIONS order) for each order (rows)."""
    total: np.ndarray
    operational: np.ndarray
    genuine: np.ndarray
    abusive: np.ndarray            # bool per order (the true label)
    margin: np.ndarray             # gross margin per order


def loss_fraction(return_label, returned_value_fraction) -> np.ndarray:
    """returned_value_fraction when the order was returned, else 1.0 (e.g. item-not-received claims)."""
    returned = pd.Series(return_label).fillna(0).astype(int).to_numpy() == 1
    fraction = pd.Series(returned_value_fraction).astype(float).to_numpy()
    return np.where(returned & ~np.isnan(fraction), fraction, 1.0)


def cost_matrix(rows: pd.DataFrame, labels, cfg: PolicyConfig) -> CostMatrix:
    """rows: order_value_inr, clv_inr, return_label, returned_value_fraction; labels: 0/1 abuse labels."""
    abusive = np.asarray(labels, dtype=int) == 1
    fractions = loss_fraction(rows["return_label"], rows["returned_value_fraction"])
    n = len(rows)
    total, operational, genuine = (np.zeros((n, 4)) for _ in range(3))
    for i, (v, clv) in enumerate(zip(rows["order_value_inr"].astype(float), rows["clv_inr"].astype(float))):
        costs = action_costs(1.0 if abusive[i] else 0.0, v, clv, cfg)
        for j, action in enumerate(ACTIONS):
            c = costs[action]
            loss = c.abusive * fractions[i] if abusive[i] else c.abusive
            total[i, j] = loss + c.genuine + c.operational
            operational[i, j] = c.operational
            genuine[i, j] = c.genuine
    margin = cfg.economics.gross_margin_rate * rows["order_value_inr"].astype(float).to_numpy()
    return CostMatrix(total, operational, genuine, abusive, margin)


def realized_costs(cm: CostMatrix, actions: np.ndarray) -> np.ndarray:
    return cm.total[np.arange(len(actions)), actions]


# ── strategy metrics ─────────────────────────────────────────────────────────
def _rate(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def strategy_backtest(strategy: str, actions: np.ndarray, cm: CostMatrix,
                      cfg: PolicyConfig) -> tuple[StrategyBacktest, dict]:
    """The §4 StrategyBacktest fields, plus counts and notes for undefined ratios."""
    actions = np.asarray(actions, dtype=int)
    idx = np.arange(len(actions))
    n = len(actions)
    ab, gen = cm.abusive, ~cm.abusive
    n_ab, n_gen = int(ab.sum()), int(gen.sum())
    cost = cm.total[idx, actions]
    intercept = np.array([0.0, cfg.prepaid_only.abuser_deterrence_rate, cfg.manual_review.reviewer_detection_rate, 1.0])
    lost = np.array([0.0, cfg.prepaid_only.genuine_abandonment_rate,
                     cfg.manual_review.genuine_delay_abandonment_rate + cfg.manual_review.genuine_false_cancel_rate,
                     1.0])
    expected_intercepted = float(intercept[actions][ab].sum())
    blocks = actions == BLOCK
    side_costs = float((cm.operational[idx, actions] + cm.genuine[idx, actions]).sum())
    notes = []
    if expected_intercepted == 0:
        notes.append("cost_per_detected_abuse undefined (no abusive order intercepted); reported as 0")
    if not blocks.any():
        notes.append("precision_block undefined (no BLOCK); reported as 0")
    result = StrategyBacktest(
        strategy=strategy,
        realized_cost_per_1000=make_money(1000 * cost.sum() / n if n else 0.0),
        abuse_loss_prevented=make_money(float((cm.total[idx, ALLOW] - cost)[ab].sum())),
        genuine_block_rate=_rate((gen & blocks).sum(), n_gen),
        customer_friction_rate=_rate((gen & np.isin(actions, [PREPAID, REVIEW])).sum(), n_gen),
        manual_reviews_per_1000=_rate(1000 * (actions == REVIEW).sum(), n),
        cost_per_detected_abuse=make_money(side_costs / expected_intercepted if expected_intercepted else 0.0),
        revenue_preserved=make_money(float((cm.margin * (1 - lost[actions]))[gen].sum())),
        precision_block=_rate((ab & blocks).sum(), blocks.sum()),
        recall_intercepted=_rate(expected_intercepted, n_ab),
    )
    extras = {"orders": n, "abusive": n_ab, "genuine": n_gen, "expected_intercepted_abusive": expected_intercepted,
              "realized_cost_total": make_money(float(cost.sum())).model_dump(), "notes": notes}
    return result, extras


def action_distribution(actions: np.ndarray) -> dict[str, int]:
    counts = np.bincount(np.asarray(actions, dtype=int), minlength=4)
    return {a.value: int(counts[i]) for i, a in enumerate(ACTIONS)}


# ── strategies ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SentinelDecisions:
    selected: np.ndarray                          # action index per order
    cost_optimal: np.ndarray                      # action index per order (argmin over all four actions)
    removed_optimal_by: tuple[tuple[str, ...], ...]   # guardrail ids that removed the cost-optimal action


def sentinel_decisions(rows: pd.DataFrame, p_abuse, p_return, cfg: PolicyConfig) -> SentinelDecisions:
    """decide() per order with the real signals; decided_at = graph_state_as_of = t0."""
    selected = np.empty(len(rows), dtype=int)
    optimal = np.empty(len(rows), dtype=int)
    removed_by = []
    for i, (row, pa, pr) in enumerate(zip(rows.to_dict("records"), p_abuse, p_return)):
        t0 = row["t0"].to_pydatetime()
        ctx = DecisionContext(p_abuse=float(pa), p_return=float(pr), order_value_inr=float(row["order_value_inr"]),
                              clv_inr=float(row["clv_inr"]),
                              signals=corroborating_signals(signal_inputs_from_row(row)),
                              decided_at=t0, graph_state_as_of=row["graph_state_as_of"].to_pydatetime())
        decision = decide(ctx, cfg)
        selected[i] = A_INDEX[decision.selected_action]
        optimal[i] = A_INDEX[decision.cost_optimal_action]
        removed_by.append(tuple(g.guardrail_id for g in decision.guardrails
                                if decision.cost_optimal_action in g.removed_actions))
    return SentinelDecisions(selected, optimal, tuple(removed_by))


def sentinel_actions(rows: pd.DataFrame, p_abuse, p_return, cfg: PolicyConfig) -> np.ndarray:
    return sentinel_decisions(rows, p_abuse, p_return, cfg).selected


def unconstrained_actions(rows: pd.DataFrame, p_abuse, cfg: PolicyConfig) -> np.ndarray:
    """Lowest expected cost over all four actions, no guardrails (same cent rounding and tie rule as decide())."""
    out = np.empty(len(rows), dtype=int)
    for i, (v, clv, pa) in enumerate(zip(rows["order_value_inr"].astype(float), rows["clv_inr"].astype(float),
                                         p_abuse)):
        totals = {a: make_money(c.total).inr for a, c in action_costs(float(pa), v, clv, cfg).items()}
        out[i] = A_INDEX[argmin_with_tiebreak(totals, set(ACTIONS), cfg)]
    return out


def threshold_actions(p_abuse, tau_review: float, tau_block: float) -> np.ndarray:
    """Vectorised fixed_threshold(); fixed_threshold_actions() applies the baseline function itself."""
    p = np.asarray(p_abuse, dtype=float)
    block = (p >= tau_block) & (tau_block < NEVER)
    review = (p >= tau_review) & (tau_review < NEVER)
    return np.where(block, BLOCK, np.where(review, REVIEW, ALLOW))


def guardrail_cost(rows: pd.DataFrame, cm: CostMatrix, decisions: SentinelDecisions, unconstrained: np.ndarray,
                   fixed: np.ndarray) -> dict:
    """Price of guardrails (evaluation-only diagnostic): SENTINEL vs the unconstrained cost argmin."""
    n = len(rows)
    idx = np.arange(n)
    ab, gen = cm.abusive, ~cm.abusive

    def summary(actions):
        cost = cm.total[idx, actions]
        return {"realized_cost_per_1000": make_money(1000 * cost.sum() / n if n else 0.0).model_dump(),
                "block": int((actions == BLOCK).sum()), "genuine_block": int((gen & (actions == BLOCK)).sum()),
                "manual_review": int((actions == REVIEW).sum()), "prepaid_only": int((actions == PREPAID).sum()),
                "abusive_allowed": int((ab & (actions == ALLOW)).sum())}

    sentinel = decisions.selected
    if not np.array_equal(decisions.cost_optimal, unconstrained):
        raise AssertionError("decide()'s cost_optimal_action differs from the unconstrained argmin")
    s_cost, u_cost = cm.total[idx, sentinel], cm.total[idx, unconstrained]
    extra = float((s_cost - u_cost).sum())
    avoided = int((gen & (unconstrained == BLOCK)).sum() - (gen & (sentinel == BLOCK)).sum())
    per_guardrail: dict[str, dict] = {}
    changed = sentinel != unconstrained
    for i in np.flatnonzero(changed):
        for gid in decisions.removed_optimal_by[i]:
            entry = per_guardrail.setdefault(gid, {"orders": 0, "realized_cost_difference": 0.0})
            entry["orders"] += 1
            entry["realized_cost_difference"] += float(s_cost[i] - u_cost[i])
    for entry in per_guardrail.values():
        entry["realized_cost_difference"] = make_money(entry["realized_cost_difference"]).model_dump()
    return {
        "note": "Evaluation-only diagnostic, not a StrategyBacktest strategy. SENTINEL_UNCONSTRAINED takes the "
                "lowest expected cost over all four actions with no guardrails. Realized cost at the true label.",
        "rows": n,
        "strategies": {"SENTINEL": summary(sentinel), "SENTINEL_UNCONSTRAINED": summary(unconstrained),
                       "FIXED_THRESHOLD": summary(fixed)},
        "guardrail_effect": {
            "decisions_changed": int(changed.sum()),
            "extra_realized_cost_per_1000": make_money(1000 * extra / n if n else 0.0).model_dump(),
            "extra_realized_cost_total": make_money(extra).model_dump(),
            "genuine_blocks_avoided": avoided,
            "extra_realized_cost_per_genuine_block_avoided":
                make_money(extra / avoided).model_dump() if avoided else None,
        },
        "per_guardrail": dict(sorted(per_guardrail.items())),
        "orders_with_multiple_guardrails": int(sum(1 for i in np.flatnonzero(changed)
                                                   if len(decisions.removed_optimal_by[i]) > 1)),
    }


def fixed_threshold_actions(p_abuse, tau_review: float, tau_block: float) -> np.ndarray:
    return np.array([A_INDEX[fixed_threshold(float(p), tau_block=tau_block, tau_review=tau_review).action]
                     for p in p_abuse], dtype=int)


def rule_based_actions(rows: pd.DataFrame) -> np.ndarray:
    out = np.empty(len(rows), dtype=int)
    for i, row in enumerate(rows.to_dict("records")):
        rate = row["matured_return_rate"]
        outcome = rule_based(None if pd.isna(rate) else float(rate), int(row["matured_returns"]),
                             row["account_age_days"], float(row["order_value_inr"]), row["payment_method"])
        out[i] = A_INDEX[outcome.action]
    return out


def allow_all_actions(n: int) -> np.ndarray:
    return np.full(n, A_INDEX[allow_all()], dtype=int)


@dataclass(frozen=True)
class Tuning:
    tau_review: float
    tau_block: float
    realized_cost_per_1000: float
    order_ids: tuple[str, ...]


def tune_fixed_threshold(rows: pd.DataFrame, p_abuse, cm: CostMatrix) -> Tuning:
    """Grid search on CALIBRATION rows only. Lowest realized cost (to the cent) wins; ties go to the higher
    tau_block, then the higher tau_review (less intervention)."""
    if not (rows["split"] == CALIBRATION).all():
        raise AssertionError("FIXED_THRESHOLD must be tuned on CALIBRATION rows only (P13)")
    best = None
    for tau_review in TAU_GRID:
        for tau_block in TAU_GRID:
            if tau_block < tau_review:
                continue
            total = round(float(realized_costs(cm, threshold_actions(p_abuse, tau_review, tau_block)).sum()), 2)
            key = (total, -tau_block, -tau_review)
            if best is None or key < best[0]:
                best = (key, tau_review, tau_block)
    (total, _, _), tau_review, tau_block = best
    return Tuning(tau_review, tau_block, 1000 * total / len(rows), tuple(rows["order_id"]))


# ── sensitivity ──────────────────────────────────────────────────────────────
def scaled_config(cfg: PolicyConfig, group: str, factor: float) -> PolicyConfig:
    """Every numeric value in one config group × factor; *_rate values clipped to [0, 1]."""
    section = getattr(cfg, group)
    changes = {}
    for f in dataclasses.fields(section):
        value = getattr(section, f.name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            scaled = value * factor
            changes[f.name] = min(max(scaled, 0.0), 1.0) if f.name.endswith("_rate") else scaled
    return dataclasses.replace(cfg, **{group: dataclasses.replace(section, **changes)},
                               config_sha256=f"{cfg.config_sha256}:{group}x{factor}")
