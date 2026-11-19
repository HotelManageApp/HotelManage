"""Staff login, refresh-token rotation, logout and password change (spec/SPEC-staff-auth.md)."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import BadRequest, Unauthorized
from app.core.logging import get_logger
from app.modules.staff_auth import repository
from app.modules.staff_auth.models import Staff
from app.modules.staff_auth.security import (
    encode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)

logger = get_logger(__name__)

# One message for every login failure, so callers cannot tell which part was wrong.
LOGIN_FAILED_MESSAGE = "Email hoặc mật khẩu không đúng"
SESSION_EXPIRED_MESSAGE = "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại"

LOGIN_FAILURES_PER_EMAIL = rate_limit.Window(limit=5, seconds=15 * 60, lock_seconds=15 * 60)
LOGIN_FAILURES_PER_IP = rate_limit.Window(limit=20, seconds=15 * 60, lock_seconds=15 * 60)


@dataclass(frozen=True)
class IssuedSession:
    staff: Staff
    access_token: str
    access_expires_in: int
    refresh_token: str
    refresh_max_age: int


def _email_key(email: str) -> str:
    digest = hashlib.sha256(email.lower().encode()).hexdigest()
    return f"staff_login:email:{digest}"


def _ip_key(ip: str) -> str:
    return f"staff_login:ip:{ip}"


def _issue(
    db: AsyncSession,
    settings: Settings,
    staff: Staff,
    now: datetime,
    *,
    family_id: uuid.UUID | None = None,
) -> IssuedSession:
    access_ttl = timedelta(minutes=settings.staff_access_token_minutes)
    refresh_ttl = timedelta(hours=settings.staff_refresh_token_hours)
    access_token, _ = encode_access_token(
        staff_id=staff.id,
        role=staff.role,
        token_version=staff.token_version,
        secret=settings.staff_jwt_secret.get_secret_value(),
        ttl=access_ttl,
        now=now,
    )
    refresh_token = new_refresh_token()
    repository.add_refresh_token(
        db,
        staff_id=staff.id,
        token_hash=hash_refresh_token(refresh_token),
        family_id=family_id or uuid.uuid4(),
        expires_at=now + refresh_ttl,
    )
    return IssuedSession(
        staff=staff,
        access_token=access_token,
        access_expires_in=int(access_ttl.total_seconds()),
        refresh_token=refresh_token,
        refresh_max_age=int(refresh_ttl.total_seconds()),
    )


async def login(
    db: AsyncSession, settings: Settings, *, email: str, password: str, client_ip: str
) -> IssuedSession:
    now = datetime.now(UTC)
    email_key, ip_key = _email_key(email), _ip_key(client_ip)
    await rate_limit.ensure_not_locked(db, email_key, now=now)
    await rate_limit.ensure_not_locked(db, ip_key, now=now)

    staff = await repository.get_staff_by_email(db, email)
    usable = staff is not None and staff.is_active
    # Always run the hash, even for unknown or locked accounts (no timing oracle).
    password_ok = verify_password(staff.password_hash if usable and staff else None, password)

    if not (usable and password_ok and staff):
        await rate_limit.record_failure(db, email_key, LOGIN_FAILURES_PER_EMAIL, now=now)
        await rate_limit.record_failure(db, ip_key, LOGIN_FAILURES_PER_IP, now=now)
        await db.commit()
        logger.info("staff_login_failed", email_hash=email_key.rsplit(":", 1)[1], ip=client_ip)
        raise Unauthorized(LOGIN_FAILED_MESSAGE)

    await rate_limit.reset(db, email_key)
    if password_needs_rehash(staff.password_hash):
        staff.password_hash = hash_password(password)
    staff.last_login_at = now
    session = _issue(db, settings, staff, now)
    await db.commit()
    logger.info("staff_login", staff_id=str(staff.id), role=staff.role.value)
    return session


async def refresh(db: AsyncSession, settings: Settings, *, raw_token: str | None) -> IssuedSession:
    """Rotate a refresh token. Reusing a revoked token revokes its whole family."""
    if not raw_token:
        raise Unauthorized(SESSION_EXPIRED_MESSAGE)
    now = datetime.now(UTC)
    current = await repository.get_refresh_token(db, hash_refresh_token(raw_token), for_update=True)
    if current is None:
        raise Unauthorized(SESSION_EXPIRED_MESSAGE)
    if current.revoked_at is not None:
        await repository.revoke_family(db, current.family_id, now)
        await db.commit()
        logger.warning("staff_refresh_token_reuse", staff_id=str(current.staff_id))
        raise Unauthorized(SESSION_EXPIRED_MESSAGE)
    if current.expires_at <= now:
        raise Unauthorized(SESSION_EXPIRED_MESSAGE)

    staff = await repository.get_staff(db, current.staff_id)
    if staff is None or not staff.is_active:
        await repository.revoke_family(db, current.family_id, now)
        await db.commit()
        raise Unauthorized(SESSION_EXPIRED_MESSAGE)

    current.revoked_at = now
    session = _issue(db, settings, staff, now, family_id=current.family_id)
    await db.commit()
    return session


async def logout(db: AsyncSession, *, raw_token: str | None) -> None:
    if not raw_token:
        return
    current = await repository.get_refresh_token(db, hash_refresh_token(raw_token))
    if current is not None and current.revoked_at is None:
        current.revoked_at = datetime.now(UTC)
        await db.commit()


async def change_password(
    db: AsyncSession,
    staff: Staff,
    *,
    current_password: str,
    new_password: str,
    raw_refresh_token: str | None,
) -> None:
    if not verify_password(staff.password_hash, current_password):
        raise BadRequest(
            "Mật khẩu hiện tại không đúng",
            code="INVALID_CURRENT_PASSWORD",
            details=[{"field": "current_password", "issue": "incorrect"}],
        )
    if new_password.lower() == staff.email.lower():
        raise BadRequest(
            "Mật khẩu mới không được trùng email",
            code="VALIDATION_ERROR",
            details=[{"field": "new_password", "issue": "must differ from email"}],
        )
    now = datetime.now(UTC)
    staff.password_hash = hash_password(new_password)
    staff.token_version += 1  # every access token issued before is now rejected
    keep = None
    if raw_refresh_token:
        current = await repository.get_refresh_token(db, hash_refresh_token(raw_refresh_token))
        if current is not None and current.staff_id == staff.id:
            keep = current.id
    await repository.revoke_all_for_staff(db, staff.id, now, except_id=keep)
    await db.commit()
    logger.info("staff_password_changed", staff_id=str(staff.id))
