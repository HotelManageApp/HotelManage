"""Reception: checkout requests, a stay's bill and its extras/discounts
(SPEC-express-checkout, API nhân viên)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select

from app.core.db import DbSession
from app.core.errors import Conflict, NotFound
from app.modules.express_checkout import service
from app.modules.express_checkout.billing import Bill, build_bill, ensure_bill_editable
from app.modules.express_checkout.models import (
    OPEN_CHECKOUT_STATUSES,
    CheckoutRequest,
    CheckoutStatus,
    PaymentMethod,
    StayCharge,
)
from app.modules.notifications.api import EntityType
from app.modules.room_service.api import open_order_ids
from app.modules.room_service.schemas import HistoryEntry
from app.modules.shared.status_history import history_of
from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.stay_access.models import Room, Stay, StayStatus
from app.modules.stay_access.schemas import StrictModel

Reception = Annotated[Staff, Depends(require_roles(StaffRole.RECEPTION))]

router = APIRouter(tags=["express-checkout"])


class ChargeIn(StrictModel):
    kind: Literal["EXTRA", "DISCOUNT"]
    description: str = Field(min_length=1, max_length=200)
    amount_vnd: int = Field(gt=0, le=1_000_000_000)


class ChargeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    description: str
    amount_vnd: int
    created_at: datetime


async def _open_stay(db: DbSession, stay_id: uuid.UUID, *, for_update: bool = False) -> Stay:
    stmt = select(Stay).where(Stay.id == stay_id)
    if for_update:
        stmt = stmt.with_for_update()
    stay = await db.scalar(stmt)
    if stay is None:
        raise NotFound("Không tìm thấy kỳ lưu trú")
    if stay.status is StayStatus.CLOSED:
        raise Conflict("Kỳ lưu trú đã kết thúc", code="STAY_CLOSED")
    return stay


@router.get("/stays/{stay_id}/bill", response_model=Bill)
async def stay_bill(stay_id: uuid.UUID, _: Reception, db: DbSession) -> Bill:
    """Current bill of an open stay (also for check-out at the desk)."""
    await _open_stay(db, stay_id)
    return await build_bill(db, stay_id)


@router.post(
    "/stays/{stay_id}/charges", response_model=ChargeOut, status_code=status.HTTP_201_CREATED
)
async def add_charge(
    stay_id: uuid.UUID, body: ChargeIn, staff: Reception, db: DbSession
) -> StayCharge:
    await _open_stay(db, stay_id, for_update=True)  # serialises with verify (same stay row)
    await ensure_bill_editable(db, stay_id)
    charge = StayCharge(stay_id=stay_id, created_by=staff.id, **body.model_dump())
    db.add(charge)
    await db.flush()
    await build_bill(db, stay_id)  # a discount larger than the bill -> 409 NEGATIVE_TOTAL
    await db.commit()
    await db.refresh(charge)
    return charge


@router.delete("/stays/{stay_id}/charges/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_charge(
    stay_id: uuid.UUID, charge_id: uuid.UUID, _: Reception, db: DbSession
) -> Response:
    await _open_stay(db, stay_id, for_update=True)
    await ensure_bill_editable(db, stay_id)
    charge = await db.scalar(
        select(StayCharge).where(
            StayCharge.id == charge_id,
            StayCharge.stay_id == stay_id,
            StayCharge.deleted_at.is_(None),
        )
    )
    if charge is None:
        raise NotFound("Không tìm thấy khoản phụ phí")
    charge.deleted_at = datetime.now(UTC)
    await db.flush()
    await build_bill(db, stay_id)  # removing an extra can leave discounts above the bill
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- checkout requests ----------

RECENT_FINISHED = timedelta(hours=24)
OVERDUE_AFTER = timedelta(minutes=10)


class Version(StrictModel):
    version: int = Field(ge=0)


class Complete(Version):
    payment_method: PaymentMethod


class Reject(Version):
    reason: str = Field(min_length=1, max_length=500)


class RequestOut(BaseModel):
    id: uuid.UUID
    stay_id: uuid.UUID
    room_number: str
    guest_name: str | None
    status: CheckoutStatus
    source: str
    feedback_rating: int | None
    feedback_note: str | None
    total_vnd: int | None
    payment_method: str | None
    reject_reason: str | None
    created_at: datetime
    verified_at: datetime | None
    completed_at: datetime | None
    rejected_at: datetime | None
    version: int
    overdue: bool


class RequestDetail(RequestOut):
    bill: Bill | None  # the frozen snapshot once verified, else the live bill of the open stay
    bill_is_snapshot: bool
    open_order_ids: list[uuid.UUID]
    history: list[HistoryEntry]


def _out(request: CheckoutRequest, room_number: str, guest_name: str | None) -> RequestOut:
    now = datetime.now(UTC)
    return RequestOut(
        id=request.id,
        stay_id=request.stay_id,
        room_number=room_number,
        guest_name=guest_name,
        status=request.status,
        source=request.source,
        feedback_rating=request.feedback_rating,
        feedback_note=request.feedback_note,
        total_vnd=request.total_vnd,
        payment_method=request.payment_method,
        reject_reason=request.reject_reason,
        created_at=request.created_at,
        verified_at=request.verified_at,
        completed_at=request.completed_at,
        rejected_at=request.rejected_at,
        version=request.version,
        overdue=request.status is CheckoutStatus.CHECKOUT_REQUESTED
        and now - request.created_at > OVERDUE_AFTER,
    )


def _with_stay():
    return (
        select(CheckoutRequest, Room.number, Stay.guest_name)
        .join(Stay, Stay.id == CheckoutRequest.stay_id)
        .join(Room, Room.id == Stay.room_id)
    )


@router.get("/checkout-requests", response_model=list[RequestOut])
async def list_requests(
    _: Reception,
    db: DbSession,
    status_filter: Annotated[CheckoutStatus | None, Query(alias="status")] = None,
) -> list[RequestOut]:
    stmt = _with_stay()
    if status_filter is not None:
        stmt = stmt.where(CheckoutRequest.status == status_filter)
    else:
        stmt = stmt.where(
            or_(
                CheckoutRequest.status.in_(OPEN_CHECKOUT_STATUSES),
                CheckoutRequest.updated_at >= datetime.now(UTC) - RECENT_FINISHED,
            )
        )
    rows = (await db.execute(stmt.order_by(CheckoutRequest.created_at).limit(200))).all()
    return [_out(r, number, guest) for r, number, guest in rows]


async def _detail(db: DbSession, request_id: uuid.UUID) -> RequestDetail:
    row = (
        await db.execute(
            _with_stay()
            .where(CheckoutRequest.id == request_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise NotFound("Không tìm thấy yêu cầu trả phòng")
    request, number, guest = row
    stay = await db.get(Stay, request.stay_id)
    bill: Bill | None
    if request.bill_snapshot is not None:
        bill, snapshot = Bill.model_validate(request.bill_snapshot), True
    elif stay is not None and stay.status is not StayStatus.CLOSED:
        bill, snapshot = await build_bill(db, request.stay_id), False
    else:
        bill, snapshot = None, False
    pending: list[uuid.UUID] = []
    if stay is not None and stay.status is not StayStatus.CLOSED:
        pending = await open_order_ids(db, request.stay_id)
    history = [
        HistoryEntry(
            from_status=h.from_status,
            to_status=h.to_status,
            at=h.created_at,
            by=h.actor.split(":", 1)[0],
            reason=h.reason,
        )
        for h in await history_of(db, EntityType.CHECKOUT.value, request.id)
    ]
    return RequestDetail(
        **_out(request, number, guest).model_dump(),
        bill=bill,
        bill_is_snapshot=snapshot,
        open_order_ids=pending,
        history=history,
    )


@router.get("/checkout-requests/{request_id}", response_model=RequestDetail)
async def get_request(request_id: uuid.UUID, _: Reception, db: DbSession) -> RequestDetail:
    return await _detail(db, request_id)


@router.post("/checkout-requests/{request_id}/verify", response_model=RequestDetail)
async def verify(
    request_id: uuid.UUID, body: Version, staff: Reception, db: DbSession
) -> RequestDetail:
    await service.verify(db, request_id, version=body.version, staff=staff)
    return await _detail(db, request_id)


@router.post("/checkout-requests/{request_id}/complete", response_model=RequestDetail)
async def complete(
    request_id: uuid.UUID, body: Complete, staff: Reception, db: DbSession
) -> RequestDetail:
    await service.complete(
        db,
        request_id,
        version=body.version,
        payment_method=body.payment_method.value,
        staff=staff,
    )
    return await _detail(db, request_id)


@router.post("/checkout-requests/{request_id}/reject", response_model=RequestDetail)
async def reject(
    request_id: uuid.UUID, body: Reject, staff: Reception, db: DbSession
) -> RequestDetail:
    await service.reject(db, request_id, version=body.version, reason=body.reason, staff=staff)
    return await _detail(db, request_id)
