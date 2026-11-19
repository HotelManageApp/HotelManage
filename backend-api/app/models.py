"""Import every ORM model here so Alembic autogenerate sees the full schema."""

from app.core.db import Base
from app.core.hotel_settings import HotelSettings
from app.core.rate_limit import RateLimitBucket
from app.modules.concierge_data.models import ChatMessage, KbEntry, NearbyPlace
from app.modules.housekeeping.models import HousekeepingRequest, HousekeepingRequestItem
from app.modules.notifications.models import NotificationOutbox
from app.modules.room_service.models import FoodOrder, MenuCategory, MenuItem, OrderItem
from app.modules.shared.status_history import StatusHistory
from app.modules.staff_auth.models import Staff, StaffRefreshToken
from app.modules.stay_access.models import Room, Stay, StaySession

__all__ = [
    "Base",
    "ChatMessage",
    "FoodOrder",
    "HotelSettings",
    "HousekeepingRequest",
    "HousekeepingRequestItem",
    "KbEntry",
    "MenuCategory",
    "MenuItem",
    "NearbyPlace",
    "NotificationOutbox",
    "OrderItem",
    "RateLimitBucket",
    "Room",
    "Staff",
    "StaffRefreshToken",
    "StatusHistory",
    "Stay",
    "StaySession",
]
