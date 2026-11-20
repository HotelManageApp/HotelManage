"""/api/v1/guest/me/fcm-token — the app registers or removes its push token."""

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from pydantic import Field
from sqlalchemy import update

from app.core.db import DbSession
from app.modules.stay_access.deps import CurrentStay
from app.modules.stay_access.models import StaySession
from app.modules.stay_access.schemas import StrictModel

router = APIRouter(prefix="/guest/me", tags=["notifications"])


class FcmTokenBody(StrictModel):
    fcm_token: str = Field(min_length=20, max_length=4096, pattern=r"^[A-Za-z0-9_:\-]+$")


async def _set_token(db: DbSession, ctx: CurrentStay, token: str | None) -> None:
    await db.execute(
        update(StaySession)
        .where(StaySession.id == ctx.session_id)
        .values(fcm_token=token, fcm_updated_at=datetime.now(UTC))
    )
    await db.commit()


@router.put("/fcm-token", status_code=status.HTTP_204_NO_CONTENT)
async def put_fcm_token(body: FcmTokenBody, ctx: CurrentStay, db: DbSession) -> Response:
    # A token belongs to one device: if this phone signed in to an earlier stay, detach it there.
    await db.execute(
        update(StaySession)
        .where(StaySession.fcm_token == body.fcm_token, StaySession.id != ctx.session_id)
        .values(fcm_token=None)
    )
    await _set_token(db, ctx, body.fcm_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/fcm-token", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fcm_token(ctx: CurrentStay, db: DbSession) -> Response:
    await _set_token(db, ctx, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
