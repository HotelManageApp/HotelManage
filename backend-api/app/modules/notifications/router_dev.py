"""POST /api/v1/dev/notify-test — only mounted when APP_ENV=dev (spec/SPEC-notifications.md).

Lets the team check push and SSE end to end before the business modules exist.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict

from app.core.db import DbSession
from app.core.errors import NotFound
from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.stay_access import repository

router = APIRouter(prefix="/dev", tags=["dev"])


class NotifyTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stay_id: uuid.UUID


@router.post("/notify-test", status_code=status.HTTP_202_ACCEPTED)
async def notify_test(
    body: NotifyTest,
    staff: Annotated[Staff, Depends(require_roles(StaffRole.RECEPTION))],
    db: DbSession,
) -> Response:
    stay = await repository.get_stay(db, body.stay_id)
    if stay is None:
        raise NotFound("Không tìm thấy kỳ lưu trú")
    room = await repository.get_room(db, stay.room_id)
    await emit_status_changed(
        db,
        entity_type=EntityType.STAY,
        entity_id=stay.id,
        stay_id=stay.id,
        status="TEST",
        room_number=room.number if room else "",
        actor=f"STAFF:{staff.id}",
    )
    await db.commit()
    return Response(status_code=status.HTTP_202_ACCEPTED)
