"""POST /api/v1/public/checkout/decision (§2 trust boundary, §4): outcome only, via the same ScoringService.

No internal key: this is the only public route. Errors carry a fixed generic body (see api/main.py) and
never echo request fields. Every call that reaches scoring writes one probe_events row.
"""
from typing import Annotated

from fastapi import APIRouter, Depends

from sentinel.api.deps import get_services
from sentinel.api.schemas import CheckoutOutcome, CheckoutRequest, ScoreOrderRequest
from sentinel.api.services import order_view
from sentinel.api.services.checkout import checkout_outcome, log_probe
from sentinel.api.services.runtime import AppServices
from sentinel.db.models import immediate_transaction, read_connection

router = APIRouter(tags=["public"])


@router.post("/checkout/decision", response_model=CheckoutOutcome)
def checkout_decision(request: CheckoutRequest,
                      services: Annotated[AppServices, Depends(get_services)]) -> CheckoutOutcome:
    with services.lock:
        try:
            decision = services.scoring.score(ScoreOrderRequest.model_validate(request.model_dump()), "LIVE")
            with read_connection(services.engine) as conn:
                action = order_view.current_action(conn, request.order_id)
        finally:                                             # logged whatever the outcome; never blocks
            with immediate_transaction(services.engine) as conn:
                log_probe(conn, now=services.clock(), device_id=request.device_id,
                          account_id=request.account_id, order_id=request.order_id)
    return checkout_outcome(request.order_id, decision.decision_id, action)
