"""Guest side of express checkout (SPEC-express-checkout, API khách; chatbot tool §4.5)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.db import DbSession
from app.core.errors import NotFound
from app.modules.express_checkout import service
from app.modules.express_checkout.billing import BillLine, build_bill
from app.modules.express_checkout.models import CheckoutRequest
from app.modules.stay_access.deps import ActiveStay, CurrentStay
from app.modules.stay_access.schemas import StrictModel

router = APIRouter(prefix="/guest", tags=["guest-checkout"])


class GuestBill(BaseModel):
    """A bill as the guest sees it: no guest name, nothing they did not already know."""

    room_number: str
    lines: list[BillLine]
    total_vnd: int
    open_orders: int
    currency: str = "VND"
    generated_at: datetime
    is_estimate: bool


def guest_bill(bill: dict[str, Any], *, is_estimate: bool) -> GuestBill:
    return GuestBill(
        room_number=bill["stay"]["room_number"],
        lines=bill["lines"],
        total_vnd=bill["total_vnd"],
        open_orders=bill["open_orders"],
        generated_at=bill["generated_at"],
        is_estimate=is_estimate,
    )


class CreateCheckout(StrictModel):
    """No amount, room or stay: the server decides (C2.4, C4.1)."""

    guest_confirmed: Literal[True]
    feedback_rating: int | None = Field(default=None, ge=1, le=5)
    feedback_note: str | None = Field(default=None, max_length=500)
    source: Literal["APP", "CHATBOT"] = "APP"


class CheckoutCreated(BaseModel):
    """Same shape as the `request_express_checkout` tool output (chatbot-tools-spec §4.5)."""

    checkout_request_id: uuid.UUID
    status: str
    open_orders: int
    message_key: str


class GuestCheckout(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    feedback_rating: int | None
    reject_reason: str | None
    bill: GuestBill | None  # the frozen bill once reception verified it


@router.get("/checkout/preview", response_model=GuestBill)
async def preview(ctx: CurrentStay, db: DbSession) -> GuestBill:
    bill = await build_bill(db, ctx.stay_id)
    return guest_bill(bill.model_dump(mode="json"), is_estimate=True)


@router.post(
    "/checkout-requests", response_model=CheckoutCreated, status_code=status.HTTP_201_CREATED
)
async def create(body: CreateCheckout, ctx: ActiveStay, db: DbSession) -> CheckoutCreated:
    created = await service.create_request(
        db,
        ctx,
        source=body.source,
        feedback_rating=body.feedback_rating,
        feedback_note=body.feedback_note,
    )
    return CheckoutCreated(
        checkout_request_id=created.request.id,
        status=created.request.status.value,
        open_orders=created.open_orders,
        message_key=service.AWAITING_RECEPTION,
    )


@router.get("/checkout-requests/current", response_model=GuestCheckout)
async def current(ctx: CurrentStay, db: DbSession) -> GuestCheckout:
    request = await db.scalar(
        select(CheckoutRequest)
        .where(CheckoutRequest.stay_id == ctx.stay_id)
        .order_by(CheckoutRequest.created_at.desc())
        .limit(1)
    )
    if request is None:
        raise NotFound("Chưa có yêu cầu trả phòng")
    return GuestCheckout(
        id=request.id,
        status=request.status.value,
        created_at=request.created_at,
        feedback_rating=request.feedback_rating,
        reject_reason=request.reject_reason,
        bill=guest_bill(request.bill_snapshot, is_estimate=False)
        if request.bill_snapshot
        else None,
    )
