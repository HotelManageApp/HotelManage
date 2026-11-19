"""Test data builders. Keep them small; each test states what matters to it."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.staff_auth.security import encode_access_token, hash_password
from app.modules.stay_access.models import Room, RoomStatus, Stay, StaySession, StayStatus
from tests.conftest import TEST_STAFF_JWT_SECRET

DEFAULT_PASSWORD = "correct-horse-battery"


async def create_staff(
    db: AsyncSession,
    *,
    email: str = "le.tan@hotel.test",
    role: StaffRole = StaffRole.RECEPTION,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Nguyen Van A",
    is_active: bool = True,
) -> Staff:
    staff = Staff(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(staff)
    await db.commit()
    await db.refresh(staff)
    return staff


def staff_headers(staff: Staff) -> dict[str, str]:
    """Authorization header for `staff`, minted directly (skips the login endpoint)."""
    token, _ = encode_access_token(
        staff_id=staff.id,
        role=staff.role,
        token_version=staff.token_version,
        secret=TEST_STAFF_JWT_SECRET,
        ttl=timedelta(minutes=15),
    )
    return {"Authorization": f"Bearer {token}"}


async def create_room(
    db: AsyncSession,
    number: str = "101",
    *,
    floor: int | None = 1,
    status: RoomStatus = RoomStatus.VACANT,
    is_active: bool = True,
) -> Room:
    room = Room(
        number=number, floor=floor, room_type="Standard", status=status, is_active=is_active
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


def checkout_in(days: float = 2) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


async def create_stay(
    db: AsyncSession,
    *,
    room_number: str = "101",
    status: StayStatus = StayStatus.ACTIVE,
    guest_name: str | None = "Tran Thi B",
) -> Stay:
    """An open stay in its own occupied room, checked in by a fresh receptionist."""
    staff = await create_staff(db, email=f"rx-{uuid.uuid4().hex[:8]}@hotel.test")
    room = await create_room(db, room_number, status=RoomStatus.OCCUPIED)
    now = datetime.now(UTC)
    stay = Stay(
        room_id=room.id,
        guest_name=guest_name,
        checkin_at=now,
        expected_checkout_at=now + timedelta(days=2),
        room_charge_vnd=1_000_000,
        status=status,
        code_issued_at=now,
        checked_in_by=staff.id,
    )
    db.add(stay)
    await db.commit()
    await db.refresh(stay)
    return stay


async def add_session(
    db: AsyncSession,
    stay: Stay,
    *,
    fcm_token: str | None = None,
    lang: str = "vi",
    revoked: bool = False,
) -> StaySession:
    session = StaySession(
        stay_id=stay.id,
        device_id=f"device-{uuid.uuid4().hex[:12]}",
        lang=lang,
        fcm_token=fcm_token,
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session
