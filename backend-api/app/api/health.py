from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.db import check_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    db_ok = await check_db(request.app.state.engine, settings.db_health_timeout_seconds)
    body = {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "version": settings.app_version,
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)
