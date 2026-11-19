"""Import every ORM model here so Alembic autogenerate sees the full schema."""

from app.core.db import Base
from app.core.hotel_settings import HotelSettings
from app.core.rate_limit import RateLimitBucket
from app.modules.notifications.models import NotificationOutbox
from app.modules.room_service.models import MenuCategory, MenuItem
from app.modules.shared.status_history import StatusHistory
from app.modules.staff_auth.models import Staff, StaffRefreshToken
from app.modules.stay_access.models import Room, Stay, StaySession

__all__ = [
    "Base",
    "HotelSettings",
    "MenuCategory",
    "MenuItem",
    "NotificationOutbox",
    "RateLimitBucket",
    "Room",
    "Staff",
    "StaffRefreshToken",
    "StatusHistory",
    "Stay",
    "StaySession",
]
