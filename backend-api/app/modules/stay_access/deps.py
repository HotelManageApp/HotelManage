"""Guest authentication: the only source of a guest's stay and room (CONSTRAINTS C4.1).

Every guest endpoint depends on `CurrentStay` (read) or `ActiveStay` (write). Request bodies use
`extra="forbid"` models, so a client can never pass its own room_id/stay_id.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.db import DbSession
from app.core.errors import Conflict, Forbidden, Unauthorized
from app.modules.stay_access.models import Room, Stay, StaySession, StayStatus
from app.modules.stay_access.tokens import InvalidStayToken, decode_stay_token

_bearer = HTTPBearer(auto_error=False)
_LAST_SEEN_RESOLUTION = timedelta(minutes=1)

SESSION_ENDED_MESSAGE = (
    "Phiên lưu trú đã kết thúc hoặc mã đã được cấp lại. Vui lòng liên hệ Lễ tân."
)


@dataclass(frozen=True)
class StayContext:
    stay_id: uuid.UUID
    room_id: uuid.UUID
    room_number: str
    session_id: uuid.UUID
    status: StayStatus
    lang: str


def _ended(reason: str) -> Unauthorized:
    # `reason` lets the app show the right screen (thank-you vs. "code re-issued"); nothing else.
    return Unauthorized(SESSION_ENDED_MESSAGE, details=[{"reason": reason}])


async def current_stay(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> StayContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthorized()
    secret = request.app.state.settings.stay_jwt_secret.get_secret_value()
    try:
        claims = decode_stay_token(credentials.credentials, secret=secret)
    except InvalidStayToken:
        raise Unauthorized() from None

    row = (
        await db.execute(
            select(StaySession, Stay, Room.number)
            .join(Stay, Stay.id == StaySession.stay_id)
            .join(Room, Room.id == Stay.room_id)
            .where(StaySession.id == claims.session_id)
        )
    ).one_or_none()
    if row is None:
        raise Unauthorized()
    session, stay, room_number = row
    if session.stay_id != claims.stay_id or stay.room_id != claims.room_id:
        raise Unauthorized()
    if stay.status == StayStatus.CLOSED:
        raise _ended("STAY_CLOSED")
    if session.revoked_at is not None:
        reason = session.revoke_reason.value if session.revoke_reason else "REVOKED"
        raise _ended("CODE_REISSUED" if reason == "REISSUE" else reason)

    now = datetime.now(UTC)
    if now - session.last_seen_at >= _LAST_SEEN_RESOLUTION:
        session.last_seen_at = now
        await db.commit()

    return StayContext(
        stay_id=stay.id,
        room_id=stay.room_id,
        room_number=room_number,
        session_id=session.id,
        status=stay.status,
        lang=session.lang,
    )


CurrentStay = Annotated[StayContext, Depends(current_stay)]


async def current_active_stay(ctx: CurrentStay) -> StayContext:
    """For endpoints that create something: refused while checkout is pending."""
    if ctx.status is not StayStatus.ACTIVE:
        raise Conflict("Yêu cầu trả phòng đang được xử lý", code="STAY_CHECKOUT_PENDING")
    return ctx


ActiveStay = Annotated[StayContext, Depends(current_active_stay)]


def ensure_same_stay(ctx: StayContext, owner_stay_id: uuid.UUID) -> None:
    """403 when a guest reaches a resource of another stay (CONSTRAINTS C5.1)."""
    if owner_stay_id != ctx.stay_id:
        raise Forbidden()
