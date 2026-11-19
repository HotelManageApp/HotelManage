import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.room_service.models import FoodOrder, OrderStatus
from app.modules.shared.status_history import StatusHistory
from app.modules.stay_access.schemas import StrictModel


class OrderLineIn(StrictModel):
    item_id: uuid.UUID
    quantity: int = Field(ge=1, le=20)
    note: str | None = Field(default=None, max_length=200)


class CreateOrder(StrictModel):
    """No price, total, room or stay here: the server decides all of them (C2.4, C4.1)."""

    items: list[OrderLineIn] = Field(min_length=1, max_length=20)
    order_note: str | None = Field(default=None, max_length=300)
    source: Literal["APP", "CHATBOT"] = "APP"


class OrderLineOut(BaseModel):
    item_id: uuid.UUID
    name: str
    quantity: int
    unit_price_vnd: int
    line_total_vnd: int
    note: str | None


class HistoryEntry(BaseModel):
    from_status: str | None
    to_status: str
    at: datetime
    by: str  # GUEST | STAFF | SYSTEM — never a staff id for guests
    reason: str | None


class OrderOut(BaseModel):
    id: uuid.UUID
    status: OrderStatus
    items: list[OrderLineOut]
    total_vnd: int
    order_note: str | None
    source: str
    estimated_minutes: int | None
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    history: list[HistoryEntry] | None = None


def order_out(order: FoodOrder, lang: str, history: list[StatusHistory] | None = None) -> OrderOut:
    return OrderOut(
        id=order.id,
        status=order.status,
        items=[
            OrderLineOut(
                item_id=line.menu_item_id,
                name=line.name(lang),
                quantity=line.quantity,
                unit_price_vnd=line.unit_price_vnd,
                line_total_vnd=line.line_total_vnd,
                note=line.note,
            )
            for line in order.items
        ],
        total_vnd=order.total_vnd,
        order_note=order.order_note,
        source=order.source,
        estimated_minutes=order.estimated_minutes,
        cancel_reason=order.cancel_reason,
        created_at=order.created_at,
        updated_at=order.updated_at,
        version=order.version,
        history=None
        if history is None
        else [
            HistoryEntry(
                from_status=h.from_status,
                to_status=h.to_status,
                at=h.created_at,
                by=h.actor.split(":", 1)[0],
                reason=h.reason,
            )
            for h in history
        ],
    )
