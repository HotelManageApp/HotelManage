"""Single-row table holding hotel-wide settings. Modules add their own columns here."""

from datetime import time

from sqlalchemy import Boolean, CheckConstraint, SmallInteger, Time, text
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
