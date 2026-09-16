from contextlib import asynccontextmanager
from fastapi import FastAPI

from sentinel.api.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    # TODO: Replay graph state, load models at startup
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sentinel",
        description="Return Abuse Detection with Cost-Weighted Decisioning",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    return app


app = create_app()
