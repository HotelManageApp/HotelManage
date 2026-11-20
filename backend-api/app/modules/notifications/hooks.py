"""Stay closed -> one last "thank you" push, then the devices stop receiving notifications.

Registered on stay_access's on-stay-closed hook (runs inside the closing transaction). The device
tokens are copied into the outbox row first, because the sessions lose their tokens right after.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.stay_access.events import register_on_stay_closed
from app.modules.stay_access.models import Room, Stay, StaySession


async def thank_guest_and_forget_devices(db: AsyncSession, stay_id: uuid.UUID) -> None:
    rows = await db.execute(
        select(StaySession.fcm_token, StaySession.lang).where(
            StaySession.stay_id == stay_id, StaySession.fcm_token.is_not(None)
        )
    )
    recipients = [{"token": token, "lang": lang} for token, lang in rows.all() if token]
    room_number = await db.scalar(
        select(Room.number).join(Stay, Stay.room_id == Room.id).where(Stay.id == stay_id)
    )
    await emit_status_changed(
        db,
        entity_type=EntityType.STAY,
        entity_id=stay_id,
        stay_id=stay_id,
        status="CLOSED",
        room_number=room_number or "",
        actor="SYSTEM",
        push=bool(recipients),
        target_tokens=recipients or None,
    )
    await db.execute(
        update(StaySession).where(StaySession.stay_id == stay_id).values(fcm_token=None)
    )


def register() -> None:
    register_on_stay_closed(thank_guest_and_forget_devices)
