"""App factory (§1 api/main.py; Phase 7 brief §A).

The lifespan builds one ScoringService and one ReviewService (AppServices) and refuses to start without the
seeded database. Routers: internal under /api/v1/internal (X-Internal-Key on every route), public under
/api/v1/public, /health unauthenticated. No CORS middleware: the Vite proxy makes the UI same-origin. There is
no /predict route and no route that returns a model score without a decision.

HTTP errors (§4): 401 bad internal key, 404 not found (neutral body, never echoes the id), 409 conflict,
422 validation. Public-route errors carry a fixed generic body and never echo a request field.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sentinel.api.routers import (demo, health, internal_audit, internal_metrics, internal_orders,
                                  internal_scoring, public_checkout)
from sentinel.api.services.errors import Conflict, NotFound, RequestRejected, ServiceError
from sentinel.api.services.runtime import AppServices
from sentinel.settings import ARTIFACTS_DIR, DATA_DIR, DB_PATH, DEMO_MODE

INTERNAL_PREFIX = "/api/v1/internal"
PUBLIC_PREFIX = "/api/v1/public"
NOT_FOUND = "Not found."
PUBLIC_ERRORS = {404: "Not found.", 409: "This request conflicts with an earlier request.",
                 422: "The request could not be processed."}


def _status(exc: ServiceError) -> int:
    if isinstance(exc, NotFound):
        return 404
    if isinstance(exc, Conflict):
        return 409
    if isinstance(exc, RequestRejected):
        return 422
    raise exc


def _is_public(request: Request) -> bool:
    return request.url.path.startswith(PUBLIC_PREFIX)


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    status = _status(exc)
    if _is_public(request):
        return JSONResponse(status_code=status, content={"detail": PUBLIC_ERRORS[status]})
    return JSONResponse(status_code=status, content={"detail": NOT_FOUND if status == 404 else str(exc)})


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if _is_public(request):
        return JSONResponse(status_code=422, content={"detail": PUBLIC_ERRORS[422]})
    # Internal: where and why, never the submitted value (FastAPI's default body echoes `input`).
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": [str(part) for part in e.get("loc", ())], "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()]})


def create_app(db_path: Path = DB_PATH, *, demo_mode: bool = DEMO_MODE, artifacts_dir: Path = ARTIFACTS_DIR,
               data_dir: Path = DATA_DIR, clock: Callable[[], datetime] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = AppServices.start(db_path, demo_mode=demo_mode, artifacts_dir=artifacts_dir,
                                               data_dir=data_dir, clock=clock)
        try:
            yield
        finally:
            app.state.services.close()

    app = FastAPI(title="Sentinel", description="Return Abuse Detection with Cost-Weighted Decisioning",
                  version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    for router in (internal_scoring.router, internal_orders.router, internal_audit.router,
                   internal_metrics.router, demo.router):
        app.include_router(router, prefix=INTERNAL_PREFIX)
    app.include_router(public_checkout.router, prefix=PUBLIC_PREFIX)
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    return app


app = create_app()
