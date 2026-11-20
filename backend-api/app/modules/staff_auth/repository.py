import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff_auth.models import Staff, StaffRefreshToken


async def get_staff_by_email(db: AsyncSession, email: str) -> Staff | None:
    return await db.scalar(select(Staff).where(Staff.email == email))


async def get_staff(db: AsyncSession, staff_id: uuid.UUID) -> Staff | None:
    return await db.get(Staff, staff_id)


async def get_refresh_token(
    db: AsyncSession, token_hash: str, *, for_update: bool = False
) -> StaffRefreshToken | None:
    stmt = select(StaffRefreshToken).where(StaffRefreshToken.token_hash == token_hash)
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


def add_refresh_token(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    token_hash: str,
    family_id: uuid.UUID,
    expires_at: datetime,
) -> StaffRefreshToken:
    token = StaffRefreshToken(
        staff_id=staff_id, token_hash=token_hash, family_id=family_id, expires_at=expires_at
    )
    db.add(token)
    return token


async def revoke_family(db: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await db.execute(
        update(StaffRefreshToken)
        .where(StaffRefreshToken.family_id == family_id, StaffRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def revoke_all_for_staff(
    db: AsyncSession, staff_id: uuid.UUID, now: datetime, *, except_id: uuid.UUID | None = None
) -> None:
    stmt = update(StaffRefreshToken).where(
        StaffRefreshToken.staff_id == staff_id, StaffRefreshToken.revoked_at.is_(None)
    )
    if except_id is not None:
        stmt = stmt.where(StaffRefreshToken.id != except_id)
    await db.execute(stmt.values(revoked_at=now))
