"""Audit-event payload (§10.1), with deviation #14's optional scores for degraded decisions.

Every event is self-contained: an override or appeal event repeats the scores, costs, versions and graph
summary of the decision it concerns, so any single record can be read without joins.
"""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sentinel.api.schemas import Action, ActionCost, GraphEvidenceSummary, GuardrailResult

EventType = Literal["DECISION_CREATED", "OVERRIDE_APPLIED", "APPEAL_OPENED"]
OverrideReason = Literal["CUSTOMER_VERIFIED", "INDEPENDENT_EVIDENCE_OF_ABUSE",
                         "FALSE_POSITIVE_SHARED_IDENTIFIER", "POLICY_EXCEPTION", "OTHER"]


class AuditActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["SYSTEM", "REVIEWER"]
    id: str


class AuditModelVersions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    return_model: str
    abuse_model: str
    feature_set: str
    label_definition: str
    return_artifact_sha256: str
    abuse_artifact_sha256: str


class AuditOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason_category: OverrideReason
    reason_text: str
    reviewer_id: str
    reviewed_at: AwareDatetime
    guardrail_conflicts: list[str]


class AuditAppeal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    appeal_reference: str
    channel: Literal["CUSTOMER_SUPPORT", "EMAIL"]
    note: str
    status: Literal["OPEN"]


class AuditEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["audit-1.0"] = "audit-1.0"
    audit_event_id: str
    event_type: EventType
    occurred_at: AwareDatetime
    order_id: str
    decision_id: str
    actor: AuditActor

    # Prediction. p_return / p_abuse are None only for a degraded decision (#14): no score is invented.
    features_as_of: AwareDatetime
    p_return: float | None = Field(ge=0, le=1)
    p_abuse: float | None = Field(ge=0, le=1)
    p_abuse_without_graph_evidence: float | None
    reason_codes: list[str]
    feature_attributions_pp: dict[str, float]
    prediction_explanation: str
    graph_summary: GraphEvidenceSummary

    # Policy. cost_optimal_action is None only for a degraded decision (#14).
    candidate_actions: list[ActionCost]
    cost_optimal_action: Action | None
    selected_action: Action
    policy_rule: Literal["MIN_EXPECTED_COST", "MIN_EXPECTED_COST_WITHIN_GUARDRAILS", "DEGRADED_MODE_FALLBACK"]
    guardrails: list[GuardrailResult]
    policy_explanation: str
    policy_version: str
    policy_config_sha256: str
    model_versions: AuditModelVersions
    degraded_mode: bool

    # State transition
    original_recommendation: Action
    previous_action: Action | None
    new_action: Action
    override: AuditOverride | None
    appeal: AuditAppeal | None
