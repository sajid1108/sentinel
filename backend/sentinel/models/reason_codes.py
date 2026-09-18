"""Evidence -> reason codes -> deterministic reviewer text (§6.5, as amended by deviation #27).

Codes are EVIDENCE statements, not attribution statements. A code fires when its catalog predicate is
true, full stop. Attribution never gates firing: a link the reviewer can act on must stay visible even
when a correlated feature absorbed the model's split for it. Where a fired code's own attribution is
negligible, it says so in `attribution_note` rather than disappearing.

Templates are fixed strings filled from recorded evidence. No LLM text, no SHAP. Rendered text never
contains a raw feature name, a threshold, a model version or a probability; counts and ages are fine.
"""
from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from sentinel.features import definitions

CATALOG_FILE = Path(__file__).resolve().parent.parent / "config" / "reason_codes.toml"

# A fired code whose own ablation delta is below this says so, instead of vanishing (#27).
REDUNDANT_ATTRIBUTION_PP = 2.0
REDUNDANT_NOTE = ("Redundant with other relationship evidence; the score is already explained by "
                  "correlated features.")

# §6.1 component smoothing: ratio = (confirmed + 1) / (size + 10), so the confirmed count is exact.
COMPONENT_PRIOR_CONFIRMED = 1
COMPONENT_PRIOR_ACCOUNTS = 10

_COMPARISONS = {ast.GtE: lambda a, b: a >= b, ast.Gt: lambda a, b: a > b,
                ast.LtE: lambda a, b: a <= b, ast.Lt: lambda a, b: a < b,
                ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}


class CatalogError(ValueError):
    """The reason-code catalog is malformed or names something the evidence cannot supply."""


@dataclass(frozen=True)
class CodeSpec:
    code: str
    model: str
    direction: str
    predicate: str
    template: str
    evidence_strength: str
    min_attribution_pp: float
    template_unconfirmed_counts: str | None = None


@dataclass(frozen=True)
class FiredCode:
    code: str
    model: str
    direction: str
    reviewer_text: str
    evidence: dict
    attribution_pp: float | None
    evidence_strength: str
    attribution_note: str | None = None


@dataclass(frozen=True)
class Evidence:
    """Everything the catalog may read about one order. Features plus link facts; never a label."""
    features: dict
    discounted_links: tuple = ()
    # Supplied by a later phase (#28); when absent the device code renders its counts-free wording.
    device_confirmed_accounts: int | None = None
    device_last_confirmed_days: float | None = None
    extra: dict = field(default_factory=dict)

    def predicate_scope(self) -> dict:
        scope = dict(self.features)
        scope["has_discounted_links"] = bool(self.discounted_links)
        scope.update(self.extra)
        return scope


def load_catalog(path: Path = CATALOG_FILE) -> dict[str, CodeSpec]:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for code, body in raw.get("codes", {}).items():
        try:
            out[code] = CodeSpec(
                code=code, model=body["model"], direction=body["direction"], predicate=body["predicate"],
                template=body["template"], evidence_strength=body["evidence_strength"],
                min_attribution_pp=float(body["min_attribution_pp"]),
                template_unconfirmed_counts=body.get("template_unconfirmed_counts"))
        except KeyError as exc:
            raise CatalogError(f"reason code {code!r} is missing {exc.args[0]!r}") from exc
    if not out:
        raise CatalogError(f"no reason codes in {path}")
    return out


CATALOG_VERSION = tomllib.loads(CATALOG_FILE.read_text(encoding="utf-8"))["meta"]["version"]


# -- predicates --------------------------------------------------------------
def _evaluate(node: ast.AST, scope: dict):
    """A deliberately tiny expression language: names, numbers, comparisons and `and`. No eval()."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, scope)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        return all(_evaluate(v, scope) for v in node.values)
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, scope)
        for op, right_node in zip(node.ops, node.comparators):
            compare = _COMPARISONS.get(type(op))
            if compare is None:
                raise CatalogError(f"unsupported comparison {type(op).__name__} in a predicate")
            right = _evaluate(right_node, scope)
            if not compare(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        if node.id not in scope:
            raise CatalogError(f"predicate refers to {node.id!r}, which the evidence does not carry")
        return scope[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    raise CatalogError(f"unsupported expression {type(node).__name__} in a predicate")


def fires(spec: CodeSpec, evidence: Evidence) -> bool:
    return bool(_evaluate(ast.parse(spec.predicate, mode="eval"), evidence.predicate_scope()))


# -- evidence and text -------------------------------------------------------
def component_confirmed_accounts(features: dict) -> int:
    """Invert the §6.1 smoothing to recover the confirmed count the ratio was built from."""
    size = float(features["component_size_reliable_90d"])
    ratio = float(features["component_abuse_ratio_smoothed"])
    return int(round(ratio * (size + COMPONENT_PRIOR_ACCOUNTS) - COMPONENT_PRIOR_CONFIRMED))


def code_evidence(spec: CodeSpec, evidence: Evidence) -> dict:
    """The recorded values behind one fired code. Keys are reviewer-facing, not feature names."""
    f = evidence.features
    if spec.code == "GRAPH_DEVICE_CONFIRMED_LINK":
        out: dict = {"other_accounts_on_device_30d": int(f["device_other_accounts_30d"])}
        if evidence.device_confirmed_accounts is not None:
            out["confirmed_accounts"] = int(evidence.device_confirmed_accounts)
        if evidence.device_last_confirmed_days is not None:
            out["days_since_confirmation"] = round(float(evidence.device_last_confirmed_days), 1)
        return out
    if spec.code == "GRAPH_DEVICE_SHARED":
        return {"other_accounts_30d": int(f["device_other_accounts_30d"])}
    if spec.code == "GRAPH_TOKEN_REUSE":
        return {"other_accounts": int(f["token_other_accounts_30d"])}
    if spec.code == "GRAPH_COMMUNITY_RISK":
        return {"group_size": int(f["component_size_reliable_90d"]),
                "confirmed_accounts": component_confirmed_accounts(f)}
    if spec.code == "TEMPORAL_BURST":
        return {"linked_orders_24h": int(f["linked_orders_24h"])}
    if spec.code == "SAME_SKU_COORDINATION":
        return {"same_item_orders_7d": int(f["linked_same_sku_7d"])}
    if spec.code == "ACCOUNT_PRIOR_SUSPICIOUS_CLAIM":
        return {"flagged_claims_180d": int(f["prior_suspicious_claims_180d"])}
    if spec.code == "NEW_ACCOUNT_HIGH_VALUE":
        return {"account_age_days": round(float(f["account_age_days"]), 1),
                "order_value_inr": float(f["order_value_inr"])}
    if spec.code == "MITIGATING_ESTABLISHED_ACCOUNT":
        return {"account_age_days": round(float(f["account_age_days"]), 1),
                "prior_orders": int(f["prior_orders"])}
    if spec.code == "MITIGATING_DISCOUNTED_LINKS":
        link = evidence.discounted_links[0]
        return {"kind": link.kind.replace("_", " ").lower(),
                "reason": link.reason.replace("_", " ").lower()}
    if spec.code == "RETURN_SIZE_BRACKETING":
        return {"variants": int(f["n_variants_same_product"])}
    if spec.code == "RETURN_HIGH_HISTORY":
        return {"return_rate_pct": round(float(f["matured_return_rate_smoothed"]) * 100)}
    raise CatalogError(f"no evidence mapping for reason code {spec.code!r}")


def render(spec: CodeSpec, evidence: Evidence, values: dict) -> str:
    if spec.code == "GRAPH_DEVICE_CONFIRMED_LINK":
        if "confirmed_accounts" not in values or "days_since_confirmation" not in values:
            return spec.template_unconfirmed_counts
        return spec.template.format(n=values["confirmed_accounts"], days=values["days_since_confirmation"])
    if spec.code == "GRAPH_DEVICE_SHARED":
        return spec.template.format(n=values["other_accounts_30d"])
    if spec.code == "GRAPH_TOKEN_REUSE":
        return spec.template.format(n=values["other_accounts"])
    if spec.code == "GRAPH_COMMUNITY_RISK":
        return spec.template.format(size=values["group_size"], k=values["confirmed_accounts"])
    if spec.code == "TEMPORAL_BURST":
        return spec.template.format(n=values["linked_orders_24h"])
    if spec.code == "SAME_SKU_COORDINATION":
        return spec.template.format(n=values["same_item_orders_7d"])
    if spec.code == "ACCOUNT_PRIOR_SUSPICIOUS_CLAIM":
        return spec.template.format(n=values["flagged_claims_180d"])
    if spec.code == "MITIGATING_DISCOUNTED_LINKS":
        return spec.template.format(kind=values["kind"], reason=values["reason"])
    if spec.code == "RETURN_HIGH_HISTORY":
        return spec.template.format(rate=values["return_rate_pct"])
    return spec.template


# Which feature's ablation delta a code reports. A code about several features reports the strongest.
CODE_FEATURES: dict[str, tuple[str, ...]] = {
    "GRAPH_DEVICE_CONFIRMED_LINK": ("device_confirmed_abuse_weight",),
    "GRAPH_DEVICE_SHARED": ("device_other_accounts_30d",),
    "GRAPH_TOKEN_REUSE": ("token_other_accounts_30d",),
    "GRAPH_COMMUNITY_RISK": ("component_abuse_ratio_smoothed", "component_size_reliable_90d"),
    "TEMPORAL_BURST": ("linked_orders_24h",),
    "SAME_SKU_COORDINATION": ("linked_same_sku_7d",),
    "ACCOUNT_PRIOR_SUSPICIOUS_CLAIM": ("prior_suspicious_claims_180d",),
    "NEW_ACCOUNT_HIGH_VALUE": ("account_age_days", "order_value_inr"),
    "MITIGATING_ESTABLISHED_ACCOUNT": ("account_age_days", "prior_orders"),
    "MITIGATING_DISCOUNTED_LINKS": (),
    "RETURN_SIZE_BRACKETING": ("n_variants_same_product",),
    "RETURN_HIGH_HISTORY": ("matured_return_rate_smoothed",),
}


def _attribution_for(spec: CodeSpec, attributions: dict[str, dict[str, float]]) -> float | None:
    deltas = attributions.get(spec.model, {})
    candidates = [deltas[f] for f in CODE_FEATURES.get(spec.code, ()) if f in deltas]
    if not candidates:
        return None
    return max(candidates, key=abs)


def fired_codes(evidence: Evidence, attributions: dict[str, dict[str, float]],
                catalog: dict[str, CodeSpec] | None = None) -> tuple[list[FiredCode], list[FiredCode]]:
    """(increasing, mitigating) codes, in catalog order.

    `attributions` is {"ABUSE": {feature: pp}, "RETURN": {feature: pp}}. It decides the reported
    attribution_pp and the redundancy note, never whether a code fires (#27).
    """
    catalog = catalog or load_catalog()
    increases: list[FiredCode] = []
    decreases: list[FiredCode] = []
    for spec in catalog.values():
        if not fires(spec, evidence):
            continue
        values = code_evidence(spec, evidence)
        pp = _attribution_for(spec, attributions)
        note = REDUNDANT_NOTE if pp is not None and abs(pp) < REDUNDANT_ATTRIBUTION_PP else None
        fired = FiredCode(spec.code, spec.model, spec.direction, render(spec, evidence, values), values,
                          None if pp is None else round(pp, 4), spec.evidence_strength, note)
        (increases if spec.direction == "INCREASES" else decreases).append(fired)
    return increases, decreases


# -- group dominance for the prediction explanation (§6.5 level 1) ------------
ACCOUNT_FEATURES: tuple[str, ...] = ("account_age_days", "prior_orders", "prior_suspicious_claims_180d")
# Exposure, not evidence: how much the order is worth and what it contains says nothing about
# coordination, and neither appears among the §9.2 corroborating signals. Both stay in the model - they
# are predictive - but they are excluded from the dominance groups, because "this order is expensive"
# is not an explanation a reviewer can act on and would otherwise drown the real evidence (#29).
EXPOSURE_FEATURES: tuple[str, ...] = ("order_value_inr", "primary_category")
GROUP_PRECEDENCE: tuple[str, ...] = ("graph", "account", "order")
_NON_ORDER = set(definitions.ABUSE_GRAPH_FEATURES) | set(ACCOUNT_FEATURES) | set(EXPOSURE_FEATURES)
GROUPS: dict[str, tuple[str, ...]] = {
    "graph": definitions.ABUSE_GRAPH_FEATURES,
    "account": ACCOUNT_FEATURES,
    "order": tuple(f for f in definitions.ABUSE_FEATURES if f not in _NON_ORDER),
}
