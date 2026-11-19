"""Import every ORM model here so Alembic autogenerate sees the full schema."""

from app.core.db import Base
from app.core.hotel_settings import HotelSettings

__all__ = ["Base", "HotelSettings"]
