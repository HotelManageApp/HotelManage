"""Import every ORM model here so Alembic autogenerate sees the full schema."""

from app.core.db import Base
from app.core.hotel_settings import HotelSettings
from app.core.rate_limit import RateLimitBucket
from app.modules.staff_auth.models import Staff, StaffRefreshToken
from app.modules.stay_access.models import Room, Stay, StaySession

__all__ = [
    "Base",
    "HotelSettings",
    "RateLimitBucket",
    "Room",
    "Staff",
    "StaffRefreshToken",
    "Stay",
    "StaySession",
]
