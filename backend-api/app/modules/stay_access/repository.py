import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.stay_access.models import Room, Stay, StayStatus


async def get_room(
    db: AsyncSession, room_id: uuid.UUID, *, for_update: bool = False
) -> Room | None:
    stmt = select(Room).where(Room.id == room_id)
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def get_room_by_number(db: AsyncSession, number: str) -> Room | None:
    return await db.scalar(select(Room).where(Room.number == number))


async def list_rooms_with_open_stay(db: AsyncSession) -> list[tuple[Room, Stay | None]]:
    stmt = (
        select(Room, Stay)
        .outerjoin(Stay, (Stay.room_id == Room.id) & (Stay.status != StayStatus.CLOSED))
        .order_by(Room.floor.nulls_last(), Room.number)
    )
    return [(room, stay) for room, stay in (await db.execute(stmt)).all()]


async def get_stay(
    db: AsyncSession, stay_id: uuid.UUID, *, for_update: bool = False
) -> Stay | None:
    stmt = select(Stay).where(Stay.id == stay_id)
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def list_stays(db: AsyncSession, status: StayStatus | None) -> list[tuple[Stay, str]]:
    stmt = select(Stay, Room.number).join(Room, Room.id == Stay.room_id)
    if status is not None:
        stmt = stmt.where(Stay.status == status)
    stmt = stmt.order_by(Stay.checkin_at.desc()).limit(200)
    return [(stay, number) for stay, number in (await db.execute(stmt)).all()]


async def code_lookup_in_use(db: AsyncSession, lookup: str) -> bool:
    return await db.scalar(select(Stay.id).where(Stay.room_code_lookup == lookup)) is not None
