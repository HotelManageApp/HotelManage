"""Kitchen and reception views of food orders (spec/SPEC-room-service.md, API nhân viên)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import or_, select

from app.core.db import DbSession
from app.core.errors import NotFound
from app.modules.notifications.api import EntityType
from app.modules.room_service import state
from app.modules.room_service.models import OPEN_ORDER_STATUSES, FoodOrder, OrderStatus
from app.modules.room_service.schemas import OrderOut, order_out
from app.modules.shared.status_history import history_of
from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.stay_access.models import Room, Stay
from app.modules.stay_access.schemas import StrictModel

Kitchen = Annotated[Staff, Depends(require_roles(StaffRole.KITCHEN))]
KitchenOrReception = Annotated[
    Staff, Depends(require_roles(StaffRole.KITCHEN, StaffRole.RECEPTION))
]

RECENT_FINISHED = timedelta(hours=12)
OVERDUE_AFTER = timedelta(minutes=10)

router = APIRouter(prefix="/orders", tags=["staff-orders"])


class StaffOrderOut(OrderOut):
    room_number: str
    guest_name: str | None = None  # reception only; the kitchen does not need it
    overdue: bool


class TransitionBody(StrictModel):
    to: Literal["CONFIRMED", "PREPARING", "DELIVERING", "COMPLETED", "CANCELLED"]
    version: int = Field(ge=0)
    estimated_minutes: int | None = Field(default=None, ge=5, le=180)
    reason: str | None = Field(default=None, max_length=300)


class CancelBody(StrictModel):
    version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=300)


def _staff_view(
    order: FoodOrder, room_number: str, guest_name: str | None, staff: Staff, now: datetime
) -> StaffOrderOut:
    base = order_out(order, "vi")
    return StaffOrderOut(
        **base.model_dump(),
        room_number=room_number,
        guest_name=guest_name if staff.role is StaffRole.RECEPTION else None,
        overdue=order.status is OrderStatus.PENDING and now - order.created_at > OVERDUE_AFTER,
    )


def _with_room():
    return (
        select(FoodOrder, Room.number, Stay.guest_name)
        .join(Room, Room.id == FoodOrder.room_id)
        .join(Stay, Stay.id == FoodOrder.stay_id)
    )


@router.get("", response_model=list[StaffOrderOut])
async def list_orders(
    staff: KitchenOrReception,
    db: DbSession,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    room: Annotated[str | None, Query(max_length=20)] = None,
) -> list[StaffOrderOut]:
    now = datetime.now(UTC)
    stmt = _with_room()
    if status_filter is not None:
        stmt = stmt.where(FoodOrder.status == status_filter)
    else:
        stmt = stmt.where(
            or_(
                FoodOrder.status.in_(OPEN_ORDER_STATUSES),
                FoodOrder.updated_at >= now - RECENT_FINISHED,
            )
        )
    if room:
        stmt = stmt.where(Room.number == room)
    rows = (await db.execute(stmt.order_by(FoodOrder.created_at).limit(300))).all()
    return [_staff_view(order, number, guest, staff, now) for order, number, guest in rows]


async def _load(db: DbSession, order_id: uuid.UUID, *, for_update: bool = False):
    stmt = _with_room().where(FoodOrder.id == order_id)
    if for_update:
        stmt = stmt.with_for_update(of=FoodOrder)
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise NotFound("Không tìm thấy đơn")
    return row


async def _respond(db: DbSession, order: FoodOrder, number: str, guest: str | None, staff: Staff):
    view = _staff_view(order, number, guest, staff, datetime.now(UTC))
    view.history = order_out(
        order, "vi", await history_of(db, EntityType.FOOD_ORDER.value, order.id)
    ).history
    return view


@router.get("/{order_id}", response_model=StaffOrderOut)
async def get_order(order_id: uuid.UUID, staff: KitchenOrReception, db: DbSession) -> StaffOrderOut:
    order, number, guest = await _load(db, order_id)
    return await _respond(db, order, number, guest, staff)


@router.post("/{order_id}/transition", response_model=StaffOrderOut)
async def transition(
    order_id: uuid.UUID, body: TransitionBody, staff: Kitchen, db: DbSession
) -> StaffOrderOut:
    order, number, guest = await _load(db, order_id, for_update=True)
    await state.transition(
        db,
        order,
        OrderStatus(body.to),
        actor=state.Actor.KITCHEN,
        actor_label=f"STAFF:{staff.id}",
        room_number=number,
        reason=body.reason,
        expected_version=body.version,
        estimated_minutes=body.estimated_minutes,
    )
    await db.commit()
    await db.refresh(order)
    return await _respond(db, order, number, guest, staff)


@router.post("/{order_id}/cancel", response_model=StaffOrderOut)
async def cancel(
    order_id: uuid.UUID, body: CancelBody, staff: KitchenOrReception, db: DbSession
) -> StaffOrderOut:
    order, number, guest = await _load(db, order_id, for_update=True)
    actor = state.Actor.KITCHEN if staff.role is StaffRole.KITCHEN else state.Actor.RECEPTION
    await state.transition(
        db,
        order,
        OrderStatus.CANCELLED,
        actor=actor,
        actor_label=f"STAFF:{staff.id}",
        room_number=number,
        reason=body.reason,
        expected_version=body.version,
    )
    await db.commit()
    await db.refresh(order)
    return await _respond(db, order, number, guest, staff)
