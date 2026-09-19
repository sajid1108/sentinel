"""GET /demo/presets, POST /demo/presets/{order_id}/score, GET /demo/order-builder and POST /demo/reset
(DEMO_MODE only; otherwise 404 - Phase 7 brief §B, #34). A preset scored through its own route is recorded
with source DEMO (Phase 10 Part 1); POST /score-order keeps recording LIVE. The order builder serves the
"Try an order" form's options (Phase 10 §A)."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from sentinel.api.deps import get_services, verify_internal_key
from sentinel.api.schemas import OrderBuilderResponse, ScoreOrderRequest, ScoreOrderResponse
from sentinel.api.services import order_builder
from sentinel.api.services.errors import NotFound
from sentinel.api.services.runtime import AppServices, presets_path
from sentinel.db.models import read_connection

router = APIRouter(prefix="/demo", tags=["demo"], dependencies=[Depends(verify_internal_key)])
Services = Annotated[AppServices, Depends(get_services)]


class DemoResetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    decisions: int


def _require_demo_mode(services: AppServices) -> None:
    if not services.demo_mode:
        raise NotFound("demo endpoints are disabled")


def load_presets(services: AppServices) -> list[ScoreOrderRequest]:
    """The §11 demo requests, as seed-db wrote them beside the database."""
    path = presets_path(services.db_path)
    return [ScoreOrderRequest.model_validate(p) for p in json.loads(path.read_text(encoding="utf-8"))]


@router.get("/presets", response_model=list[ScoreOrderRequest])
def presets(services: Services) -> list[ScoreOrderRequest]:
    _require_demo_mode(services)
    return load_presets(services)


@router.post("/presets/{order_id}/score", response_model=ScoreOrderResponse)
def score_preset(order_id: str, services: Services) -> ScoreOrderResponse:
    """Score the preset with this order id as a DEMO decision. A preset already scored replays its record."""
    _require_demo_mode(services)
    preset = next((p for p in load_presets(services) if p.order_id == order_id), None)
    if preset is None:
        raise NotFound("unknown preset")
    with services.lock:
        return services.scoring.score(preset, "DEMO")


@router.get("/order-builder", response_model=OrderBuilderResponse)
def builder(services: Services) -> OrderBuilderResponse:
    """Accounts, identifier options, categories and placed_at for the "Try an order" form, all from data."""
    _require_demo_mode(services)
    presets = load_presets(services)
    with services.lock, read_connection(services.engine) as conn:        # the FeatureBuilder is not thread-safe
        return order_builder.order_builder(conn, services.scoring, presets)


@router.post("/reset", response_model=DemoResetResponse)
def reset(services: Services) -> DemoResetResponse:
    _require_demo_mode(services)
    return DemoResetResponse(status="reset", decisions=services.reset())
