"""Comparison strategies (§9.5). They exist to be compared against Sentinel, not to make decisions."""
from sentinel.api.schemas import Action, BaselineOutcome, PaymentMethod
from sentinel.money import format_inr

# RULE_BASED: the "conflated" merchant status quo, fixed rules (not policy config).
RULE_RETURN_RATE_MIN = 0.5
RULE_MATURED_RETURNS_MIN = 5
RULE_NEW_ACCOUNT_MAX_AGE_DAYS = 30
RULE_NEW_ACCOUNT_VALUE_INR = 15_000
RULE_COD_VALUE_INR = 5_000


def fixed_threshold(p_abuse: float, tau_block: float, tau_review: float) -> BaselineOutcome:
    """Same abuse model, no value or CLV awareness. Thresholds are tuned on CALIBRATION only (P13)."""
    if not 0.0 <= tau_review <= tau_block <= 1.0:
        raise ValueError("thresholds must satisfy 0 <= tau_review <= tau_block <= 1")
    if p_abuse >= tau_block:
        return BaselineOutcome(strategy="FIXED_THRESHOLD", action=Action.BLOCK,
                               rule_fired=f"p_abuse >= {tau_block:.2f}")
    if p_abuse >= tau_review:
        return BaselineOutcome(strategy="FIXED_THRESHOLD", action=Action.MANUAL_REVIEW,
                               rule_fired=f"p_abuse >= {tau_review:.2f}")
    return BaselineOutcome(strategy="FIXED_THRESHOLD", action=Action.ALLOW,
                           rule_fired=f"p_abuse < {tau_review:.2f}")


def rule_based(matured_return_rate: float | None, matured_returns: int, account_age_days: int,
               order_value_inr: float, payment_method: PaymentMethod) -> BaselineOutcome:
    """First matching rule wins, in the §9.5 order."""
    if (matured_return_rate is not None and matured_return_rate >= RULE_RETURN_RATE_MIN
            and matured_returns >= RULE_MATURED_RETURNS_MIN):
        return BaselineOutcome(strategy="RULE_BASED", action=Action.BLOCK,
                               rule_fired="matured return rate >= 0.5 and >= 5 returns")
    if account_age_days < RULE_NEW_ACCOUNT_MAX_AGE_DAYS and order_value_inr >= RULE_NEW_ACCOUNT_VALUE_INR:
        return BaselineOutcome(strategy="RULE_BASED", action=Action.MANUAL_REVIEW,
                               rule_fired=f"new account (< 30 d) and value >= {format_inr(RULE_NEW_ACCOUNT_VALUE_INR)}")
    if payment_method == "COD" and order_value_inr >= RULE_COD_VALUE_INR:
        return BaselineOutcome(strategy="RULE_BASED", action=Action.PREPAID_ONLY,
                               rule_fired=f"COD and value >= {format_inr(RULE_COD_VALUE_INR)}")
    return BaselineOutcome(strategy="RULE_BASED", action=Action.ALLOW, rule_fired="no rule fired")


def allow_all() -> Action:
    """Reference strategy for "loss prevented". Not a BaselineOutcome: §4 lists only two baseline strategies."""
    return Action.ALLOW
