"""Background rules for food orders (spec/SPEC-room-service.md, "Đóng stay & nhắc đơn quá hạn")."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periodic import PeriodicJob
from app.modules.notifications.api import EntityType, notify_staff, staff_event_payload
from app.modules.room_service import state
from app.modules.room_service.models import FoodOrder, OrderStatus
from app.modules.stay_access.events import register_on_stay_closed
from app.modules.stay_access.models import Room

OVERDUE_AFTER = timedelta(minutes=10)
STAY_CLOSED_REASON = "STAY_CLOSED"


async def cancel_open_orders_on_stay_closed(db: AsyncSession, stay_id: uuid.UUID) -> None:
    """Not yet cooking -> cancelled. Cooking or on the way -> kept (and billed)."""
    rows = await db.execute(
        select(FoodOrder, Room.number)
        .join(Room, Room.id == FoodOrder.room_id)
        .where(
            FoodOrder.stay_id == stay_id,
            FoodOrder.status.in_((OrderStatus.PENDING, OrderStatus.CONFIRMED)),
        )
        .with_for_update(of=FoodOrder)
    )
    for order, room_number in rows.all():
        await state.transition(
            db,
            order,
            OrderStatus.CANCELLED,
            actor=state.Actor.SYSTEM,
            actor_label="SYSTEM",
            room_number=room_number,
            reason=STAY_CLOSED_REASON,
            push=False,  # the guest gets the check-out thank-you instead
        )


async def remind_overdue_orders(db: AsyncSession, now: datetime | None = None) -> int:
    """One `order_overdue` event (reception + kitchen) per order left PENDING too long."""
    current = now or datetime.now(UTC)
    rows = await db.execute(
        select(FoodOrder, Room.number)
        .join(Room, Room.id == FoodOrder.room_id)
        .where(
            FoodOrder.status == OrderStatus.PENDING,
            FoodOrder.created_at <= current - OVERDUE_AFTER,
            FoodOrder.overdue_notified_at.is_(None),
        )
        .with_for_update(of=FoodOrder, skip_locked=True)
    )
    reminded = 0
    for order, room_number in rows.all():
        order.overdue_notified_at = current
        await notify_staff(
            db,
            staff_event_payload(
                event="order_overdue",
                entity_type=EntityType.FOOD_ORDER,
                entity_id=order.id,
                status=order.status.value,
                room_number=room_number,
                actor="SYSTEM",
                occurred_at=current,
            ),
        )
        reminded += 1
    await db.commit()
    return reminded


OVERDUE_JOB = PeriodicJob("food_order_overdue", 60.0, remind_overdue_orders)


def register() -> None:
    register_on_stay_closed(cancel_open_orders_on_stay_closed)
