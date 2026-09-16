"""Corroborating signals (§9.2) and guardrails G1-G6 (§9.3).

Guardrails only remove actions. They never add cost and never pick the answer.
PREPAID_ONLY and MANUAL_REVIEW are never removed.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sentinel.api.schemas import Action, EvidenceSignal, GuardrailResult
from sentinel.money import format_inr
from sentinel.policy.config import PolicyConfig
from sentinel.settings import DEMO_CLOCK

# §9.2 thresholds. They define the signals themselves, so they are not policy config keys.
CONFIRMED_ABUSE_WEIGHT_MIN = 0.3
DEVICE_OTHER_ACCOUNTS_MIN = 3
TOKEN_OTHER_ACCOUNTS_MIN = 2
LINKED_ORDERS_24H_MIN = 3
LINKED_SAME_SKU_7D_MIN = 2
ACCOUNT_CLAIMS_MIN = 1
# G4
WEAK_SIGNAL_WEIGHT = 0.3
GRAPH_STATE_MAX_AGE = timedelta(hours=24)
# ACCOUNT_CLAIMS is evidence on the account itself, not a decayed link: full weight.
ACCOUNT_CLAIMS_WEIGHT = 1.0

SIGNAL_ORDER = ("DEVICE", "PAYMENT_TOKEN", "ADDRESS", "TEMPORAL_BURST", "ACCOUNT_CLAIMS")
# G2: at least one present signal must come from this set; ADDRESS can never be the anchor.
ANCHOR_SIGNALS = frozenset({"DEVICE", "PAYMENT_TOKEN", "ACCOUNT_CLAIMS"})
BURST_LINK_KINDS = frozenset({"DEVICE", "PAYMENT_TOKEN"})

_WORDS = ("none", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _count_word(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


@dataclass(frozen=True)
class SignalInputs:
    """Point-in-time evidence (§6.3 features plus link weights) from which §9.2 signals are derived.

    Each *_weight is the reliability x decay weight (§6.1) of the links that carry that signal.
    """
    device_confirmed_abuse_weight: float = 0.0
    device_other_accounts_30d: int = 0               # concurrent only; sequential use already excluded
    device_weight: float = 0.0
    token_other_accounts_30d: int = 0
    token_weight: float = 0.0
    address_is_multi_tenant: bool = False            # point-in-time flag (P7)
    address_confirmed_abuse_weight: float = 0.0
    address_weight: float = 0.0
    linked_orders_24h: int = 0
    linked_same_sku_7d: int = 0
    burst_link_kinds: frozenset[str] = field(default_factory=frozenset)  # link kinds joining the burst
    burst_weight: float = 0.0
    prior_suspicious_claims_180d: int = 0


def corroborating_signals(inputs: SignalInputs) -> list[EvidenceSignal]:
    """The five §9.2 signals, always in SIGNAL_ORDER."""
    s = inputs

    device = (s.device_confirmed_abuse_weight >= CONFIRMED_ABUSE_WEIGHT_MIN
              or s.device_other_accounts_30d >= DEVICE_OTHER_ACCOUNTS_MIN)
    token = s.token_other_accounts_30d >= TOKEN_OTHER_ACCOUNTS_MIN
    address = (not s.address_is_multi_tenant
               and s.address_confirmed_abuse_weight >= CONFIRMED_ABUSE_WEIGHT_MIN)
    burst_observed = (s.linked_orders_24h >= LINKED_ORDERS_24H_MIN
                      or s.linked_same_sku_7d >= LINKED_SAME_SKU_7D_MIN)
    burst_via_device_or_token = bool(s.burst_link_kinds & BURST_LINK_KINDS)
    burst = burst_observed and burst_via_device_or_token
    claims = s.prior_suspicious_claims_180d >= ACCOUNT_CLAIMS_MIN

    if s.address_is_multi_tenant and s.address_confirmed_abuse_weight >= CONFIRMED_ABUSE_WEIGHT_MIN:
        address_detail = "Multi-tenant address; confirmed-abuse links there are not evidence."
    else:
        address_detail = (f"Confirmed-abuse weight {s.address_confirmed_abuse_weight:.2f} on this address "
                          f"(needs {CONFIRMED_ABUSE_WEIGHT_MIN:.2f}); cannot be the only independent signal.")
    if burst_observed and not burst_via_device_or_token:
        burst_detail = "Linked-order burst reached only through address links; does not count."
    else:
        burst_detail = (f"{s.linked_orders_24h} linked orders in 24 h, {s.linked_same_sku_7d} same-SKU "
                        f"linked orders in 7 d, via device or token links.")

    rows = [
        ("DEVICE", device, s.device_weight,
         f"Device: confirmed-abuse weight {s.device_confirmed_abuse_weight:.2f}, "
         f"{s.device_other_accounts_30d} other concurrent accounts in 30 d."),
        ("PAYMENT_TOKEN", token, s.token_weight,
         f"Payment token used by {s.token_other_accounts_30d} other accounts in 30 d."),
        ("ADDRESS", address, s.address_weight, address_detail),
        ("TEMPORAL_BURST", burst, s.burst_weight, burst_detail),
        ("ACCOUNT_CLAIMS", claims, ACCOUNT_CLAIMS_WEIGHT,
         f"{s.prior_suspicious_claims_180d} suspicious claim(s) on this account in 180 d."),
    ]
    return [
        EvidenceSignal(signal=name, present=present, weight=weight if present else 0.0,
                       counts_for_corroboration=present, detail=detail)
        for name, present, weight, detail in rows
    ]


@dataclass(frozen=True)
class DecisionContext:
    """Everything the policy may read. p_return is carried for the record only (G1): nothing reads it."""
    p_abuse: float
    p_return: float
    order_value_inr: float
    clv_inr: float
    signals: tuple[EvidenceSignal, ...]
    graph_state_as_of: datetime
    degraded: bool = False
    degraded_reason: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.p_abuse <= 1.0 or not 0.0 <= self.p_return <= 1.0:
            raise ValueError("probabilities must be in [0, 1]")
        if self.order_value_inr <= 0:
            raise ValueError("order_value_inr must be > 0")
        if self.graph_state_as_of.tzinfo is None:
            raise ValueError("graph_state_as_of must be timezone-aware")
        object.__setattr__(self, "signals", tuple(self.signals))

    @property
    def counted_signals(self) -> list[EvidenceSignal]:
        return [s for s in self.signals if s.present and s.counts_for_corroboration]


def _result(gid: str, name: str, removed: list[Action], detail: str) -> GuardrailResult:
    return GuardrailResult(guardrail_id=gid, name=name, triggered=bool(removed),
                           effect="REMOVED_ACTIONS" if removed else "NONE",
                           removed_actions=removed, detail=detail)


def g1_return_probability_excluded(ctx: DecisionContext, cfg: PolicyConfig) -> GuardrailResult:
    return _result("G1", "Return probability excluded", [],
                   "p_return is not an input to expected cost or any guardrail; shown for context only.")


def g2_block_needs_corroboration(ctx: DecisionContext, cfg: PolicyConfig) -> GuardrailResult:
    counted = ctx.counted_signals
    names = [s.signal for s in counted]
    need = cfg.guardrails.block_min_corroborating_signals
    if len(counted) < need:
        verb = "was" if len(counted) <= 1 else "were"
        return _result("G2", "BLOCK needs corroboration", [Action.BLOCK],
                       f"G2 requires {_count_word(need)} corroborating signals; "
                       f"{_count_word(len(counted))} {verb} found.")
    if not ANCHOR_SIGNALS & set(names):
        return _result("G2", "BLOCK needs corroboration", [Action.BLOCK],
                       "G2 requires at least one DEVICE, PAYMENT_TOKEN or ACCOUNT_CLAIMS signal; "
                       f"only {', '.join(names)} found.")
    return _result("G2", "BLOCK needs corroboration", [],
                   f"{_count_word(len(counted)).capitalize()} corroborating signals: {', '.join(names)}.")


def g3_block_needs_confidence(ctx: DecisionContext, cfg: PolicyConfig) -> GuardrailResult:
    need = cfg.guardrails.block_min_p_abuse
    if ctx.p_abuse < need:
        return _result("G3", "BLOCK needs confidence", [Action.BLOCK],
                       f"G3 requires p_abuse of at least {need:.2f}; this order scored {ctx.p_abuse:.2f}.")
    return _result("G3", "BLOCK needs confidence", [],
                   f"p_abuse {ctx.p_abuse:.2f} meets the {need:.2f} minimum for BLOCK.")


def g4_no_block_on_weak_or_stale_evidence(ctx: DecisionContext, cfg: PolicyConfig) -> GuardrailResult:
    name = "No BLOCK on weak or stale evidence"
    present = [s for s in ctx.signals if s.present]
    # With no present signal at all, G2 already removes BLOCK; G4 is about weak or stale evidence.
    if present and all(s.weight < WEAK_SIGNAL_WEIGHT for s in present):
        return _result("G4", name, [Action.BLOCK],
                       f"G4 removes BLOCK because every present signal has weight below {WEAK_SIGNAL_WEIGHT:.2f}.")
    cutoff = DEMO_CLOCK - GRAPH_STATE_MAX_AGE
    if ctx.graph_state_as_of < cutoff:
        return _result("G4", name, [Action.BLOCK],
                       f"G4 removes BLOCK because graph state ({ctx.graph_state_as_of.isoformat()}) "
                       "is more than 24 hours old.")
    return _result("G4", name, [], "Evidence is recent and at least one signal is strong.")


def g5_no_silent_allow_at_high_exposure(ctx: DecisionContext, cfg: PolicyConfig) -> GuardrailResult:
    g = cfg.guardrails
    detail = (f"G5 removes ALLOW when p_abuse is at least {g.high_exposure_min_p_abuse:.2f} "
              f"and the order value is at least {format_inr(g.high_exposure_value_inr)}.")
    removed = ([Action.ALLOW]
               if ctx.p_abuse >= g.high_exposure_min_p_abuse and ctx.order_value_inr >= g.high_exposure_value_inr
               else [])
    return _result("G5", "No silent ALLOW at high exposure", removed,
                   detail if removed else "Exposure is below the G5 backstop.")


def g6_degraded_mode(ctx: DecisionContext, cfg: PolicyConfig) -> tuple[GuardrailResult, Action]:
    """Fallback when model, features or graph state are unavailable. Never BLOCK."""
    floor = cfg.guardrails.degraded_review_min_value_inr
    action = Action.MANUAL_REVIEW if ctx.order_value_inr >= floor else Action.ALLOW
    reason = ctx.degraded_reason or "model or graph state unavailable"
    comparison = "at least" if action is Action.MANUAL_REVIEW else "below"
    result = GuardrailResult(
        guardrail_id="G6", name="Degraded mode", triggered=True, effect="FALLBACK",
        removed_actions=[Action.BLOCK],
        detail=(f"Degraded mode ({reason}): {action.value} because the order value is {comparison} "
                f"{format_inr(floor)}. BLOCK is never selected in degraded mode."))
    return result, action


GUARDRAILS = (
    g1_return_probability_excluded,
    g2_block_needs_corroboration,
    g3_block_needs_confidence,
    g4_no_block_on_weak_or_stale_evidence,
    g5_no_silent_allow_at_high_exposure,
)
