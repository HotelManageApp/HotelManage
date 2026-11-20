"""Single-row table holding hotel-wide settings. Modules add their own columns here."""

from datetime import time

from sqlalchemy import Boolean, CheckConstraint, SmallInteger, Text, Time, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class HotelSettings(TimestampMixin, Base):
    __tablename__ = "hotel_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))

    # room-service (spec/SPEC-room-service.md)
    room_service_open: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'06:00'")
    )
    room_service_close: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'22:00'")
    )
    room_service_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    default_prep_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("25")
    )

    # concierge (spec/SPEC-concierge-guide.md): shown to guests and put into the bot's prompt
    hotel_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Hotel'"))
    reception_phone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    default_lang: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'vi'"))
    chat_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


async def load_hotel_settings(db: AsyncSession) -> HotelSettings:
    settings = await db.get(HotelSettings, 1)
    if settings is None:  # created by migration 0001; guard against a hand-cleaned table
        raise RuntimeError("hotel_settings row is missing")
    return settings
