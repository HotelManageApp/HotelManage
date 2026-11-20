"""The one place a stay's bill is computed: estimate for the guest, verification at the desk,
the printed slip and the snapshot frozen at BILLING_VERIFIED (SPEC-express-checkout "Hóa đơn").

    room      stay.room_charge_vnd
    food      each COMPLETED order (cancelled or open orders are not billed)
    extras    stay_charge EXTRA, not deleted
    discounts stay_charge DISCOUNT, not deleted (subtracted)
    total     room + food + extras − discounts; below zero -> 409 NEGATIVE_TOTAL
    open_orders  orders still in progress: not billed, they only block the final bill
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.express_checkout.models import (
    OPEN_CHECKOUT_STATUSES,
    ChargeKind,
    CheckoutRequest,
    CheckoutStatus,
    StayCharge,
)
from app.modules.room_service.api import get_stay_food_total
from app.modules.stay_access.models import Room, Stay

LineType = Literal["ROOM", "FOOD", "EXTRA", "DISCOUNT"]


class BillStay(BaseModel):
    room_number: str
    guest_name: str | None
    checkin_at: datetime
    expected_checkout_at: datetime


class BillLine(BaseModel):
    type: LineType
    description: str
    amount_vnd: int  # always positive; DISCOUNT lines are subtracted
    order_id: uuid.UUID | None = None
    charge_id: uuid.UUID | None = None


class Bill(BaseModel):
    stay: BillStay
    lines: list[BillLine]
    total_vnd: int
    open_orders: int
    currency: Literal["VND"] = "VND"
    generated_at: datetime


def _order_label(order_id: uuid.UUID, item_count: int) -> str:
    return f"Đơn #{str(order_id)[:4].upper()} ({item_count} món)"


async def build_bill(db: AsyncSession, stay_id: uuid.UUID) -> Bill:
    row = (
        await db.execute(
            select(Stay, Room.number).join(Room, Room.id == Stay.room_id).where(Stay.id == stay_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFound("Không tìm thấy kỳ lưu trú")
    stay, room_number = row

    lines = [BillLine(type="ROOM", description="Tiền phòng", amount_vnd=stay.room_charge_vnd)]
    food = await get_stay_food_total(db, stay_id)
    lines += [
        BillLine(
            type="FOOD",
            description=_order_label(o.order_id, o.item_count),
            amount_vnd=o.total_vnd,
            order_id=o.order_id,
        )
        for o in food.orders
    ]
    charges = await db.scalars(
        select(StayCharge)
        .where(StayCharge.stay_id == stay_id, StayCharge.deleted_at.is_(None))
        .order_by(StayCharge.created_at, StayCharge.id)
    )
    for charge in charges:
        lines.append(
            BillLine(
                type="DISCOUNT" if charge.kind == ChargeKind.DISCOUNT else "EXTRA",
                description=charge.description,
                amount_vnd=charge.amount_vnd,
                charge_id=charge.id,
            )
        )

    total = sum(-line.amount_vnd if line.type == "DISCOUNT" else line.amount_vnd for line in lines)
    if total < 0:
        raise Conflict(
            "Giảm giá lớn hơn tổng hóa đơn", code="NEGATIVE_TOTAL", details=[{"total_vnd": total}]
        )
    return Bill(
        stay=BillStay(
            room_number=room_number,
            guest_name=stay.guest_name,
            checkin_at=stay.checkin_at,
            expected_checkout_at=stay.expected_checkout_at,
        ),
        lines=lines,
        total_vnd=total,
        open_orders=food.open_orders,
        generated_at=datetime.now(UTC),
    )


async def open_request(db: AsyncSession, stay_id: uuid.UUID) -> CheckoutRequest | None:
    return await db.scalar(
        select(CheckoutRequest).where(
            CheckoutRequest.stay_id == stay_id,
            CheckoutRequest.status.in_(OPEN_CHECKOUT_STATUSES),
        )
    )


async def is_bill_locked(db: AsyncSession, stay_id: uuid.UUID) -> bool:
    """Once reception has verified the bill, the room charge and the charges are frozen."""
    request = await open_request(db, stay_id)
    return request is not None and request.status is CheckoutStatus.BILLING_VERIFIED


async def ensure_bill_editable(db: AsyncSession, stay_id: uuid.UUID) -> None:
    if await is_bill_locked(db, stay_id):
        raise Conflict(
            "Hóa đơn đã được chốt, không sửa được nữa. Từ chối yêu cầu để chốt lại.",
            code="BILL_LOCKED",
        )
