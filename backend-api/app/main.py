"""Application factory.

Run with `uv run uvicorn app.main:app --reload --port 8000`; `app` is built lazily on first
access so importing this module (e.g. in tests) does not require environment variables.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI

from app.api.health import router as health_router
from app.core.config import Settings, load_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_context import RequestContextMiddleware
from app.modules.staff_auth.router import router as staff_auth_router
from app.modules.stay_access.router_guest import router as guest_router
from app.modules.stay_access.router_staff import router as reception_router

API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    is_prod = settings.app_env == "prod"
    app = FastAPI(
        title="HotelManage backend-api",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/openapi.json",
    )
    app.state.settings = settings

    register_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    api_v1 = APIRouter(prefix=API_V1_PREFIX)
    # Module routers are included here as modules are built (stay_access, ...).
    api_v1.include_router(staff_auth_router)
    api_v1.include_router(reception_router)
    api_v1.include_router(guest_router)
    app.include_router(api_v1)
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
