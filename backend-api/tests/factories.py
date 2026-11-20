"""Test data builders. Keep them small; each test states what matters to it."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hotel_settings import HotelSettings
from app.modules.room_service.models import (
    FoodOrder,
    MenuCategory,
    MenuItem,
    OrderItem,
    OrderStatus,
)
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.staff_auth.security import encode_access_token, hash_password
from app.modules.stay_access.models import Room, RoomStatus, Stay, StaySession, StayStatus
from tests.conftest import TEST_STAFF_JWT_SECRET

DEFAULT_PASSWORD = "correct-horse-battery"


async def create_staff(
    db: AsyncSession,
    *,
    email: str = "le.tan@hotel.test",
    role: StaffRole = StaffRole.RECEPTION,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Nguyen Van A",
    is_active: bool = True,
) -> Staff:
    staff = Staff(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(staff)
    await db.commit()
    await db.refresh(staff)
    return staff


def staff_headers(staff: Staff) -> dict[str, str]:
    """Authorization header for `staff`, minted directly (skips the login endpoint)."""
    token, _ = encode_access_token(
        staff_id=staff.id,
        role=staff.role,
        token_version=staff.token_version,
        secret=TEST_STAFF_JWT_SECRET,
        ttl=timedelta(minutes=15),
    )
    return {"Authorization": f"Bearer {token}"}


async def create_room(
    db: AsyncSession,
    number: str = "101",
    *,
    floor: int | None = 1,
    status: RoomStatus = RoomStatus.VACANT,
    is_active: bool = True,
) -> Room:
    room = Room(
        number=number, floor=floor, room_type="Standard", status=status, is_active=is_active
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


def checkout_in(days: float = 2) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


async def create_stay(
    db: AsyncSession,
    *,
    room_number: str = "101",
    status: StayStatus = StayStatus.ACTIVE,
    guest_name: str | None = "Tran Thi B",
) -> Stay:
    """An open stay in its own occupied room, checked in by a fresh receptionist."""
    staff = await create_staff(db, email=f"rx-{uuid.uuid4().hex[:8]}@hotel.test")
    room = await create_room(db, room_number, status=RoomStatus.OCCUPIED)
    now = datetime.now(UTC)
    stay = Stay(
        room_id=room.id,
        guest_name=guest_name,
        checkin_at=now,
        expected_checkout_at=now + timedelta(days=2),
        room_charge_vnd=1_000_000,
        status=status,
        code_issued_at=now,
        checked_in_by=staff.id,
    )
    db.add(stay)
    await db.commit()
    await db.refresh(stay)
    return stay


async def add_session(
    db: AsyncSession,
    stay: Stay,
    *,
    fcm_token: str | None = None,
    lang: str = "vi",
    revoked: bool = False,
) -> StaySession:
    session = StaySession(
        stay_id=stay.id,
        device_id=f"device-{uuid.uuid4().hex[:12]}",
        lang=lang,
        fcm_token=fcm_token,
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def kitchen_open_all_day(db: AsyncSession, *, paused: bool = False) -> None:
    """Tests must not depend on the wall clock: open == close means open around the clock."""
    settings = await db.get(HotelSettings, 1)
    assert settings is not None
    settings.room_service_open = settings.room_service_close = datetime.min.time()
    settings.room_service_paused = paused
    await db.commit()


async def create_menu(db: AsyncSession) -> dict[str, MenuItem]:
    """Two categories and four dishes; one sold out, one archived, one in a hidden category."""
    breakfast = MenuCategory(
        code="BREAKFAST", name_vi="Bữa sáng", name_en="Breakfast", sort_order=0
    )
    drink = MenuCategory(code="DRINK", name_vi="Đồ uống", name_en="Drinks", sort_order=1)
    hidden = MenuCategory(code="SEASONAL", name_vi="Theo mùa", name_en="Seasonal", is_active=False)
    db.add_all([breakfast, drink, hidden])
    await db.flush()
    items = {
        "pho": MenuItem(
            category_id=breakfast.id, name_vi="Phở bò", name_en="Beef pho", price_vnd=65000
        ),
        "banhmi": MenuItem(
            category_id=breakfast.id,
            name_vi="Bánh mì",
            name_en="Baguette",
            price_vnd=45000,
            available=False,
        ),
        "cam": MenuItem(
            category_id=drink.id,
            name_vi="Nước cam",
            name_en="Orange juice",
            price_vnd=40000,
            description_vi="Cam tươi",
            description_en="Fresh oranges",
        ),
        "old": MenuItem(
            category_id=drink.id,
            name_vi="Trà sữa",
            name_en="Milk tea",
            price_vnd=35000,
            is_archived=True,
        ),
        "mango": MenuItem(category_id=hidden.id, name_vi="Xoài", name_en="Mango", price_vnd=30000),
    }
    db.add_all(items.values())
    await db.commit()
    for item in items.values():
        await db.refresh(item)
    return items


async def add_food_order(
    db: AsyncSession, stay: Stay, status: OrderStatus, items: list[tuple[MenuItem, int]]
) -> FoodOrder:
    """An order written straight to the database (prices copied from the menu items)."""
    order = FoodOrder(
        stay_id=stay.id,
        room_id=stay.room_id,
        status=status,
        total_vnd=sum(item.price_vnd * qty for item, qty in items),
        source="APP",
    )
    order.items = [
        OrderItem(
            menu_item_id=item.id,
            position=i,
            name_vi=item.name_vi,
            name_en=item.name_en,
            unit_price_vnd=item.price_vnd,
            quantity=qty,
            line_total_vnd=item.price_vnd * qty,
        )
        for i, (item, qty) in enumerate(items)
    ]
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order
