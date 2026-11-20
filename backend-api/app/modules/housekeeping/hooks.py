"""Housekeeping reactions to stay and room events (spec/SPEC-housekeeping.md, "TURNOVER").

- Stay closed  -> guest requests not started are cancelled (STAY_CLOSED), work in progress is
                  kept, and one TURNOVER job is opened for the room.
- Room marked vacant by reception -> an open TURNOVER for that room is cancelled.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.housekeeping import state
from app.modules.housekeeping.models import (
    OPEN_HK_STATUSES,
    HkStatus,
    HkType,
    HousekeepingRequest,
)
from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.shared import status_history
from app.modules.stay_access.events import register_on_room_marked_vacant, register_on_stay_closed
from app.modules.stay_access.models import Room, Stay

STAY_CLOSED_REASON = "STAY_CLOSED"
MARKED_VACANT_REASON = "MARKED_VACANT_BY_RECEPTION"
NOT_STARTED = (HkStatus.REQUESTED, HkStatus.ASSIGNED)


async def _cancel_not_started(
    db: AsyncSession, requests: list[HousekeepingRequest], room_number: str, reason: str
) -> None:
    for request in requests:
        await state.transition(
            db,
            request,
            HkStatus.CANCELLED,
            actor=state.Actor.SYSTEM,
            actor_label="SYSTEM",
            room_number=room_number,
            reason=reason,
            push=False,
        )


async def on_stay_closed(db: AsyncSession, stay_id: uuid.UUID) -> None:
    room = await db.scalar(
        select(Room).join(Stay, Stay.room_id == Room.id).where(Stay.id == stay_id)
    )
    if room is None:
        return
    open_guest_requests = list(
        await db.scalars(
            select(HousekeepingRequest)
            .where(
                HousekeepingRequest.stay_id == stay_id,
                HousekeepingRequest.status.in_(NOT_STARTED),
            )
            .with_for_update()
        )
    )
    await _cancel_not_started(db, open_guest_requests, room.number, STAY_CLOSED_REASON)

    already_open = await db.scalar(
        select(HousekeepingRequest.id).where(
            HousekeepingRequest.room_id == room.id,
            HousekeepingRequest.type == HkType.TURNOVER,
            HousekeepingRequest.status.in_(OPEN_HK_STATUSES),
        )
    )
    if already_open is not None:
        return
    turnover = HousekeepingRequest(
        id=uuid.uuid4(),
        room_id=room.id,
        stay_id=None,
        type=HkType.TURNOVER,
        status=HkStatus.REQUESTED,
        source="SYSTEM",
    )
    db.add(turnover)
    status_history.record(
        db,
        entity_type=EntityType.HOUSEKEEPING.value,
        entity_id=turnover.id,
        from_status=None,
        to_status=HkStatus.REQUESTED.value,
        actor="SYSTEM",
    )
    await db.flush()
    await emit_status_changed(
        db,
        entity_type=EntityType.HOUSEKEEPING,
        entity_id=turnover.id,
        stay_id=stay_id,
        status=HkStatus.REQUESTED.value,
        room_number=room.number,
        actor="SYSTEM",
        push=False,
    )


async def on_room_marked_vacant(db: AsyncSession, room_id: uuid.UUID) -> None:
    room_number = await db.scalar(select(Room.number).where(Room.id == room_id)) or ""
    turnovers = list(
        await db.scalars(
            select(HousekeepingRequest)
            .where(
                HousekeepingRequest.room_id == room_id,
                HousekeepingRequest.type == HkType.TURNOVER,
                HousekeepingRequest.status.in_(NOT_STARTED),
            )
            .with_for_update()
        )
    )
    await _cancel_not_started(db, turnovers, room_number, MARKED_VACANT_REASON)


def register() -> None:
    register_on_stay_closed(on_stay_closed)
    register_on_room_marked_vacant(on_room_marked_vacant)
