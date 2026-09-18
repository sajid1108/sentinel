"""The three §6.5 explanation levels, assembled from attributions and fired reason codes.

Levels 1 and 2 live here. Level 3, the policy explanation, is rendered by `policy/engine.py` and is
deliberately NOT duplicated: this module never imports `sentinel.policy` and never names an Action.
Models explain; policy decides.

Every sentence is a fixed template filled from recorded evidence. No LLM text.
"""
from __future__ import annotations

from dataclasses import dataclass

from sentinel.models import reason_codes as rc
from sentinel.models.attribution import Ablation, ablation

GRAPH_GROUP = "graph"

# One sentence per dominant evidence group (§6.5 level 1).
PREDICTION_TEMPLATES: dict[str, str] = {
    "graph": "The abuse score is driven mainly by links to other accounts sharing this order's "
             "device, payment method or delivery pattern.",
    "account": "The abuse score is driven mainly by this account's own history rather than by links "
               "to other accounts.",
    "order": "The abuse score is driven mainly by the characteristics of this order itself.",
}
# When nothing moved the score, what is left to explain is the account itself, so this is the account
# group's wording for the no-evidence case rather than a fourth category.
NO_EVIDENCE_TEMPLATE = ("No material abuse evidence was found; the score reflects this account's own "
                        "history rather than links to other accounts.")
NO_EVIDENCE_GROUP = "account"

# Below this, no group counts as dominant and the no-evidence sentence is used instead.
DOMINANCE_MIN_PP = 1.0


@dataclass(frozen=True)
class OrderExplanation:
    """Everything the reviewer dashboard needs to explain one order's scores. No action, no cost."""
    p_return: float
    p_abuse: float
    p_abuse_without_graph_evidence: float
    prediction_explanation: str
    reasons: list[rc.FiredCode]                 # evidence order: strength, then |attribution|, then catalog
    mitigating_reasons: list[rc.FiredCode]
    group_attribution_pp: dict[str, float]
    reason_code_version: str
    attributions_by_magnitude: list[rc.FiredCode]   # the same codes as `reasons`, by |attribution_pp| only


def dominant_group(group_delta_pp: dict[str, float]) -> str | None:
    """The evidence group that moved the score most, ties broken by graph > account > order.

    None when no group clears DOMINANCE_MIN_PP, i.e. nothing materially moved the score.
    """
    ranked = sorted(rc.GROUP_PRECEDENCE,
                    key=lambda g: (-group_delta_pp.get(g, 0.0), rc.GROUP_PRECEDENCE.index(g)))
    best = ranked[0]
    return best if group_delta_pp.get(best, 0.0) >= DOMINANCE_MIN_PP else None


def prediction_explanation(group_delta_pp: dict[str, float]) -> str:
    group = dominant_group(group_delta_pp)
    return NO_EVIDENCE_TEMPLATE if group is None else PREDICTION_TEMPLATES[group]


def explanation_group(group_delta_pp: dict[str, float]) -> str:
    """The group the rendered sentence speaks for, including the no-evidence fallback."""
    return dominant_group(group_delta_pp) or NO_EVIDENCE_GROUP


# Reasons are evidence statements (#27), so they are ordered as evidence: strongest evidence first.
EVIDENCE_STRENGTH_ORDER: tuple[str, ...] = ("STRONG", "MODERATE", "WEAK")


def sort_reasons(reasons: list[rc.FiredCode], catalog_order: list[str]) -> list[rc.FiredCode]:
    """Evidence strength (STRONG, MODERATE, WEAK), then |attribution_pp| descending, then catalog order.

    Codes with no attribution sort as 0 within their strength band. Attribution is never hidden: every code
    still carries its attribution_pp, and sort_by_attribution gives the model-attribution view.
    """
    position = {code: i for i, code in enumerate(catalog_order)}
    strength = {s: i for i, s in enumerate(EVIDENCE_STRENGTH_ORDER)}
    return sorted(reasons, key=lambda r: (strength[r.evidence_strength], -abs(r.attribution_pp or 0.0),
                                          position.get(r.code, len(position))))


def sort_by_attribution(reasons: list[rc.FiredCode], catalog_order: list[str]) -> list[rc.FiredCode]:
    """|attribution_pp| descending only (ties and missing attributions keep catalog order): what moved the score."""
    position = {code: i for i, code in enumerate(catalog_order)}
    return sorted(reasons, key=lambda r: (-abs(r.attribution_pp or 0.0), position.get(r.code, len(position))))


def explain_order(bundles: dict[str, dict], reference: dict, features: dict, discounted_links=(),
                  device_confirmed_accounts: int | None = None,
                  device_last_confirmed_days: float | None = None,
                  matured_returns: int | None = None, matured_orders: int | None = None,
                  catalog: dict[str, rc.CodeSpec] | None = None) -> OrderExplanation:
    """One order, both models, one batched ablation each. Probabilities and evidence only."""
    catalog = catalog or rc.load_catalog()
    abuse: Ablation = ablation(bundles["abuse"], reference, features, rc.GROUPS)
    returns: Ablation = ablation(bundles["return"], reference, features)

    evidence = rc.Evidence(features=features, discounted_links=tuple(discounted_links),
                           device_confirmed_accounts=device_confirmed_accounts,
                           device_last_confirmed_days=device_last_confirmed_days,
                           matured_returns=matured_returns, matured_orders=matured_orders)
    increases, mitigating = rc.fired_codes(
        evidence, {"ABUSE": abuse.deltas, "RETURN": returns.deltas}, catalog)

    order = list(catalog)
    return OrderExplanation(
        p_return=returns.p,
        p_abuse=abuse.p,
        p_abuse_without_graph_evidence=abuse.group_p[GRAPH_GROUP],
        prediction_explanation=prediction_explanation(abuse.group_delta_pp),
        reasons=sort_reasons(increases, order),
        mitigating_reasons=sort_reasons(mitigating, order),
        group_attribution_pp=dict(abuse.group_delta_pp),
        reason_code_version=rc.CATALOG_VERSION,
        attributions_by_magnitude=sort_by_attribution(increases, order),
    )
