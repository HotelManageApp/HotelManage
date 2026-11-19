"""Room-service opening hours in the hotel's time zone (overnight ranges such as 18:00–02:00
are supported)."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hotel_settings import HotelSettings, load_hotel_settings


def is_open_at(moment_local: time, opens: time, closes: time) -> bool:
    if opens == closes:
        return True  # open around the clock
    if opens < closes:
        return opens <= moment_local < closes
    return moment_local >= opens or moment_local < closes


def label(opens: time, closes: time) -> str:
    return f"{opens:%H:%M}–{closes:%H:%M}"


async def load(db: AsyncSession) -> HotelSettings:
    return await load_hotel_settings(db)


def accepting_orders(settings: HotelSettings, now: datetime, tz: str) -> bool:
    local = now.astimezone(ZoneInfo(tz)).time()
    return not settings.room_service_paused and is_open_at(
        local, settings.room_service_open, settings.room_service_close
    )
