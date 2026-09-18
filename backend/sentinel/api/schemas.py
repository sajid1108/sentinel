# backend/sentinel/api/schemas.py
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
HashedId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]   # raw PII cannot pass


class Action(StrEnum):
    ALLOW = "ALLOW"
    PREPAID_ONLY = "PREPAID_ONLY"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    BLOCK = "BLOCK"


SEVERITY: dict[Action, int] = {Action.ALLOW: 0, Action.PREPAID_ONLY: 1,
                               Action.MANUAL_REVIEW: 2, Action.BLOCK: 3}

Category = Literal["APPAREL", "FOOTWEAR", "ELECTRONICS", "BEAUTY", "HOME", "ACCESSORIES"]
PaymentMethod = Literal["PREPAID_CARD", "PREPAID_UPI", "COD"]


class Money(Contract):
    inr: float
    display: str                                   # "₹1,490" — formatted once, server-side


# POST /score-order
class OrderLineIn(Contract):
    sku_id: str
    product_id: str
    variant: str
    category: Category
    unit_price_inr: float = Field(gt=0, le=500_000)
    quantity: int = Field(ge=1, le=20)


class ScoreOrderRequest(Contract):
    """Internal order representation at t0 = after payment-method selection, before confirmation."""
    order_id: str = Field(pattern=r"^ORD-[A-Z0-9-]{3,40}$")
    account_id: str = Field(pattern=r"^ACC-[A-Z0-9-]{3,40}$")
    placed_at: AwareDatetime
    lines: list[OrderLineIn] = Field(min_length=1, max_length=50)
    discount_pct: float = Field(ge=0, le=90)
    delivery_speed: Literal["STANDARD", "EXPRESS"]
    payment_method: PaymentMethod
    device_id: HashedId
    address_id: HashedId
    payment_token_id: HashedId | None = None

    @model_validator(mode="after")
    def _token_matches_payment_method(self) -> "ScoreOrderRequest":
        if (self.payment_method == "COD") != (self.payment_token_id is None):
            raise ValueError("payment_token_id must be null for COD and present for prepaid")
        return self


class Scores(Contract):
    p_return: Probability | None                           # None only in degraded mode (no model score)
    p_abuse: Probability | None
    p_abuse_without_graph_evidence: Probability | None
    return_model_version: str
    abuse_model_version: str
    feature_set_version: str
    p_return_used_for_action: Literal[False] = False


class ReasonCode(Contract):
    code: str
    model: Literal["RETURN", "ABUSE"]
    direction: Literal["INCREASES", "DECREASES"]
    reviewer_text: str
    evidence: dict[str, float | int | str]
    attribution_pp: float | None
    evidence_strength: Literal["STRONG", "MODERATE", "WEAK"]
    # Set when a fired code's own ablation delta is negligible: the evidence is real but a correlated
    # feature already carries it in the score. Optional, so existing payloads stay valid (#27).
    attribution_note: str | None = None


class EvidenceSignal(Contract):
    signal: Literal["DEVICE", "PAYMENT_TOKEN", "ADDRESS", "TEMPORAL_BURST", "ACCOUNT_CLAIMS"]
    present: bool
    weight: float
    counts_for_corroboration: bool
    detail: str


class DiscountedLink(Contract):
    identifier_label: str
    kind: Literal["DEVICE", "ADDRESS", "PAYMENT_TOKEN"]
    reason: Literal["MULTI_TENANT_ADDRESS", "SEQUENTIAL_DEVICE_USE", "STALE_RELATIONSHIP",
                    "HIGH_FANOUT_IDENTIFIER", "HOUSEHOLD_PATTERN"]
    weight: float


class GraphEvidenceSummary(Contract):
    component_size_reliable_90d: int
    confirmed_abusive_accounts_in_component: int
    min_hops_to_confirmed_abuse: int | None
    linked_orders_24h: int
    corroborating_signal_count: int
    signals: list[EvidenceSignal]
    discounted_links: list[DiscountedLink]
    weak_evidence_only: bool


class ActionCost(Contract):
    action: Action
    expected_cost: Money
    abusive_branch: Money
    genuine_branch: Money
    operational: Money
    feasible: bool
    excluded_by: list[str]
    rank_by_cost: int


class GuardrailResult(Contract):
    guardrail_id: Literal["G1", "G2", "G3", "G4", "G5", "G6"]
    name: str
    triggered: bool
    effect: Literal["NONE", "REMOVED_ACTIONS", "FALLBACK"]
    removed_actions: list[Action]
    detail: str


class PolicyDecision(Contract):
    policy_version: str
    policy_config_sha256: str
    cost_optimal_action: Action | None                     # None only in degraded mode
    selected_action: Action
    selected_rule: Literal["MIN_EXPECTED_COST", "MIN_EXPECTED_COST_WITHIN_GUARDRAILS",
                           "DEGRADED_MODE_FALLBACK"]
    costs: list[ActionCost]
    guardrails: list[GuardrailResult]
    policy_explanation: str
    assumptions_notice: Literal["Monetary values are demonstration assumptions (policy v1.0)."]

    @model_validator(mode="after")
    def _decision_invariants(self) -> "PolicyDecision":
        if self.selected_rule == "DEGRADED_MODE_FALLBACK":
            # No model score exists, so no cost may be shown as if it had been calculated.
            if self.costs:
                raise ValueError("degraded decisions carry no costs")
            if self.cost_optimal_action is not None:
                raise ValueError("degraded decisions have no cost_optimal_action")
            return self
        if self.cost_optimal_action is None:
            raise ValueError("cost_optimal_action is required unless degraded")
        by_action = {c.action: c for c in self.costs}
        if len(self.costs) != len(Action) or set(by_action) != set(Action):
            raise ValueError("costs must contain all four actions exactly once")
        if not by_action[Action.PREPAID_ONLY].feasible or not by_action[Action.MANUAL_REVIEW].feasible:
            raise ValueError("PREPAID_ONLY and MANUAL_REVIEW must always be feasible")
        sel = by_action[self.selected_action]
        if not sel.feasible:
            raise ValueError("selected action is infeasible")
        best_feasible = min(c.expected_cost.inr for c in self.costs if c.feasible)
        best_overall = min(c.expected_cost.inr for c in self.costs)
        if sel.expected_cost.inr - best_feasible > 1.0:
            raise ValueError("selected action is not the minimum feasible expected cost")
        if by_action[self.cost_optimal_action].expected_cost.inr - best_overall > 1.0:
            raise ValueError("cost_optimal_action is not the minimum expected cost")
        if (self.selected_action == self.cost_optimal_action) != (self.selected_rule == "MIN_EXPECTED_COST"):
            raise ValueError("selected_rule inconsistent with selected vs cost-optimal action")
        return self


class ScoreOrderResponse(Contract):
    decision_id: str
    order_id: str
    scored_at: AwareDatetime
    features_as_of: AwareDatetime
    scores: Scores
    prediction_explanation: str
    reasons: list[ReasonCode]
    graph_summary: GraphEvidenceSummary
    policy: PolicyDecision
    status: Literal["AUTO_APPLIED", "PENDING_REVIEW", "OVERRIDDEN", "APPEAL_OPEN"]
    audit_event_id: str
    degraded_mode: bool
    idempotent_replay: bool


# GET /orders
class QueueFilters(Contract):
    action: Action | None = None
    status: Literal["AUTO_APPLIED", "PENDING_REVIEW", "OVERRIDDEN", "APPEAL_OPEN"] | None = None
    source: Literal["DEMO", "BACKTEST_REPLAY", "LIVE"] | None = None
    min_p_abuse: Probability | None = None
    min_value_inr: float | None = None
    graph_evidence: Literal["ANY", "STRONG", "WEAK_ONLY", "NONE"] = "ANY"
    sort: Literal["scored_at_desc", "p_abuse_desc", "value_desc", "exposure_desc"] = "scored_at_desc"
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class QueueItem(Contract):
    order_id: str
    decision_id: str
    scored_at: AwareDatetime
    order_value: Money
    p_return: Probability | None                           # None only for degraded decisions
    p_abuse: Probability | None
    recommended_action: Action
    current_action: Action
    status: Literal["AUTO_APPLIED", "PENDING_REVIEW", "OVERRIDDEN", "APPEAL_OPEN"]
    graph_risk_summary: str
    corroborating_signal_count: int
    source: Literal["DEMO", "BACKTEST_REPLAY", "LIVE"]


class QueueResponse(Contract):
    items: list[QueueItem]
    total: int
    counts_by_action: dict[Action, int]


# GET /orders/{order_id}
class CustomerSummary(Contract):
    account_id: str
    account_age_days: int
    prior_orders: int
    matured_return_rate: float | None
    prior_suspicious_claims_180d: int
    clv_used_by_policy: Money
    clv_basis: Literal["HISTORY", "NEW_CUSTOMER_FLOOR", "CAPPED"]


class OrderSummary(Contract):
    order_id: str
    placed_at: AwareDatetime
    order_value: Money
    discount_pct: float
    lines: list[OrderLineIn]
    payment_method: PaymentMethod
    delivery_speed: Literal["STANDARD", "EXPRESS"]


class GraphNode(Contract):
    id: str
    kind: Literal["ACCOUNT", "ORDER", "DEVICE", "ADDRESS", "PAYMENT_TOKEN"]
    label: str
    state: Literal["CURRENT", "CONFIRMED_ABUSE", "LINKED", "NEUTRAL"]
    flags: list[Literal["MULTI_TENANT", "SEQUENTIAL_DEVICE", "HIGH_FANOUT", "RECENT_24H"]]
    x: float
    y: float


class GraphEdge(Contract):
    id: str
    source: str
    target: str
    kind: Literal["USED_DEVICE", "USED_TOKEN", "SHIPPED_TO", "PLACED_BY"]
    age_days: float
    reliability: float
    decayed_weight: float
    counted_as_evidence: bool
    discount_reason: str | None


class GraphPayload(Contract):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    hidden_node_count: int
    as_of: AwareDatetime
    # What the drawn graph actually accounts for, so the UI never prints a count the picture contradicts
    # (Phase 8 brief 1.1, #35). Equal to graph_summary.linked_orders_24h and device_confirmed_peer_count
    # unless the node cap truncated the graph.
    linked_orders_24h_shown: int
    confirmed_peers_shown: int


class BaselineOutcome(Contract):
    strategy: Literal["FIXED_THRESHOLD", "RULE_BASED"]
    action: Action
    rule_fired: str


class AuditEventOut(Contract):
    seq: int
    event_id: str
    event_type: Literal["DECISION_CREATED", "OVERRIDE_APPLIED", "APPEAL_OPENED"]
    occurred_at: AwareDatetime
    order_id: str
    actor_type: Literal["SYSTEM", "REVIEWER"]
    actor_id: str
    previous_action: Action | None
    new_action: Action
    policy_version: str
    return_model_version: str
    abuse_model_version: str
    payload: dict
    prev_hash: str
    event_hash: str


class OrderDetailResponse(Contract):
    order: OrderSummary
    customer: CustomerSummary
    decision: ScoreOrderResponse
    graph: GraphPayload
    baselines: list[BaselineOutcome]
    audit_events: list[AuditEventOut]
    current_action: Action
    appeal_reference: str | None


# POST /orders/{order_id}/override
OverrideReason = Literal["CUSTOMER_VERIFIED", "INDEPENDENT_EVIDENCE_OF_ABUSE",
                         "FALSE_POSITIVE_SHARED_IDENTIFIER", "POLICY_EXCEPTION", "OTHER"]


class OverrideRequest(Contract):
    new_action: Action
    reason_category: OverrideReason
    reason_text: str = Field(min_length=15, max_length=1000)
    expected_current_action: Action


class OverrideResponse(Contract):
    order_id: str
    decision_id: str
    original_recommendation: Action
    previous_action: Action
    new_action: Action
    reviewer_id: str
    overridden_at: AwareDatetime
    audit_event_id: str
    warnings: list[str]


class AppealRequest(Contract):
    channel: Literal["CUSTOMER_SUPPORT", "EMAIL"]
    note: str = Field(min_length=10, max_length=1000)


# GET /audit-events
class AuditEventsResponse(Contract):
    items: list[AuditEventOut]
    total: int


class AuditVerifyResponse(Contract):
    valid: bool
    events_checked: int
    first_broken_seq: int | None


# GET /metrics
class DecisionActivity(Contract):
    orders_evaluated: int
    action_distribution: dict[Action, int]
    friction_orders: int
    manual_review_volume: int
    override_rate: float
    model_estimated_cost_avoided: Money
    explanation_coverage: float
    version_traceability: float
    weak_evidence_decisions: int


class StrategyBacktest(Contract):
    strategy: Literal["SENTINEL", "FIXED_THRESHOLD", "RULE_BASED", "ALLOW_ALL"]
    realized_cost_per_1000: Money
    abuse_loss_prevented: Money
    genuine_block_rate: float
    customer_friction_rate: float
    manual_reviews_per_1000: float
    cost_per_detected_abuse: Money
    revenue_preserved: Money
    precision_block: float
    recall_intercepted: float


class CalibrationPoint(Contract):
    bin_mean_predicted: float
    observed_rate: float
    count: int


class ModelEvaluation(Contract):
    model: Literal["RETURN", "ABUSE"]
    model_version: str
    pr_auc: float
    pr_auc_ci95: tuple[float, float]
    brier: float
    ece_10bin_quantile: float
    calibration_curve: list[CalibrationPoint]
    by_value_band: dict[str, dict[str, float]]
    by_cohort: dict[str, dict[str, float]]


class MetricsResponse(Contract):
    activity: DecisionActivity
    backtest: list[StrategyBacktest]
    models: list[ModelEvaluation]
    cold_start_ring_recall: float
    sensitivity: list[dict[str, float | str]]
    drift_monitoring: Literal["PLACEHOLDER_NOT_COMPUTED"]
    data_notice: Literal[
        "Synthetic data is used to validate the architecture, policy behaviour, auditability, "
        "and coordinated-pattern detection. Real deployment would require merchant-specific "
        "historical data and prospective validation."
    ]


# GET /internal/policy — the demonstration assumptions panel (Phase 8 brief 1.2, #35)
class PolicyAssumptionValue(Contract):
    """One key of policy_v1_0.toml, exactly as the policy engine loaded it."""
    key: str
    value: float | str
    money: Money | None                                    # set for every *_inr key, formatted server-side


class PolicyAssumptionSection(Contract):
    section: str
    values: list[PolicyAssumptionValue]


class PolicyAssumptionsResponse(Contract):
    policy_version: str
    policy_config_sha256: str
    notice: str
    sections: list[PolicyAssumptionSection]


# PUBLIC: POST /checkout/decision
class CheckoutRequest(ScoreOrderRequest):
    """Public checkout payload. Validation is identical to ScoreOrderRequest by construction."""


class CheckoutOutcome(Contract):
    order_id: str
    outcome: Literal["CONFIRMED", "PREPAID_PAYMENT_REQUIRED", "UNABLE_TO_PROCESS"]
    customer_message: str
    support_reference: str


