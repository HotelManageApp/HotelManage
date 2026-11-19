"""Guest login with a room code, token renewal and logout (spec/SPEC-stay-access.md)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import Conflict, Unauthorized
from app.core.logging import get_logger
from app.modules.stay_access import codes
from app.modules.stay_access.models import RevokeReason, Room, Stay, StaySession, StayStatus
from app.modules.stay_access.tokens import encode_stay_token

logger = get_logger(__name__)

INVALID_CODE_MESSAGE = "Mã phòng không hợp lệ hoặc đã hết hạn"

# CONSTRAINTS C4.3
REQUESTS_PER_IP = rate_limit.Window(limit=5, seconds=60, lock_seconds=60)
FAILURES_PER_IP = rate_limit.Window(limit=10, seconds=3600, lock_seconds=15 * 60)
FAILURES_PER_DEVICE = rate_limit.Window(limit=10, seconds=3600, lock_seconds=15 * 60)
GLOBAL_FAILURE_ALERT = 100  # per hour, logged only


@dataclass(frozen=True)
class GuestSession:
    token: str
    expires_at: datetime
    stay: Stay
    room_number: str


def token_expiry(stay: Stay, settings: Settings) -> datetime:
    return stay.expected_checkout_at + timedelta(hours=settings.stay_grace_hours)


async def _record_failure(db: AsyncSession, ip: str, device_id: str, now: datetime) -> None:
    await rate_limit.record_failure(db, f"room_code:fail:ip:{ip}", FAILURES_PER_IP, now=now)
    await rate_limit.record_failure(
        db, f"room_code:fail:device:{device_id}", FAILURES_PER_DEVICE, now=now
    )
    total = await rate_limit.register(db, "room_code:fail:global", window_seconds=3600, now=now)
    if total > GLOBAL_FAILURE_ALERT:
        logger.warning("room_code_bruteforce_suspected", failures_last_hour=total)
    await db.commit()


async def login_with_code(
    db: AsyncSession,
    settings: Settings,
    *,
    raw_code: str,
    device_id: str,
    lang: str,
    client_ip: str,
) -> GuestSession:
    now = datetime.now(UTC)
    # Every attempt counts against the per-IP request budget, right or wrong.
    try:
        await rate_limit.consume(db, f"room_code:ip:{client_ip}", REQUESTS_PER_IP, now=now)
    finally:
        await db.commit()
    await rate_limit.ensure_not_locked(db, f"room_code:fail:ip:{client_ip}", now=now)
    await rate_limit.ensure_not_locked(db, f"room_code:fail:device:{device_id}", now=now)

    code = codes.normalize_code(raw_code)
    stay = room_number = None
    if code is not None:
        lookup = codes.code_lookup(code, settings.room_code_pepper.get_secret_value())
        row = (
            await db.execute(
                select(Stay, Room.number)
                .join(Room, Room.id == Stay.room_id)
                .where(Stay.room_code_lookup == lookup)
                .with_for_update(of=Stay)
            )
        ).one_or_none()
        if row is not None:
            stay, room_number = row

    usable = (
        stay is not None
        and stay.status in (StayStatus.ACTIVE, StayStatus.CHECKOUT_PENDING)
        and now <= token_expiry(stay, settings)
    )
    if not usable or stay is None or room_number is None:
        await _record_failure(db, client_ip, device_id, now)
        logger.info("room_code_login_failed", ip=client_ip)
        raise Unauthorized(INVALID_CODE_MESSAGE)

    # Logging in again from the same device replaces its previous session.
    await db.execute(
        update(StaySession)
        .where(
            StaySession.stay_id == stay.id,
            StaySession.device_id == device_id,
            StaySession.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=RevokeReason.LOGOUT)
    )
    active = await db.scalar(
        select(func.count())
        .select_from(StaySession)
        .where(StaySession.stay_id == stay.id, StaySession.revoked_at.is_(None))
    )
    if (active or 0) >= settings.max_devices_per_stay:
        await db.rollback()
        raise Conflict(
            f"Phòng đã đăng nhập trên {settings.max_devices_per_stay} thiết bị",
            code="TOO_MANY_DEVICES",
        )

    session = StaySession(id=uuid.uuid4(), stay_id=stay.id, device_id=device_id, lang=lang)
    db.add(session)
    expires_at = token_expiry(stay, settings)
    token = encode_stay_token(
        session_id=session.id,
        stay_id=stay.id,
        room_id=stay.room_id,
        expires_at=expires_at,
        secret=settings.stay_jwt_secret.get_secret_value(),
        now=now,
    )
    await rate_limit.reset(db, f"room_code:fail:device:{device_id}")
    await db.commit()
    logger.info("room_code_login", stay_id=str(stay.id), session_id=str(session.id))
    return GuestSession(token=token, expires_at=expires_at, stay=stay, room_number=room_number)


async def renew(
    db: AsyncSession, settings: Settings, *, session_id: uuid.UUID, stay_id: uuid.UUID
) -> GuestSession:
    row = (
        await db.execute(
            select(Stay, Room.number).join(Room, Room.id == Stay.room_id).where(Stay.id == stay_id)
        )
    ).one()
    stay, room_number = row
    expires_at = token_expiry(stay, settings)
    if expires_at <= datetime.now(UTC):
        raise Unauthorized(INVALID_CODE_MESSAGE)
    token = encode_stay_token(
        session_id=session_id,
        stay_id=stay.id,
        room_id=stay.room_id,
        expires_at=expires_at,
        secret=settings.stay_jwt_secret.get_secret_value(),
    )
    return GuestSession(token=token, expires_at=expires_at, stay=stay, room_number=room_number)


async def logout(db: AsyncSession, session_id: uuid.UUID) -> None:
    await db.execute(
        update(StaySession)
        .where(StaySession.id == session_id, StaySession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revoke_reason=RevokeReason.LOGOUT)
    )
    await db.commit()
