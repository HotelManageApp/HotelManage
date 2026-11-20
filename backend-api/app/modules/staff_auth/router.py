"""/api/v1/staff — login, refresh, logout, me, change password."""

from fastapi import APIRouter, Request, Response, status

from app.core.db import DbSession
from app.core.errors import Forbidden
from app.modules.staff_auth import service
from app.modules.staff_auth.deps import CurrentStaff
from app.modules.staff_auth.models import Staff
from app.modules.staff_auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    StaffOut,
    TokenResponse,
)

router = APIRouter(prefix="/staff", tags=["staff-auth"])

REFRESH_COOKIE = "staff_refresh"
REFRESH_COOKIE_PATH = "/api/v1/staff/auth"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_origin(request: Request) -> None:
    """CSRF guard for cookie-authenticated endpoints, on top of SameSite=Strict."""
    origin = request.headers.get("origin")
    if origin is None or origin not in request.app.state.settings.admin_web_origins:
        raise Forbidden("Nguồn yêu cầu không được phép")


def _session_response(response: Response, session: service.IssuedSession) -> TokenResponse:
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        max_age=session.refresh_max_age,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=session.access_token,
        expires_in=session.access_expires_in,
        staff=StaffOut.model_validate(session.staff),
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, secure=True, samesite="strict"
    )


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession
) -> TokenResponse:
    session = await service.login(
        db,
        request.app.state.settings,
        email=body.email,
        password=body.password,
        client_ip=_client_ip(request),
    )
    return _session_response(response, session)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, db: DbSession) -> TokenResponse:
    _check_origin(request)
    session = await service.refresh(
        db, request.app.state.settings, raw_token=request.cookies.get(REFRESH_COOKIE)
    )
    return _session_response(response, session)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, db: DbSession) -> Response:
    _check_origin(request)
    await service.logout(db, raw_token=request.cookies.get(REFRESH_COOKIE))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookie(response)
    return response


@router.get("/me", response_model=StaffOut)
async def me(staff: CurrentStaff) -> Staff:
    return staff


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
) -> Response:
    await service.change_password(
        db,
        staff,
        current_password=body.current_password,
        new_password=body.new_password,
        raw_refresh_token=request.cookies.get(REFRESH_COOKIE),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
