import hmac
from datetime import datetime

from fastapi import Header, HTTPException, Request

from sentinel.api.services.runtime import AppServices
from sentinel.settings import DEMO_CLOCK, INTERNAL_API_KEY


def verify_internal_key(x_internal_key: str | None = Header(default=None)) -> None:
    """Verify the internal API key. Returns 401 on failure."""
    if x_internal_key is None or not hmac.compare_digest(x_internal_key, INTERNAL_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")


def get_reviewer_id(x_reviewer_id: str = Header(default="reviewer-placeholder-01")) -> str:
    return x_reviewer_id


def get_demo_clock() -> datetime:
    return DEMO_CLOCK


def get_services(request: Request) -> AppServices:
    """The services the lifespan built (and demo reset rebuilds)."""
    return request.app.state.services
