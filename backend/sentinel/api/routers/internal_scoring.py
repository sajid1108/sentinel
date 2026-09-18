"""POST /api/v1/internal/score-order (§4): one order in, one recorded decision out. Idempotent per order id."""
from typing import Annotated

from fastapi import APIRouter, Depends

from sentinel.api.deps import get_services, verify_internal_key
from sentinel.api.schemas import ScoreOrderRequest, ScoreOrderResponse
from sentinel.api.services.runtime import AppServices

router = APIRouter(tags=["internal"], dependencies=[Depends(verify_internal_key)])


@router.post("/score-order", response_model=ScoreOrderResponse)
def score_order(request: ScoreOrderRequest,
                services: Annotated[AppServices, Depends(get_services)]) -> ScoreOrderResponse:
    with services.lock:
        return services.scoring.score(request, "LIVE")
