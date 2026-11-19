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
from app.core.periodic import Scheduler
from app.core.request_context import RequestContextMiddleware
from app.modules.housekeeping import hooks as housekeeping_hooks
from app.modules.housekeeping import jobs as housekeeping_jobs
from app.modules.housekeeping.router_guest import router as guest_housekeeping_router
from app.modules.housekeeping.router_staff import router as staff_housekeeping_router
from app.modules.notifications import hooks as notification_hooks
from app.modules.notifications.fcm import FcmSender, ServiceAccountTokens
from app.modules.notifications.outbox_worker import OutboxWorker
from app.modules.notifications.router_dev import router as dev_router
from app.modules.notifications.router_guest import router as fcm_token_router
from app.modules.notifications.senders import LogSender, PushSender
from app.modules.notifications.sse import StaffEventHub
from app.modules.notifications.sse import router as staff_events_router
from app.modules.room_service import jobs as room_service_jobs
from app.modules.room_service.router_guest import router as guest_orders_router
from app.modules.room_service.router_menu import router as menu_router
from app.modules.room_service.router_staff import router as staff_orders_router
from app.modules.staff_auth.router import router as staff_auth_router
from app.modules.stay_access.router_guest import router as guest_router
from app.modules.stay_access.router_staff import router as reception_router

API_V1_PREFIX = "/api/v1"


def build_push_sender(settings: Settings) -> PushSender:
    """FCM_SENDER=log writes pushes to the log (dev default); fcm sends through Firebase."""
    if settings.fcm_sender == "fcm" and settings.fcm_project_id and settings.fcm_credentials_file:
        return FcmSender(
            project_id=settings.fcm_project_id,
            access_token=ServiceAccountTokens(settings.fcm_credentials_file),
        )
    return LogSender()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    notification_hooks.register()
    room_service_jobs.register()
    housekeeping_hooks.register()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        worker = OutboxWorker(app.state.sessionmaker, build_push_sender(settings))
        app.state.outbox_worker = worker
        scheduler = Scheduler(app.state.sessionmaker)
        scheduler.add(room_service_jobs.OVERDUE_JOB)
        scheduler.add(housekeeping_jobs.OVERDUE_JOB)
        app.state.scheduler = scheduler
        hub = StaffEventHub(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"))
        app.state.staff_event_hub = hub
        if settings.notifications_worker_enabled:
            worker.start()
            scheduler.start()
        try:
            yield
        finally:
            await worker.stop()
            await scheduler.stop()
            await hub.close()
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
    api_v1.include_router(fcm_token_router)
    api_v1.include_router(staff_events_router)
    api_v1.include_router(menu_router)
    api_v1.include_router(guest_orders_router)
    api_v1.include_router(staff_orders_router)
    api_v1.include_router(guest_housekeeping_router)
    api_v1.include_router(staff_housekeeping_router)
    if settings.app_env == "dev":
        api_v1.include_router(dev_router)
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
