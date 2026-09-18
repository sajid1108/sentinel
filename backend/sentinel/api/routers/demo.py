"""GET /demo/presets and POST /demo/reset (DEMO_MODE only; otherwise 404 - Phase 7 brief §B, #34)."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from sentinel.api.deps import get_services, verify_internal_key
from sentinel.api.schemas import ScoreOrderRequest
from sentinel.api.services.errors import NotFound
from sentinel.api.services.runtime import AppServices, presets_path

router = APIRouter(prefix="/demo", tags=["demo"], dependencies=[Depends(verify_internal_key)])
Services = Annotated[AppServices, Depends(get_services)]


class DemoResetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    decisions: int


def _require_demo_mode(services: AppServices) -> None:
    if not services.demo_mode:
        raise NotFound("demo endpoints are disabled")


@router.get("/presets", response_model=list[ScoreOrderRequest])
def presets(services: Services) -> list[ScoreOrderRequest]:
    """The three §11 demo requests, as seed-db wrote them beside the database."""
    _require_demo_mode(services)
    path = presets_path(services.db_path)
    return [ScoreOrderRequest.model_validate(p) for p in json.loads(path.read_text(encoding="utf-8"))]


@router.post("/reset", response_model=DemoResetResponse)
def reset(services: Services) -> DemoResetResponse:
    _require_demo_mode(services)
    return DemoResetResponse(status="reset", decisions=services.reset())
