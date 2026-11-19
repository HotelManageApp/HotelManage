"""Placing food orders (spec/SPEC-room-service.md, "Tạo đơn")."""

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ValidationFailed
from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.room_service import hours
from app.modules.room_service.models import (
    FoodOrder,
    MenuCategory,
    MenuItem,
    OrderItem,
    OrderStatus,
)
from app.modules.shared import status_history
from app.modules.stay_access.deps import StayContext

MAX_PENDING_ORDERS = 5
MAX_QUANTITY = 20


@dataclass(frozen=True)
class Line:
    item_id: uuid.UUID
    quantity: int
    note: str | None


def merge_lines(lines: list[Line]) -> list[Line]:
    """Same dish twice -> one line with the summed quantity (first non-empty note kept)."""
    merged: OrderedDict[uuid.UUID, Line] = OrderedDict()
    for line in lines:
        previous = merged.get(line.item_id)
        if previous is None:
            merged[line.item_id] = line
        else:
            merged[line.item_id] = Line(
                line.item_id, previous.quantity + line.quantity, previous.note or line.note
            )
    for line in merged.values():
        if line.quantity > MAX_QUANTITY:
            raise ValidationFailed(
                details=[{"field": "items", "issue": f"at most {MAX_QUANTITY} of one dish"}]
            )
    return list(merged.values())


async def priced_lines(db: AsyncSession, lines: list[Line]) -> list[tuple[Line, MenuItem]]:
    """Look every dish up in the menu. Unknown, archived, sold-out or hidden -> 409."""
    ids = [line.item_id for line in lines]
    rows = await db.execute(
        select(MenuItem)
        .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
        .where(
            MenuItem.id.in_(ids),
            MenuItem.is_archived.is_(False),
            MenuItem.available.is_(True),
            MenuCategory.is_active.is_(True),
        )
    )
    found = {item.id: item for item in rows.scalars()}
    missing = [line.item_id for line in lines if line.item_id not in found]
    if missing:
        raise Conflict(
            "Một số món hiện không phục vụ",
            code="ITEM_UNAVAILABLE",
            details=[{"item_id": str(item_id)} for item_id in missing],
        )
    return [(line, found[line.item_id]) for line in lines]


async def find_by_idempotency_key(
    db: AsyncSession, stay_id: uuid.UUID, key: str
) -> FoodOrder | None:
    return await db.scalar(
        select(FoodOrder).where(FoodOrder.stay_id == stay_id, FoodOrder.idempotency_key == key)
    )


async def ensure_kitchen_open(db: AsyncSession, tz: str) -> None:
    settings = await hours.load(db)
    if not hours.accepting_orders(settings, datetime.now(UTC), tz):
        raise Conflict(
            f"Bếp đang tạm ngừng nhận đơn (giờ phục vụ "
            f"{hours.label(settings.room_service_open, settings.room_service_close)})",
            code="KITCHEN_CLOSED",
        )


async def place_order(
    db: AsyncSession,
    ctx: StayContext,
    *,
    lines: list[Line],
    order_note: str | None,
    source: str,
    idempotency_key: str | None,
    tz: str,
) -> tuple[FoodOrder, bool]:
    """Create a PENDING order. Returns (order, created); a replayed key returns the original."""
    if idempotency_key:
        existing = await find_by_idempotency_key(db, ctx.stay_id, idempotency_key)
        if existing is not None:
            return existing, False

    await ensure_kitchen_open(db, tz)
    priced = await priced_lines(db, merge_lines(lines))

    pending = await db.scalar(
        select(func.count())
        .select_from(FoodOrder)
        .where(FoodOrder.stay_id == ctx.stay_id, FoodOrder.status == OrderStatus.PENDING)
    )
    if (pending or 0) >= MAX_PENDING_ORDERS:
        raise Conflict(
            "Quý khách đang có nhiều đơn chờ xác nhận, vui lòng đợi Bếp xử lý",
            code="TOO_MANY_PENDING_ORDERS",
        )

    order = FoodOrder(
        id=uuid.uuid4(),
        stay_id=ctx.stay_id,
        room_id=ctx.room_id,
        status=OrderStatus.PENDING,
        order_note=order_note,
        source=source,
        idempotency_key=idempotency_key,
        total_vnd=sum(item.price_vnd * line.quantity for line, item in priced),
        items=[
            OrderItem(
                menu_item_id=item.id,
                position=position,
                name_vi=item.name_vi,
                name_en=item.name_en,
                unit_price_vnd=item.price_vnd,
                quantity=line.quantity,
                line_total_vnd=item.price_vnd * line.quantity,
                note=line.note,
            )
            for position, (line, item) in enumerate(priced)
        ],
    )
    db.add(order)
    status_history.record(
        db,
        entity_type=EntityType.FOOD_ORDER.value,
        entity_id=order.id,
        from_status=None,
        to_status=OrderStatus.PENDING.value,
        actor="GUEST",
    )
    try:
        # Flush first: a duplicate Idempotency-Key fails here (unique index), not later inside
        # the NOTIFY statement's autoflush where it could escape this handler.
        await db.flush()
        await emit_status_changed(
            db,
            entity_type=EntityType.FOOD_ORDER,
            entity_id=order.id,
            stay_id=ctx.stay_id,
            status=OrderStatus.PENDING.value,
            room_number=ctx.room_number,
            actor="GUEST",
            push=False,
        )
        await db.commit()
    except IntegrityError:
        # The same Idempotency-Key raced in from a retry: hand back the order that won.
        await db.rollback()
        if idempotency_key:
            existing = await find_by_idempotency_key(db, ctx.stay_id, idempotency_key)
            if existing is not None:
                return existing, False
        raise
    await db.refresh(order)
    return order, True
