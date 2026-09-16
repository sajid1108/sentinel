from dataclasses import dataclass
import tomllib
from pathlib import Path
import hashlib


@dataclass(frozen=True)
class PolicyMeta:
    version: str
    currency: str
    notice: str
    tie_tolerance_inr: float


@dataclass(frozen=True)
class Economics:
    gross_margin_rate: float
    reverse_logistics_cost_inr: float


@dataclass(frozen=True)
class CLVConfig:
    new_customer_floor_inr: float
    cap_inr: float


@dataclass(frozen=True)
class AllowConfig:
    abuse_recovery_rate: float


@dataclass(frozen=True)
class PrepaidOnlyConfig:
    abuser_deterrence_rate: float
    abuse_recovery_rate: float
    genuine_abandonment_rate: float
    genuine_clv_churn_rate: float
    genuine_friction_cost_inr: float


@dataclass(frozen=True)
class ManualReviewConfig:
    review_cost_inr: float
    reviewer_detection_rate: float
    genuine_delay_abandonment_rate: float
    genuine_false_cancel_rate: float


@dataclass(frozen=True)
class BlockConfig:
    genuine_clv_churn_rate: float
    genuine_support_cost_inr: float


@dataclass(frozen=True)
class GuardrailsConfig:
    block_min_p_abuse: float
    block_min_corroborating_signals: int
    high_exposure_value_inr: float
    high_exposure_min_p_abuse: float
    degraded_review_min_value_inr: float


@dataclass(frozen=True)
class PolicyConfig:
    policy: PolicyMeta
    economics: Economics
    clv: CLVConfig
    allow: AllowConfig
    prepaid_only: PrepaidOnlyConfig
    manual_review: ManualReviewConfig
    block: BlockConfig
    guardrails: GuardrailsConfig
    config_sha256: str


_SECTIONS = {
    "policy": PolicyMeta,
    "economics": Economics,
    "clv": CLVConfig,
    "allow": AllowConfig,
    "prepaid_only": PrepaidOnlyConfig,
    "manual_review": ManualReviewConfig,
    "block": BlockConfig,
    "guardrails": GuardrailsConfig,
}


def _check_keys(data: dict) -> list[str]:
    """Missing or unknown sections/keys are errors: config keys are part of the frozen contract."""
    errors = []
    for section in sorted(set(data) - set(_SECTIONS)):
        errors.append(f"unknown section [{section}]")
    for section, cls in _SECTIONS.items():
        if section not in data:
            errors.append(f"missing section [{section}]")
            continue
        expected = set(cls.__dataclass_fields__)
        for key in sorted(expected - set(data[section])):
            errors.append(f"missing key {section}.{key}")
        for key in sorted(set(data[section]) - expected):
            errors.append(f"unknown key {section}.{key}")
    return errors


def load_policy_config(path: Path | None = None) -> PolicyConfig:
    if path is None:
        path = Path(__file__).parent.parent / "config" / "policy_v1_0.toml"
    raw = path.read_bytes()
    # Normalise line endings so a CRLF checkout hashes identically to LF.
    config_sha256 = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    data = tomllib.loads(raw.decode("utf-8"))

    key_errors = _check_keys(data)
    if key_errors:
        raise ValueError("; ".join(key_errors))

    guardrails = dict(data["guardrails"])
    guardrails["block_min_corroborating_signals"] = int(guardrails["block_min_corroborating_signals"])
    cfg = PolicyConfig(
        **{name: cls(**data[name]) for name, cls in _SECTIONS.items() if name != "guardrails"},
        guardrails=GuardrailsConfig(**guardrails),
        config_sha256=config_sha256,
    )
    errors = validate_policy_config(cfg)
    if errors:
        raise ValueError("; ".join(errors))
    return cfg


def validate_policy_config(cfg: PolicyConfig) -> list[str]:
    """Validate structural properties. Returns list of errors."""
    errors = []
    # All rates in [0, 1]
    rates = [
        ("economics.gross_margin_rate", cfg.economics.gross_margin_rate),
        ("allow.abuse_recovery_rate", cfg.allow.abuse_recovery_rate),
        ("prepaid_only.abuser_deterrence_rate", cfg.prepaid_only.abuser_deterrence_rate),
        ("prepaid_only.abuse_recovery_rate", cfg.prepaid_only.abuse_recovery_rate),
        ("prepaid_only.genuine_abandonment_rate", cfg.prepaid_only.genuine_abandonment_rate),
        ("prepaid_only.genuine_clv_churn_rate", cfg.prepaid_only.genuine_clv_churn_rate),
        ("manual_review.reviewer_detection_rate", cfg.manual_review.reviewer_detection_rate),
        ("manual_review.genuine_delay_abandonment_rate", cfg.manual_review.genuine_delay_abandonment_rate),
        ("manual_review.genuine_false_cancel_rate", cfg.manual_review.genuine_false_cancel_rate),
        ("block.genuine_clv_churn_rate", cfg.block.genuine_clv_churn_rate),
    ]
    for name, val in rates:
        if not 0 <= val <= 1:
            errors.append(f"{name} = {val} is outside [0, 1]")
    
    if cfg.manual_review.reviewer_detection_rate <= 0:
        errors.append("manual_review.reviewer_detection_rate must be > 0")
    
    if not 0.5 < cfg.guardrails.block_min_p_abuse < 1.0:
        errors.append(f"guardrails.block_min_p_abuse = {cfg.guardrails.block_min_p_abuse} should be in (0.5, 1.0)")
        
    if cfg.clv.new_customer_floor_inr > cfg.clv.cap_inr:
        errors.append("clv.new_customer_floor_inr must be <= clv.cap_inr")

    inr_vals = [
        ("policy.tie_tolerance_inr", cfg.policy.tie_tolerance_inr),
        ("economics.reverse_logistics_cost_inr", cfg.economics.reverse_logistics_cost_inr),
        ("clv.new_customer_floor_inr", cfg.clv.new_customer_floor_inr),
        ("clv.cap_inr", cfg.clv.cap_inr),
        ("prepaid_only.genuine_friction_cost_inr", cfg.prepaid_only.genuine_friction_cost_inr),
        ("manual_review.review_cost_inr", cfg.manual_review.review_cost_inr),
        ("block.genuine_support_cost_inr", cfg.block.genuine_support_cost_inr),
        ("guardrails.high_exposure_value_inr", cfg.guardrails.high_exposure_value_inr),
        ("guardrails.degraded_review_min_value_inr", cfg.guardrails.degraded_review_min_value_inr),
    ]
    for name, val in inr_vals:
        if val < 0:
            errors.append(f"{name} must be >= 0")

    if cfg.guardrails.block_min_corroborating_signals < 2:
        errors.append("guardrails.block_min_corroborating_signals must be >= 2")

    if not (0 < cfg.guardrails.high_exposure_min_p_abuse < cfg.guardrails.block_min_p_abuse):
        errors.append("guardrails.high_exposure_min_p_abuse must be in (0, block_min_p_abuse)")

    if not errors:
        errors.extend(check_slope_order(cfg).errors)
    return errors


# ── §8.4 slope-order check ────────────────────────────────────────────────────
# EC(a) is linear in p with slope A(a) - G(a). Severity is monotone in p only if
# slope(ALLOW) >= slope(PREPAID_ONLY) >= slope(MANUAL_REVIEW) >= slope(BLOCK).
SLOPE_GRID_MIN_VALUE_INR = 500
SLOPE_GRID_MAX_VALUE_INR = 200_000
SLOPE_GRID_POINTS = 61
SLOPE_ORDER = ("ALLOW", "PREPAID_ONLY", "MANUAL_REVIEW", "BLOCK")
# Accepted and documented: both actions are non-blocking (§8.4).
ACCEPTED_SLOPE_SWAPS = frozenset({("PREPAID_ONLY", "MANUAL_REVIEW")})


@dataclass(frozen=True)
class SlopeViolation:
    higher: str                 # action whose slope should be >= ...
    lower: str                  # ... this action's slope
    order_value_inr: float
    clv_inr: float
    slope_gap_inr: float        # slope(higher) - slope(lower); negative


@dataclass(frozen=True)
class SlopeOrderReport:
    violations: tuple[SlopeViolation, ...]
    info: tuple[str, ...]       # accepted swap regions
    errors: tuple[str, ...]     # any other ordering violation


def _slope_grid(cfg: PolicyConfig) -> tuple[list[float], list[float]]:
    ratio = SLOPE_GRID_MAX_VALUE_INR / SLOPE_GRID_MIN_VALUE_INR
    values = [SLOPE_GRID_MIN_VALUE_INR * ratio ** (i / (SLOPE_GRID_POINTS - 1)) for i in range(SLOPE_GRID_POINTS)]
    values[-1] = float(SLOPE_GRID_MAX_VALUE_INR)
    lo, hi = cfg.clv.new_customer_floor_inr, cfg.clv.cap_inr
    clvs = [lo + (hi - lo) * i / (SLOPE_GRID_POINTS - 1) for i in range(SLOPE_GRID_POINTS)]
    clvs[-1] = float(hi)
    return values, clvs


def check_slope_order(cfg: PolicyConfig) -> SlopeOrderReport:
    from sentinel.money import format_inr
    from sentinel.policy.costs import action_costs

    values, clvs = _slope_grid(cfg)
    violations = []
    for v in values:
        for clv in clvs:
            at_0 = action_costs(0.0, v, clv, cfg)
            at_1 = action_costs(1.0, v, clv, cfg)
            slope = {a.value: at_1[a].total - at_0[a].total for a in at_0}
            for higher, lower in zip(SLOPE_ORDER, SLOPE_ORDER[1:]):
                gap = slope[higher] - slope[lower]
                if gap < 0:
                    violations.append(SlopeViolation(higher, lower, v, clv, gap))

    info, errors = [], []
    for pair in sorted({(x.higher, x.lower) for x in violations}):
        region = [x for x in violations if (x.higher, x.lower) == pair]
        message = (f"slope({pair[0]}) < slope({pair[1]}) at {len(region)} grid points: "
                   f"V {format_inr(min(x.order_value_inr for x in region))}-"
                   f"{format_inr(max(x.order_value_inr for x in region))}, "
                   f"CLV {format_inr(min(x.clv_inr for x in region))}-"
                   f"{format_inr(max(x.clv_inr for x in region))}")
        if pair in ACCEPTED_SLOPE_SWAPS:
            info.append(message + "; both actions are non-blocking, accepted (§8.4)")
        else:
            errors.append(message)
    return SlopeOrderReport(tuple(violations), tuple(info), tuple(errors))
