"""Express checkout steps (SPEC-express-checkout "State machine"). Every step runs in one
transaction with its effect on the stay:

    create            stay -> CHECKOUT_PENDING (no new orders/requests)
    -> BILLING_VERIFIED  needs open_orders = 0; freezes bill_snapshot; charges locked
    -> COMPLETED      stay_access.close_stay: stay CLOSED, sessions revoked, room CLEANING, hooks
    -> REJECTED       stay -> ACTIVE (the guest may ask again)
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.modules.express_checkout.billing import build_bill, open_request
from app.modules.express_checkout.models import CheckoutRequest, CheckoutStatus
from app.modules.express_checkout.state import Actor, check
from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.room_service.api import open_order_ids
from app.modules.shared import status_history
from app.modules.staff_auth.models import Staff
from app.modules.stay_access.deps import StayContext
from app.modules.stay_access.models import Room, Stay, StayStatus
from app.modules.stay_access.service import close_stay

S = CheckoutStatus
AWAITING_RECEPTION = "checkout.awaiting_reception"


@dataclass(frozen=True)
class Created:
    request: CheckoutRequest
    open_orders: int


async def _record(
    db: AsyncSession,
    request: CheckoutRequest,
    from_status: CheckoutStatus | None,
    *,
    actor: str,
    room_number: str,
    reason: str | None = None,
    push: bool,
) -> None:
    status_history.record(
        db,
        entity_type=EntityType.CHECKOUT.value,
        entity_id=request.id,
        from_status=from_status.value if from_status else None,
        to_status=request.status.value,
        actor=actor,
        reason=reason,
    )
    await emit_status_changed(
        db,
        entity_type=EntityType.CHECKOUT,
        entity_id=request.id,
        stay_id=request.stay_id,
        status=request.status.value,
        room_number=room_number,
        actor=actor,
        push=push,
    )


async def create_request(
    db: AsyncSession,
    ctx: StayContext,
    *,
    source: str,
    feedback_rating: int | None,
    feedback_note: str | None,
) -> Created:
    stay = await db.scalar(select(Stay).where(Stay.id == ctx.stay_id).with_for_update())
    if stay is None or stay.status is not StayStatus.ACTIVE:
        raise Conflict("Yêu cầu trả phòng đang được xử lý", code="STAY_CHECKOUT_PENDING")
    existing = await open_request(db, ctx.stay_id)
    if existing is not None:
        raise Conflict(
            "Quý khách đã gửi yêu cầu trả phòng",
            code="CONFLICT",
            details=[{"existing_request_id": str(existing.id)}],
        )
    request = CheckoutRequest(
        id=uuid.uuid4(),
        stay_id=ctx.stay_id,
        status=S.CHECKOUT_REQUESTED,
        source=source,
        feedback_rating=feedback_rating,
        feedback_note=(feedback_note or "").strip() or None,
    )
    db.add(request)
    stay.status = StayStatus.CHECKOUT_PENDING
    try:
        await db.flush()
    except IntegrityError:  # a concurrent request won the unique index
        await db.rollback()
        raise Conflict("Quý khách đã gửi yêu cầu trả phòng", code="CONFLICT") from None
    open_orders = len(await open_order_ids(db, ctx.stay_id))
    # The guest just did this: no push for them, reception gets the SSE event (+ sound).
    await _record(db, request, None, actor="GUEST", room_number=ctx.room_number, push=False)
    await db.commit()
    await db.refresh(request)
    return Created(request=request, open_orders=open_orders)


async def load_for_update(
    db: AsyncSession, request_id: uuid.UUID
) -> tuple[CheckoutRequest, Stay, str]:
    row = (
        await db.execute(
            select(CheckoutRequest, Stay, Room.number)
            .join(Stay, Stay.id == CheckoutRequest.stay_id)
            .join(Room, Room.id == Stay.room_id)
            .where(CheckoutRequest.id == request_id)
            .with_for_update(of=[CheckoutRequest, Stay])
        )
    ).one_or_none()
    if row is None:
        raise NotFound("Không tìm thấy yêu cầu trả phòng")
    return row[0], row[1], row[2]


def _staff(staff: Staff) -> str:
    return f"STAFF:{staff.id}"


async def verify(
    db: AsyncSession, request_id: uuid.UUID, *, version: int, staff: Staff
) -> CheckoutRequest:
    request, _stay, room_number = await load_for_update(db, request_id)
    check(
        request.status,
        S.BILLING_VERIFIED,
        Actor.RECEPTION,
        version=request.version,
        expected_version=version,
    )
    pending = await open_order_ids(db, request.stay_id)
    if pending:
        raise Conflict(
            "Còn đơn đồ ăn chưa giao xong, chưa chốt được hóa đơn",
            code="OPEN_ORDERS_EXIST",
            details=[{"order_id": str(order_id)} for order_id in pending],
        )
    bill = await build_bill(db, request.stay_id)
    now = datetime.now(UTC)
    from_status = request.status
    request.status = S.BILLING_VERIFIED
    request.bill_snapshot = bill.model_dump(mode="json")
    request.total_vnd = bill.total_vnd
    request.verified_by = staff.id
    request.verified_at = now
    request.version += 1
    await _record(db, request, from_status, actor=_staff(staff), room_number=room_number, push=True)
    await db.commit()
    await db.refresh(request)
    return request


async def complete(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    version: int,
    payment_method: str,
    staff: Staff,
) -> CheckoutRequest:
    request, _stay, room_number = await load_for_update(db, request_id)
    check(
        request.status,
        S.COMPLETED,
        Actor.RECEPTION,
        version=request.version,
        expected_version=version,
    )
    from_status = request.status
    request.status = S.COMPLETED
    request.payment_method = payment_method
    request.completed_by = staff.id
    request.completed_at = datetime.now(UTC)
    request.version += 1
    # No push of its own: the stay's thank-you (STAY/CLOSED) is the guest's last notification.
    await _record(
        db, request, from_status, actor=_staff(staff), room_number=room_number, push=False
    )
    await db.flush()
    # The same close as a check-out at the desk; it commits this whole step (or rolls it back).
    await close_stay(db, request.stay_id, staff)
    await db.refresh(request)
    return request


async def reject(
    db: AsyncSession, request_id: uuid.UUID, *, version: int, reason: str, staff: Staff
) -> CheckoutRequest:
    request, stay, room_number = await load_for_update(db, request_id)
    check(
        request.status,
        S.REJECTED,
        Actor.RECEPTION,
        version=request.version,
        expected_version=version,
    )
    from_status = request.status
    request.status = S.REJECTED
    request.reject_reason = reason.strip()
    request.rejected_by = staff.id
    request.rejected_at = datetime.now(UTC)
    request.version += 1
    stay.status = StayStatus.ACTIVE
    await _record(
        db,
        request,
        from_status,
        actor=_staff(staff),
        room_number=room_number,
        reason=request.reject_reason,
        push=True,
    )
    await db.commit()
    await db.refresh(request)
    return request


async def refuse_desk_checkout(db: AsyncSession, stay_id: uuid.UUID) -> None:
    """Desk check-out while an express request is open: finish or reject that request first."""
    existing = await open_request(db, stay_id)
    if existing is not None:
        raise Conflict(
            "Phòng đang có yêu cầu trả phòng nhanh, vui lòng xử lý yêu cầu đó",
            code="CHECKOUT_REQUEST_OPEN",
            details=[{"checkout_request_id": str(existing.id)}],
        )
