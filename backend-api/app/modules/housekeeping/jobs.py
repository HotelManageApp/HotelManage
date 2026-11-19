"""Housekeeping reminders (spec/SPEC-housekeeping.md, "Nhắc quá hạn")."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periodic import PeriodicJob
from app.modules.housekeeping.models import HkStatus, HousekeepingRequest
from app.modules.notifications.api import EntityType, notify_staff, staff_event_payload
from app.modules.stay_access.models import Room

OVERDUE_AFTER = timedelta(minutes=15)


async def remind_overdue_requests(db: AsyncSession, now: datetime | None = None) -> int:
    """One `housekeeping_overdue` event per request still REQUESTED 15 min after it was due."""
    current = now or datetime.now(UTC)
    due = func.greatest(
        HousekeepingRequest.created_at,
        func.coalesce(HousekeepingRequest.preferred_time, HousekeepingRequest.created_at),
    )
    rows = await db.execute(
        select(HousekeepingRequest, Room.number)
        .join(Room, Room.id == HousekeepingRequest.room_id)
        .where(
            HousekeepingRequest.status == HkStatus.REQUESTED,
            HousekeepingRequest.overdue_notified_at.is_(None),
            due <= current - OVERDUE_AFTER,
        )
        .with_for_update(of=HousekeepingRequest, skip_locked=True)
    )
    reminded = 0
    for request, room_number in rows.all():
        request.overdue_notified_at = current
        await notify_staff(
            db,
            staff_event_payload(
                event="housekeeping_overdue",
                entity_type=EntityType.HOUSEKEEPING,
                entity_id=request.id,
                status=request.status.value,
                room_number=room_number,
                actor="SYSTEM",
                occurred_at=current,
            ),
        )
        reminded += 1
    await db.commit()
    return reminded


OVERDUE_JOB = PeriodicJob("housekeeping_overdue", 60.0, remind_overdue_requests)
