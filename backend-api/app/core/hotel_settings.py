"""Single-row table holding hotel-wide settings. Later modules add columns (see their specs)."""

from sqlalchemy import CheckConstraint, SmallInteger, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class HotelSettings(TimestampMixin, Base):
    __tablename__ = "hotel_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
