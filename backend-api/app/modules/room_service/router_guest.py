"""Guest food orders: place, list, view, cancel (spec/SPEC-room-service.md)."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response, status
from sqlalchemy import select

from app.core.db import DbSession
from app.core.errors import InvalidTransition, NotFound, ValidationFailed
from app.modules.notifications.api import EntityType
from app.modules.room_service import service, state
from app.modules.room_service.models import FoodOrder, OrderStatus
from app.modules.room_service.schemas import CreateOrder, OrderOut, order_out
from app.modules.shared.status_history import history_of
from app.modules.stay_access.deps import ActiveStay, CurrentStay, StayContext, ensure_same_stay

router = APIRouter(prefix="/guest/orders", tags=["guest-orders"])

IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


async def _own_order(
    db: DbSession, ctx: StayContext, order_id: uuid.UUID, *, for_update: bool = False
) -> FoodOrder:
    stmt = select(FoodOrder).where(FoodOrder.id == order_id)
    if for_update:
        stmt = stmt.with_for_update()
    order = await db.scalar(stmt)
    if order is None:
        raise NotFound("Không tìm thấy đơn")
    ensure_same_stay(ctx, order.stay_id)
    return order


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def place_order(
    body: CreateOrder,
    ctx: ActiveStay,
    request: Request,
    response: Response,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OrderOut:
    if idempotency_key is not None and not re.fullmatch(IDEMPOTENCY_PATTERN, idempotency_key):
        raise ValidationFailed(
            details=[{"field": "Idempotency-Key", "issue": "8-64 [A-Za-z0-9_-]"}]
        )
    order, created = await service.place_order(
        db,
        ctx,
        lines=[service.Line(line.item_id, line.quantity, line.note) for line in body.items],
        order_note=body.order_note,
        source=body.source,
        idempotency_key=idempotency_key,
        tz=request.app.state.settings.hotel_timezone,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return order_out(order, ctx.lang)


@router.get("", response_model=list[OrderOut])
async def my_orders(
    ctx: CurrentStay,
    db: DbSession,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> list[OrderOut]:
    stmt = select(FoodOrder).where(FoodOrder.stay_id == ctx.stay_id)
    if status_filter is not None:
        stmt = stmt.where(FoodOrder.status == status_filter)
    orders = await db.scalars(stmt.order_by(FoodOrder.created_at.desc()).limit(50))
    return [order_out(order, ctx.lang) for order in orders]


@router.get("/{order_id}", response_model=OrderOut)
async def my_order(order_id: uuid.UUID, ctx: CurrentStay, db: DbSession) -> OrderOut:
    order = await _own_order(db, ctx, order_id)
    history = await history_of(db, EntityType.FOOD_ORDER.value, order.id)
    return order_out(order, ctx.lang, history)


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel(order_id: uuid.UUID, ctx: CurrentStay, db: DbSession) -> OrderOut:
    order = await _own_order(db, ctx, order_id, for_update=True)
    if order.status is not OrderStatus.PENDING:
        # For the guest this is "too late", not "not allowed": the kitchen has the order
        # (docs/domain-rules.md §3, SPEC-room-service SC 4).
        raise InvalidTransition("Bếp đã nhận đơn nên không hủy được nữa")
    await state.transition(
        db,
        order,
        OrderStatus.CANCELLED,
        actor=state.Actor.GUEST,
        actor_label="GUEST",
        room_number=ctx.room_number,
        reason="Khách hủy",
    )
    await db.commit()
    await db.refresh(order)
    return order_out(order, ctx.lang, await history_of(db, EntityType.FOOD_ORDER.value, order.id))
