"""Rooms, check-in, re-issue, check-out and close_stay (spec/SPEC-stay-access.md)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.modules.staff_auth.models import Staff
from app.modules.stay_access import codes, events, repository
from app.modules.stay_access.models import (
    RevokeReason,
    Room,
    RoomStatus,
    Stay,
    StaySession,
    StayStatus,
)
from app.modules.stay_access.schemas import CheckInRequest, RoomCreate, RoomUpdate, StayUpdate

logger = get_logger(__name__)

_CODE_ATTEMPTS = 5


@dataclass(frozen=True)
class IssuedStayCode:
    stay: Stay
    room_number: str
    code: str  # raw, normalised (8 chars) — return once, never log or store

    @property
    def display_code(self) -> str:
        return codes.format_code(self.code)

    @property
    def qr_payload(self) -> str:
        return codes.qr_payload(self.code)


# ---------- rooms ----------


async def create_room(db: AsyncSession, body: RoomCreate) -> Room:
    if await repository.get_room_by_number(db, body.number) is not None:
        raise Conflict(f"Phòng {body.number} đã tồn tại", code="ROOM_NUMBER_TAKEN")
    room = Room(number=body.number, floor=body.floor, room_type=body.room_type)
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


async def update_room(db: AsyncSession, room_id: uuid.UUID, body: RoomUpdate) -> Room:
    room = await repository.get_room(db, room_id, for_update=True)
    if room is None:
        raise NotFound("Không tìm thấy phòng")
    changes = body.model_dump(exclude_unset=True)
    if "number" in changes and changes["number"] != room.number:
        if await repository.get_room_by_number(db, changes["number"]) is not None:
            raise Conflict(f"Phòng {changes['number']} đã tồn tại", code="ROOM_NUMBER_TAKEN")
    if changes.get("is_active") is False and room.status != RoomStatus.VACANT:
        raise Conflict("Chỉ ngừng kinh doanh được phòng đang trống", code="ROOM_NOT_VACANT")
    for field, value in changes.items():
        if value is None and field in {"number", "is_active"}:
            continue
        setattr(room, field, value)
    await db.commit()
    await db.refresh(room)
    return room


# ---------- stays ----------


async def _new_code(db: AsyncSession, pepper: str) -> tuple[str, str]:
    """A fresh code whose lookup is not used by any live stay (collisions are very rare)."""
    for _ in range(_CODE_ATTEMPTS):
        code = codes.generate_code()
        lookup = codes.code_lookup(code, pepper)
        if not await repository.code_lookup_in_use(db, lookup):
            return code, lookup
    raise Conflict("Không sinh được mã phòng, vui lòng thử lại", code="CODE_GENERATION_FAILED")


async def check_in(
    db: AsyncSession, settings: Settings, staff: Staff, body: CheckInRequest
) -> IssuedStayCode:
    now = datetime.now(UTC)
    if body.expected_checkout_at <= now:
        raise ValidationFailed(
            details=[{"field": "expected_checkout_at", "issue": "must be in the future"}]
        )
    # Row lock: two receptionists checking in the same room are serialised here.
    room = await repository.get_room(db, body.room_id, for_update=True)
    if room is None or not room.is_active:
        raise NotFound("Không tìm thấy phòng")
    if room.status != RoomStatus.VACANT:
        raise Conflict(f"Phòng {room.number} không ở trạng thái trống", code="ROOM_NOT_VACANT")

    code, lookup = await _new_code(db, settings.room_code_pepper.get_secret_value())
    stay = Stay(
        room_id=room.id,
        guest_name=body.guest_name,
        guest_count=body.guest_count,
        checkin_at=now,
        expected_checkout_at=body.expected_checkout_at,
        room_charge_vnd=body.room_charge_vnd,
        note=body.note,
        status=StayStatus.ACTIVE,
        room_code_lookup=lookup,
        code_issued_at=now,
        checked_in_by=staff.id,
    )
    db.add(stay)
    room.status = RoomStatus.OCCUPIED
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise Conflict(f"Phòng {room.number} vừa được check-in", code="ROOM_NOT_VACANT") from None
    await db.refresh(stay)
    logger.info("stay_checked_in", stay_id=str(stay.id), room=room.number, staff_id=str(staff.id))
    return IssuedStayCode(stay=stay, room_number=room.number, code=code)


async def update_stay(db: AsyncSession, stay_id: uuid.UUID, body: StayUpdate) -> tuple[Stay, str]:
    stay = await repository.get_stay(db, stay_id, for_update=True)
    if stay is None:
        raise NotFound("Không tìm thấy kỳ lưu trú")
    if stay.status == StayStatus.CLOSED:
        raise Conflict("Kỳ lưu trú đã kết thúc", code="STAY_CLOSED")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("room_charge_vnd") is not None and await events.bill_locked(db, stay.id):
        raise Conflict("Hóa đơn đã được chốt, không sửa được tiền phòng nữa", code="BILL_LOCKED")
    if changes.get("expected_checkout_at") is not None and (
        changes["expected_checkout_at"] <= stay.checkin_at
    ):
        raise ValidationFailed(
            details=[{"field": "expected_checkout_at", "issue": "must be after check-in"}]
        )
    for field, value in changes.items():
        if value is None and field in {"guest_count", "expected_checkout_at", "room_charge_vnd"}:
            continue
        setattr(stay, field, value)
    await db.commit()
    await db.refresh(stay)
    room = await repository.get_room(db, stay.room_id)
    return stay, room.number if room else ""


# ---------- close / re-issue / rooms after check-out ----------


async def revoke_sessions(
    db: AsyncSession, stay_id: uuid.UUID, reason: RevokeReason, now: datetime
) -> None:
    await db.execute(
        update(StaySession)
        .where(StaySession.stay_id == stay_id, StaySession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason, fcm_token=None)
    )


async def _open_stay_for_update(db: AsyncSession, stay_id: uuid.UUID) -> tuple[Stay, Room]:
    stay = await repository.get_stay(db, stay_id, for_update=True)
    if stay is None:
        raise NotFound("Không tìm thấy kỳ lưu trú")
    if stay.status == StayStatus.CLOSED:
        raise Conflict("Kỳ lưu trú đã kết thúc", code="STAY_CLOSED")
    room = await repository.get_room(db, stay.room_id, for_update=True)
    if room is None:
        raise NotFound("Không tìm thấy phòng")
    return stay, room


async def close_stay(db: AsyncSession, stay_id: uuid.UUID, closed_by: Staff) -> Stay:
    """The only way a stay ends (desk check-out here, express checkout in T45).

    One transaction: stay CLOSED, code lookup cleared, room to CLEANING, the registered
    on-stay-closed hooks, then every guest session revoked. Any failure rolls everything back.
    """
    now = datetime.now(UTC)
    stay, room = await _open_stay_for_update(db, stay_id)
    stay.status = StayStatus.CLOSED
    stay.closed_at = now
    stay.closed_by = closed_by.id
    stay.room_code_lookup = None
    room.status = RoomStatus.CLEANING
    try:
        # Hooks run before sessions are revoked, so notifications can still see device tokens.
        await events.run_on_stay_closed(db, stay.id)
        await revoke_sessions(db, stay.id, RevokeReason.CHECKOUT, now)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(stay)
    logger.info("stay_closed", stay_id=str(stay.id), room=room.number, staff_id=str(closed_by.id))
    return stay


async def reissue_code(
    db: AsyncSession, settings: Settings, stay_id: uuid.UUID, staff: Staff
) -> IssuedStayCode:
    """New code for a stay (suspected leak): old code dead, every device signed out."""
    now = datetime.now(UTC)
    stay, room = await _open_stay_for_update(db, stay_id)
    code, lookup = await _new_code(db, settings.room_code_pepper.get_secret_value())
    stay.room_code_lookup = lookup
    stay.code_issued_at = now
    await revoke_sessions(db, stay.id, RevokeReason.REISSUE, now)
    await db.commit()
    await db.refresh(stay)
    logger.info("stay_code_reissued", stay_id=str(stay.id), staff_id=str(staff.id))
    return IssuedStayCode(stay=stay, room_number=room.number, code=code)


async def mark_vacant(db: AsyncSession, room_id: uuid.UUID) -> Room:
    room = await repository.get_room(db, room_id, for_update=True)
    if room is None:
        raise NotFound("Không tìm thấy phòng")
    if room.status != RoomStatus.CLEANING:
        raise Conflict("Chỉ phòng đang chờ dọn mới đánh dấu đã dọn được", code="ROOM_NOT_CLEANING")
    room.status = RoomStatus.VACANT
    await events.run_on_room_marked_vacant(db, room.id)
    await db.commit()
    await db.refresh(room)
    return room
