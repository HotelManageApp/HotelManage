"""What other modules may ask room-service (express-checkout billing, chatbot, ...)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.room_service.models import OPEN_ORDER_STATUSES, FoodOrder, OrderStatus


@dataclass(frozen=True)
class BilledOrder:
    order_id: uuid.UUID
    total_vnd: int
    item_count: int
    created_at: datetime


@dataclass(frozen=True)
class FoodBill:
    """Completed orders are billed; open ones are only counted (they block the final bill)."""

    orders: list[BilledOrder]
    total_vnd: int
    open_orders: int


async def count_open_orders(db: AsyncSession, stay_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(FoodOrder)
            .where(FoodOrder.stay_id == stay_id, FoodOrder.status.in_(OPEN_ORDER_STATUSES))
        )
        or 0
    )


async def get_stay_food_total(db: AsyncSession, stay_id: uuid.UUID) -> FoodBill:
    completed = list(
        await db.scalars(
            select(FoodOrder)
            .where(FoodOrder.stay_id == stay_id, FoodOrder.status == OrderStatus.COMPLETED)
            .order_by(FoodOrder.created_at)
        )
    )
    orders = [
        BilledOrder(
            order_id=o.id,
            total_vnd=o.total_vnd,
            item_count=sum(line.quantity for line in o.items),
            created_at=o.created_at,
        )
        for o in completed
    ]
    return FoodBill(
        orders=orders,
        total_vnd=sum(o.total_vnd for o in orders),
        open_orders=await count_open_orders(db, stay_id),
    )
