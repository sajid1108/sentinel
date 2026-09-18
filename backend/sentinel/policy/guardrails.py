"""Corroborating signals (§9.2) and guardrails G1-G6 (§9.3).

Guardrails only remove actions. They never add cost and never pick the answer.
PREPAID_ONLY and MANUAL_REVIEW are never removed.

Pure: every time comparison uses the context's own decided_at, never a global clock.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sentinel.api.schemas import Action, EvidenceSignal, GuardrailResult
from sentinel.money import format_inr, format_probability
from sentinel.policy.config import PolicyConfig

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
# ACCOUNT_CLAIMS is evidence on the account itself, not a decayed link, so it carries full weight.
# Recency is controlled by the feature's 180-day window (prior_suspicious_claims_180d), and G2
# still needs a second signal, so a claim alone can never enable BLOCK.
ACCOUNT_CLAIMS_WEIGHT = 1.0

SIGNAL_ORDER = ("DEVICE", "PAYMENT_TOKEN", "ADDRESS", "TEMPORAL_BURST", "ACCOUNT_CLAIMS")
# G2: at least one counted signal must come from this set; ADDRESS can never be the anchor.
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
    """The five §9.2 signals, always in SIGNAL_ORDER.

    present = the evidence was observed; counts_for_corroboration = it also meets the §9.2 qualifiers.
    Observed-but-discounted evidence stays visible (with its weight) so reviewers can see what was
    deliberately not counted.
    """
    s = inputs

    device = (s.device_confirmed_abuse_weight >= CONFIRMED_ABUSE_WEIGHT_MIN
              or s.device_other_accounts_30d >= DEVICE_OTHER_ACCOUNTS_MIN)
    token = s.token_other_accounts_30d >= TOKEN_OTHER_ACCOUNTS_MIN
    address = s.address_confirmed_abuse_weight >= CONFIRMED_ABUSE_WEIGHT_MIN
    address_counts = address and not s.address_is_multi_tenant
    burst = (s.linked_orders_24h >= LINKED_ORDERS_24H_MIN
             or s.linked_same_sku_7d >= LINKED_SAME_SKU_7D_MIN)
    burst_counts = burst and bool(s.burst_link_kinds & BURST_LINK_KINDS)
    claims = s.prior_suspicious_claims_180d >= ACCOUNT_CLAIMS_MIN

    if address and not address_counts:
        address_detail = "Multi-tenant address; not counted."
    elif address:
        address_detail = (f"Confirmed-abuse weight {s.address_confirmed_abuse_weight:.2f} on this address; "
                          "cannot be the only independent signal.")
    else:
        address_detail = (f"Confirmed-abuse weight {s.address_confirmed_abuse_weight:.2f} on this address "
                          f"(needs {CONFIRMED_ABUSE_WEIGHT_MIN:.2f}).")
    if burst and not burst_counts:
        burst_detail = "Observed through address links only; not counted."
    else:
        burst_detail = (f"{s.linked_orders_24h} linked orders in 24 h, {s.linked_same_sku_7d} same-SKU "
                        f"linked orders in 7 d, via device or token links.")

    rows = [
        ("DEVICE", device, device, s.device_weight,
         f"Device: confirmed-abuse weight {s.device_confirmed_abuse_weight:.2f}, "
         f"{s.device_other_accounts_30d} other concurrent accounts in 30 d."),
        ("PAYMENT_TOKEN", token, token, s.token_weight,
         f"Payment token used by {s.token_other_accounts_30d} other accounts in 30 d."),
        ("ADDRESS", address, address_counts, s.address_weight, address_detail),
        ("TEMPORAL_BURST", burst, burst_counts, s.burst_weight, burst_detail),
        ("ACCOUNT_CLAIMS", claims, claims, ACCOUNT_CLAIMS_WEIGHT,
         f"{s.prior_suspicious_claims_180d} suspicious "
         f"{'claim' if s.prior_suspicious_claims_180d == 1 else 'claims'} on this account in 180 d."),
    ]
    return [
        EvidenceSignal(signal=name, present=present, weight=weight if present else 0.0,
                       counts_for_corroboration=counts, detail=detail)
        for name, present, counts, weight, detail in rows
    ]


@dataclass(frozen=True)
class DecisionContext:
    """Everything the policy may read.

    p_return is carried for the record only (G1): nothing reads it. Degraded contexts have no scores
    at all (p_abuse and p_return are None) and may have no graph state.
    """
    p_abuse: float | None
    p_return: float | None
    order_value_inr: float
    clv_inr: float
    signals: tuple[EvidenceSignal, ...]
    decided_at: datetime                     # DEMO_CLOCK when serving; placed_at in the backtest
    graph_state_as_of: datetime | None
    degraded: bool = False
    degraded_reason: str | None = None

    def __post_init__(self) -> None:
        if self.decided_at.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware")
        scores = (self.p_abuse, self.p_return)
        if self.degraded:
            if any(p is not None for p in scores):
                raise ValueError("degraded contexts carry no scores: p_abuse and p_return must be None")
        else:
            if any(p is None for p in scores):
                raise ValueError("p_abuse and p_return are required unless degraded")
            if not all(0.0 <= p <= 1.0 for p in scores):
                raise ValueError("probabilities must be in [0, 1]")
            if self.graph_state_as_of is None:
                raise ValueError("graph_state_as_of is required unless degraded")
        if self.order_value_inr <= 0:
            raise ValueError("order_value_inr must be > 0")
        if self.graph_state_as_of is not None:
            if self.graph_state_as_of.tzinfo is None:
                raise ValueError("graph_state_as_of must be timezone-aware")
            if self.graph_state_as_of > self.decided_at:
                raise ValueError("graph_state_as_of cannot be later than decided_at")
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
        detail = (f"G2 requires {_count_word(need)} corroborating signals; "
                  f"{_count_word(len(counted))} {verb} found.")
        if names:
            detail += f" Counted: {', '.join(names)}."
        return _result("G2", "BLOCK needs corroboration", [Action.BLOCK], detail)
    if not ANCHOR_SIGNALS & set(names):
        return _result("G2", "BLOCK needs corroboration", [Action.BLOCK],
                       "G2 requires at least one DEVICE, PAYMENT_TOKEN or ACCOUNT_CLAIMS signal; "
                       f"only {', '.join(names)} found.")
    return _result("G2", "BLOCK needs corroboration", [],
                   f"{_count_word(len(counted)).capitalize()} corroborating signals: {', '.join(names)}.")


def g3_block_needs_confidence(ctx: DecisionContext, cfg: PolicyConfig) -> GuardrailResult:
    need = cfg.guardrails.block_min_p_abuse
    need_shown = format_probability(need)
    shown = format_probability(ctx.p_abuse)
    if ctx.p_abuse < need:
        # At one decimal a score just below the threshold can render as the threshold itself, which
        # would read as a contradiction. Say what is true instead of printing the same figure twice.
        if shown == need_shown:
            shown = f"just under {need_shown}"
        return _result("G3", "BLOCK needs confidence", [Action.BLOCK],
                       f"G3 requires an abuse probability of at least {need_shown}; "
                       f"this order scored {shown}.")
    return _result("G3", "BLOCK needs confidence", [],
                   f"An abuse probability of {shown} meets the {need_shown} minimum for BLOCK.")


def g4_no_block_on_weak_or_stale_evidence(ctx: DecisionContext, cfg: PolicyConfig) -> GuardrailResult:
    name = "No BLOCK on weak or stale evidence"
    counted = ctx.counted_signals
    # With no counted signal at all, G2 already removes BLOCK; G4 is about weak or stale evidence.
    if counted and all(s.weight < WEAK_SIGNAL_WEIGHT for s in counted):
        return _result("G4", name, [Action.BLOCK],
                       f"G4 removes BLOCK because every counted signal has weight below {WEAK_SIGNAL_WEIGHT:.2f}.")
    if ctx.graph_state_as_of < ctx.decided_at - GRAPH_STATE_MAX_AGE:
        return _result("G4", name, [Action.BLOCK],
                       "G4 removes BLOCK because graph state is more than 24 hours older than the decision time.")
    return _result("G4", name, [], "Evidence is recent and at least one counted signal is strong.")


def g5_no_silent_allow_at_high_exposure(ctx: DecisionContext, cfg: PolicyConfig) -> GuardrailResult:
    g = cfg.guardrails
    detail = (f"G5 removes ALLOW when the abuse probability is at least "
              f"{format_probability(g.high_exposure_min_p_abuse)} and the order value is at least "
              f"{format_inr(g.high_exposure_value_inr)}.")
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
        detail=(f"Degraded mode ({reason}): no model score is available. {action.value} because the "
                f"order value is {comparison} {format_inr(floor)}. BLOCK is never selected in degraded mode."))
    return result, action


GUARDRAILS = (
    g1_return_probability_excluded,
    g2_block_needs_corroboration,
    g3_block_needs_confidence,
    g4_no_block_on_weak_or_stale_evidence,
    g5_no_silent_allow_at_high_exposure,
)
