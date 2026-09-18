"""Reviewer queue, order detail, override and appeal (§4; Phase 7 brief §B)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from sentinel.api.deps import get_reviewer_id, get_services, verify_internal_key
from sentinel.api.schemas import (AppealRequest, AuditEventOut, OrderDetailResponse, OverrideRequest,
                                  OverrideResponse, QueueFilters, QueueResponse)
from sentinel.api.services import order_view
from sentinel.api.services.runtime import AppServices
from sentinel.db.models import read_connection

router = APIRouter(tags=["internal"], dependencies=[Depends(verify_internal_key)])
Services = Annotated[AppServices, Depends(get_services)]


def fixed_threshold_taus(services: AppServices) -> tuple[float, float]:
    """(τ_review, τ_block) tuned on CALIBRATION and recorded in evaluation.json (§9.5)."""
    tuned = services.evaluation["backtest_details"]["fixed_threshold"]
    return tuned["tau_review"], tuned["tau_block"]


@router.get("/orders", response_model=QueueResponse)
def list_orders(filters: Annotated[QueueFilters, Query()], services: Services) -> QueueResponse:
    with read_connection(services.engine) as conn:
        return order_view.queue(conn, filters)


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def order_detail(order_id: str, services: Services) -> OrderDetailResponse:
    with read_connection(services.engine) as conn:
        return order_view.order_detail(conn, order_id, services.cfg, fixed_threshold_taus(services))


@router.post("/orders/{order_id}/override", response_model=OverrideResponse)
def override(order_id: str, request: OverrideRequest, services: Services,
             reviewer_id: Annotated[str, Depends(get_reviewer_id)]) -> OverrideResponse:
    with services.lock:
        return services.review.apply_override(order_id, request, reviewer_id)


@router.post("/orders/{order_id}/appeal", response_model=AuditEventOut)
def appeal(order_id: str, request: AppealRequest, services: Services,
           reviewer_id: Annotated[str, Depends(get_reviewer_id)]) -> AuditEventOut:
    """Placeholder lifecycle (§14.2): opens an appeal and returns its APPEAL_OPENED audit event."""
    with services.lock:
        result = services.review.open_appeal(order_id, request, reviewer_id)
    with read_connection(services.engine) as conn:
        row = conn.execute("SELECT * FROM audit_events WHERE event_id = ?", (result.audit_event_id,)).fetchone()
        return order_view.audit_event_out(row)
