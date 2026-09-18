"""GET /audit-events and GET /audit-events/verify (§4, §10.2)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from sentinel.api.deps import get_services, verify_internal_key
from sentinel.api.schemas import AuditEventsResponse, AuditVerifyResponse
from sentinel.api.services import order_view
from sentinel.api.services.runtime import AppServices
from sentinel.audit.service import verify_chain
from sentinel.db.models import read_connection

router = APIRouter(tags=["internal"], dependencies=[Depends(verify_internal_key)])
Services = Annotated[AppServices, Depends(get_services)]


@router.get("/audit-events", response_model=AuditEventsResponse)
def list_audit_events(services: Services, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                      offset: Annotated[int, Query(ge=0)] = 0,
                      order_id: Annotated[str | None, Query()] = None) -> AuditEventsResponse:
    with read_connection(services.engine) as conn:
        return order_view.audit_events(conn, limit, offset, order_id)


@router.get("/audit-events/verify", response_model=AuditVerifyResponse)
def verify_audit_chain(services: Services) -> AuditVerifyResponse:
    result = verify_chain(services.engine)
    return AuditVerifyResponse(valid=result.valid, events_checked=result.events_checked,
                               first_broken_seq=result.first_broken_seq)
