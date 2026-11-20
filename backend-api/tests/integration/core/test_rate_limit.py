"""Rate limiter against real PostgreSQL (atomic upsert, windows, locks)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import RateLimited
from app.core.rate_limit import (
    Window,
    consume,
    ensure_not_locked,
    locked_for,
    record_failure,
    register,
    reset,
)

T0 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
LOGIN = Window(limit=5, seconds=15 * 60, lock_seconds=15 * 60)
PER_MINUTE = Window(limit=5, seconds=60, lock_seconds=60)


async def test_counts_within_window_and_restarts_after(db: AsyncSession) -> None:
    assert await register(db, "k", window_seconds=60, now=T0) == 1
    assert await register(db, "k", window_seconds=60, now=T0 + timedelta(seconds=30)) == 2
    assert await register(db, "k", window_seconds=60, now=T0 + timedelta(seconds=61)) == 1


async def test_failures_lock_on_the_limit_and_expire(db: AsyncSession) -> None:
    for i in range(4):
        assert not await record_failure(db, "email:x", LOGIN, now=T0 + timedelta(seconds=i))
    assert await locked_for(db, "email:x", now=T0) is None

    assert await record_failure(db, "email:x", LOGIN, now=T0 + timedelta(seconds=4))
    remaining = await locked_for(db, "email:x", now=T0 + timedelta(seconds=5))
    assert remaining is not None and 890 <= remaining <= 900

    with pytest.raises(RateLimited) as exc_info:
        await ensure_not_locked(db, "email:x", now=T0 + timedelta(minutes=1))
    assert int(exc_info.value.headers["Retry-After"]) > 0

    assert await locked_for(db, "email:x", now=T0 + timedelta(minutes=16)) is None


async def test_consume_allows_limit_then_blocks(db: AsyncSession) -> None:
    for i in range(5):
        await consume(db, "ip:1.2.3.4", PER_MINUTE, now=T0 + timedelta(seconds=i))
    with pytest.raises(RateLimited) as exc_info:
        await consume(db, "ip:1.2.3.4", PER_MINUTE, now=T0 + timedelta(seconds=6))
    assert exc_info.value.headers["Retry-After"] == "60"
    with pytest.raises(RateLimited):  # still locked, even though the counter would reset
        await consume(db, "ip:1.2.3.4", PER_MINUTE, now=T0 + timedelta(seconds=40))


async def test_keys_are_independent_and_reset_clears(db: AsyncSession) -> None:
    for _ in range(5):
        await record_failure(db, "a", LOGIN, now=T0)
    assert await locked_for(db, "a", now=T0) is not None
    assert await locked_for(db, "b", now=T0) is None
    await reset(db, "a")
    assert await locked_for(db, "a", now=T0) is None
    assert await register(db, "a", window_seconds=60, now=T0) == 1


async def test_concurrent_registrations_are_not_lost(db: AsyncSession) -> None:
    """Twenty parallel sessions increment the same key; the upsert must not drop any."""
    maker = async_sessionmaker(db.bind, expire_on_commit=False)

    async def hit() -> None:
        async with maker() as session, session.begin():
            await register(session, "burst", window_seconds=60, now=T0)

    await asyncio.gather(*(hit() for _ in range(20)))
    assert await register(db, "burst", window_seconds=60, now=T0) == 21
