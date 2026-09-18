"""GET /metrics (§4 MetricsResponse): DB activity plus the offline synthetic backtest, kept separate."""
from typing import Annotated

from fastapi import APIRouter, Depends

from sentinel.api.deps import get_services, verify_internal_key
from sentinel.api.schemas import MetricsResponse
from sentinel.api.services.metrics import metrics
from sentinel.api.services.runtime import AppServices
from sentinel.db.models import read_connection

router = APIRouter(tags=["internal"], dependencies=[Depends(verify_internal_key)])


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(services: Annotated[AppServices, Depends(get_services)]) -> MetricsResponse:
    with read_connection(services.engine) as conn:
        return metrics(conn, services.evaluation)
