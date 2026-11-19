"""Fixed-window rate limiter and lockout, stored in PostgreSQL (shared by staff and guest login).

Keys are opaque strings such as "staff_login:email:<sha256>" or "room_code:ip:<ip>". Callers hash
personal data (emails) before building a key; IPs and device ids are stored as given.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Integer, Text, case, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import RateLimited


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_bucket"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class Window:
    limit: int
    seconds: int
    lock_seconds: int


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, int((moment - now).total_seconds() + 0.999))


async def locked_for(db: AsyncSession, key: str, *, now: datetime | None = None) -> int | None:
    """Seconds left on an active lock for `key`, or None when not locked."""
    current = _now(now)
    locked_until = await db.scalar(
        select(RateLimitBucket.locked_until).where(RateLimitBucket.key == key)
    )
    if locked_until is not None and locked_until > current:
        return _seconds_until(locked_until, current)
    return None


async def register(
    db: AsyncSession, key: str, *, window_seconds: int, now: datetime | None = None
) -> int:
    """Count one event for `key` in the current window (atomic upsert). Returns the new count."""
    current = _now(now)
    expired = RateLimitBucket.window_start <= current - timedelta(seconds=window_seconds)
    stmt = (
        insert(RateLimitBucket)
        .values(key=key, window_start=current, count=1)
        .on_conflict_do_update(
            index_elements=[RateLimitBucket.key],
            set_={
                "count": case((expired, 1), else_=RateLimitBucket.count + 1),
                "window_start": case((expired, current), else_=RateLimitBucket.window_start),
            },
        )
        .returning(RateLimitBucket.count)
    )
    return int(await db.scalar(stmt) or 0)


async def lock(db: AsyncSession, key: str, *, seconds: int, now: datetime | None = None) -> int:
    current = _now(now)
    until = current + timedelta(seconds=seconds)
    stmt = insert(RateLimitBucket).values(
        key=key, window_start=current, count=0, locked_until=until
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[RateLimitBucket.key], set_={"locked_until": until}
    )
    await db.execute(stmt)
    return seconds


async def reset(db: AsyncSession, key: str) -> None:
    await db.execute(delete(RateLimitBucket).where(RateLimitBucket.key == key))


async def ensure_not_locked(db: AsyncSession, key: str, *, now: datetime | None = None) -> None:
    """Raise 429 with Retry-After while `key` is locked."""
    remaining = await locked_for(db, key, now=now)
    if remaining is not None:
        raise RateLimited(retry_after_seconds=remaining)


async def consume(
    db: AsyncSession, key: str, window: Window, *, now: datetime | None = None
) -> None:
    """Count a request; when the window limit is exceeded, lock the key and raise 429."""
    await ensure_not_locked(db, key, now=now)
    count = await register(db, key, window_seconds=window.seconds, now=now)
    if count > window.limit:
        seconds = await lock(db, key, seconds=window.lock_seconds, now=now)
        raise RateLimited(retry_after_seconds=seconds)


async def record_failure(
    db: AsyncSession, key: str, window: Window, *, now: datetime | None = None
) -> bool:
    """Count a failed attempt. Locks the key when the failure limit is reached. True if locked."""
    count = await register(db, key, window_seconds=window.seconds, now=now)
    if count >= window.limit:
        await lock(db, key, seconds=window.lock_seconds, now=now)
        return True
    return False
