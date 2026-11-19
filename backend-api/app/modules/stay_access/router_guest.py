"""/api/v1/guest — room-code login and the guest's own stay."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from app.core.db import DbSession
from app.core.errors import Unauthorized
from app.modules.stay_access import guest_service, repository
from app.modules.stay_access.deps import CurrentStay
from app.modules.stay_access.models import StayStatus
from app.modules.stay_access.schemas import StrictModel

router = APIRouter(prefix="/guest", tags=["guest"])

Lang = Literal["vi", "en"]


class RoomCodeLogin(StrictModel):
    code: str = Field(min_length=1, max_length=32)
    device_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    lang: Lang = "vi"


class GuestStay(BaseModel):
    room_number: str
    guest_name: str | None
    expected_checkout_at: datetime
    status: StayStatus
    do_not_disturb: bool  # set by the guest, cleared when they ask for cleaning


class GuestTokenResponse(BaseModel):
    access_token: str
    expires_at: datetime
    stay: GuestStay


class GuestMe(GuestStay):
    lang: str


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _token_response(session: guest_service.GuestSession) -> GuestTokenResponse:
    return GuestTokenResponse(
        access_token=session.token,
        expires_at=session.expires_at,
        stay=GuestStay(
            room_number=session.room_number,
            guest_name=session.stay.guest_name,
            expected_checkout_at=session.stay.expected_checkout_at,
            status=session.stay.status,
            do_not_disturb=session.stay.do_not_disturb,
        ),
    )


@router.post("/auth/room-code", response_model=GuestTokenResponse)
async def login_with_room_code(
    body: RoomCodeLogin, request: Request, response: Response, db: DbSession
) -> GuestTokenResponse:
    session = await guest_service.login_with_code(
        db,
        request.app.state.settings,
        raw_code=body.code,
        device_id=body.device_id,
        lang=body.lang,
        client_ip=_client_ip(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return _token_response(session)


@router.post("/auth/renew", response_model=GuestTokenResponse)
async def renew(ctx: CurrentStay, request: Request, db: DbSession) -> GuestTokenResponse:
    session = await guest_service.renew(
        db, request.app.state.settings, session_id=ctx.session_id, stay_id=ctx.stay_id
    )
    return _token_response(session)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(ctx: CurrentStay, db: DbSession) -> Response:
    await guest_service.logout(db, ctx.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=GuestMe)
async def me(ctx: CurrentStay, db: DbSession) -> GuestMe:
    stay = await repository.get_stay(db, ctx.stay_id)
    if stay is None:
        raise Unauthorized()
    return GuestMe(
        room_number=ctx.room_number,
        guest_name=stay.guest_name,
        expected_checkout_at=stay.expected_checkout_at,
        status=stay.status,
        do_not_disturb=stay.do_not_disturb,
        lang=ctx.lang,
    )
