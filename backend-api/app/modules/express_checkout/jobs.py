"""Reminder for checkout requests nobody picked up (SPEC-express-checkout)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periodic import PeriodicJob
from app.modules.express_checkout.models import CheckoutRequest, CheckoutStatus
from app.modules.notifications.api import EntityType, notify_staff, staff_event_payload
from app.modules.stay_access.models import Room, Stay

OVERDUE_AFTER = timedelta(minutes=10)


async def remind_overdue_requests(db: AsyncSession, now: datetime | None = None) -> int:
    """One `checkout_overdue` event (reception) per request left CHECKOUT_REQUESTED too long."""
    current = now or datetime.now(UTC)
    rows = await db.execute(
        select(CheckoutRequest, Room.number)
        .join(Stay, Stay.id == CheckoutRequest.stay_id)
        .join(Room, Room.id == Stay.room_id)
        .where(
            CheckoutRequest.status == CheckoutStatus.CHECKOUT_REQUESTED,
            CheckoutRequest.created_at <= current - OVERDUE_AFTER,
            CheckoutRequest.overdue_notified_at.is_(None),
        )
        .with_for_update(of=CheckoutRequest, skip_locked=True)
    )
    reminded = 0
    for request, room_number in rows.all():
        request.overdue_notified_at = current
        await notify_staff(
            db,
            staff_event_payload(
                event="checkout_overdue",
                entity_type=EntityType.CHECKOUT,
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


OVERDUE_JOB = PeriodicJob("checkout_overdue", 60.0, remind_overdue_requests)
