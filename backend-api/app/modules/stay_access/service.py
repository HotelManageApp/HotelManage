"""Rooms and check-in (spec/SPEC-stay-access.md). Close/re-issue/checkout land in T14."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.modules.staff_auth.models import Staff
from app.modules.stay_access import codes, repository
from app.modules.stay_access.models import Room, RoomStatus, Stay, StayStatus
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
