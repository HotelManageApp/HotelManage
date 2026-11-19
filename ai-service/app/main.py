"""Application factory.

Run with `uv run uvicorn app.main:app --reload --port 8001`; `app` is built lazily on first
access so importing this module (e.g. in tests) does not require environment variables.
"""

from typing import Any

from fastapi import APIRouter, FastAPI

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.concierge.orchestrator import Orchestrator
from app.core.backend_client import BackendClient
from app.core.config import Settings, load_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_context import RequestContextMiddleware
from app.llm.base import LLMClient
from app.llm.registry import create_llm_client

API_V1_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    backend: BackendClient | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    is_prod = settings.app_env == "prod"
    app = FastAPI(
        title="HotelManage ai-service",
        version=settings.app_version,
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/openapi.json",
    )
    app.state.settings = settings
    app.state.llm = llm or create_llm_client(settings)
    app.state.backend = backend or BackendClient(
        str(settings.backend_internal_url), timeout_seconds=settings.backend_timeout_seconds
    )
    app.state.orchestrator = Orchestrator(
        app.state.llm, app.state.backend, timezone_name=settings.hotel_timezone
    )

    register_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    api_v1 = APIRouter(prefix=API_V1_PREFIX)
    api_v1.include_router(chat_router)
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
