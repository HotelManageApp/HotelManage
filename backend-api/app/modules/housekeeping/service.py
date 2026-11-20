"""Guest housekeeping requests (spec/SPEC-housekeeping.md, "Tạo yêu cầu (khách)")."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ValidationFailed
from app.modules.housekeeping.models import (
    OPEN_HK_STATUSES,
    AmenityCode,
    HkStatus,
    HkType,
    HousekeepingRequest,
    HousekeepingRequestItem,
)
from app.modules.housekeeping.schemas import CreateHousekeepingRequest
from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.shared import status_history
from app.modules.stay_access.deps import StayContext
from app.modules.stay_access.models import Stay

MAX_OPEN_AMENITY_REQUESTS = 3
PREFERRED_TIME_WINDOW = timedelta(hours=24)


def _invalid(field: str, issue: str) -> ValidationFailed:
    return ValidationFailed(details=[{"field": field, "issue": issue}])


def validate(body: CreateHousekeepingRequest, stay: Stay, now: datetime) -> datetime | None:
    if body.type == "AMENITY" and not body.amenities:
        raise _invalid("amenities", "required for AMENITY")
    if body.type == "CLEANING" and body.amenities:
        raise _invalid("amenities", "not allowed for CLEANING")
    if (
        any(line.code is AmenityCode.OTHER for line in body.amenities or [])
        and not (body.note or "").strip()
    ):
        raise _invalid("note", "required when asking for OTHER")
    if body.preferred_time == "ASAP":
        return None
    preferred = body.preferred_time
    if preferred < now - timedelta(minutes=5) or preferred > now + PREFERRED_TIME_WINDOW:
        raise _invalid("preferred_time", "must be within the next 24 hours")
    if preferred > stay.expected_checkout_at:
        raise _invalid("preferred_time", "must be before check-out")
    return preferred


async def _by_key(db: AsyncSession, stay_id: uuid.UUID, key: str) -> HousekeepingRequest | None:
    return await db.scalar(
        select(HousekeepingRequest).where(
            HousekeepingRequest.stay_id == stay_id, HousekeepingRequest.idempotency_key == key
        )
    )


async def create_request(
    db: AsyncSession,
    ctx: StayContext,
    body: CreateHousekeepingRequest,
    *,
    idempotency_key: str | None,
) -> tuple[HousekeepingRequest, bool]:
    if idempotency_key:
        existing = await _by_key(db, ctx.stay_id, idempotency_key)
        if existing is not None:
            return existing, False

    now = datetime.now(UTC)
    stay = await db.get(Stay, ctx.stay_id, with_for_update=True)
    if stay is None:
        raise ValidationFailed()
    preferred = validate(body, stay, now)
    kind = HkType(body.type)

    open_requests = select(HousekeepingRequest.id).where(
        HousekeepingRequest.stay_id == ctx.stay_id,
        HousekeepingRequest.type == kind,
        HousekeepingRequest.status.in_(OPEN_HK_STATUSES),
    )
    if kind is HkType.CLEANING:
        existing_id = await db.scalar(open_requests)
        if existing_id is not None:
            raise Conflict(
                "Quý khách đã có một yêu cầu dọn phòng đang xử lý",
                code="CONFLICT",
                details=[{"existing_request_id": str(existing_id)}],
            )
        stay.do_not_disturb = False  # asking for cleaning invites staff in
        stay.dnd_updated_at = now
    else:
        count = await db.scalar(select(func.count()).select_from(open_requests.subquery()))
        if (count or 0) >= MAX_OPEN_AMENITY_REQUESTS:
            raise Conflict(
                "Quý khách đang có nhiều yêu cầu đồ dùng chưa xong",
                code="TOO_MANY_OPEN_REQUESTS",
            )

    request = HousekeepingRequest(
        id=uuid.uuid4(),
        room_id=ctx.room_id,
        stay_id=ctx.stay_id,
        type=kind,
        status=HkStatus.REQUESTED,
        preferred_time=preferred,
        note=(body.note or "").strip() or None,
        source=body.source,
        idempotency_key=idempotency_key,
        items=[
            HousekeepingRequestItem(code=line.code, quantity=line.quantity)
            for line in body.amenities or []
        ],
    )
    db.add(request)
    status_history.record(
        db,
        entity_type=EntityType.HOUSEKEEPING.value,
        entity_id=request.id,
        from_status=None,
        to_status=HkStatus.REQUESTED.value,
        actor="GUEST",
    )
    try:
        await db.flush()
        await emit_status_changed(
            db,
            entity_type=EntityType.HOUSEKEEPING,
            entity_id=request.id,
            stay_id=ctx.stay_id,
            status=HkStatus.REQUESTED.value,
            room_number=ctx.room_number,
            actor="GUEST",
            push=False,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if idempotency_key and (existing := await _by_key(db, ctx.stay_id, idempotency_key)):
            return existing, False
        raise Conflict(
            "Quý khách đã có một yêu cầu dọn phòng đang xử lý", code="CONFLICT"
        ) from None
    await db.refresh(request)
    return request, True
