"""Orders when a stay closes, overdue reminders, and the food bill (SPEC-room-service)."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.api import STAFF_EVENTS_CHANNEL
from app.modules.notifications.models import NotificationOutbox
from app.modules.room_service.api import count_open_orders, get_stay_food_total
from app.modules.room_service.jobs import remind_overdue_orders
from app.modules.room_service.models import FoodOrder, OrderStatus
from app.modules.staff_auth.models import StaffRole
from tests.conftest import TEST_DATABASE_URL
from tests.factories import create_menu, create_staff, kitchen_open_all_day, staff_headers
from tests.guests import check_in_guest


@pytest.fixture
async def world(client: httpx.AsyncClient, db: AsyncSession) -> dict:
    menu = await create_menu(db)
    await kitchen_open_all_day(db)
    guest = await check_in_guest(client, db)
    kitchen = staff_headers(await create_staff(db, email="k@h.test", role=StaffRole.KITCHEN))

    async def order(quantity: int = 1) -> str:
        response = await client.post(
            "/api/v1/guest/orders",
            json={"items": [{"item_id": str(menu["pho"].id), "quantity": quantity}]},
            headers=guest.headers,
        )
        return response.json()["id"]

    async def move(order_id: str, *steps: str) -> None:
        for version, to in enumerate(steps):
            response = await client.post(
                f"/api/v1/orders/{order_id}/transition",
                json={"to": to, "version": version},
                headers=kitchen,
            )
            assert response.status_code == 200, response.text

    return {"guest": guest, "order": order, "move": move}


async def _statuses(db: AsyncSession) -> dict[str, OrderStatus]:
    db.expire_all()
    rows = await db.execute(select(FoodOrder.id, FoodOrder.status))
    return {str(order_id): status for order_id, status in rows.all()}


async def test_closing_a_stay_cancels_only_orders_not_yet_cooking(
    client: httpx.AsyncClient, db: AsyncSession, world: dict
) -> None:
    pending = await world["order"]()
    confirmed = await world["order"]()
    cooking = await world["order"]()
    done = await world["order"]()
    await world["move"](confirmed, "CONFIRMED")
    await world["move"](cooking, "CONFIRMED", "PREPARING")
    await world["move"](done, "CONFIRMED", "PREPARING", "DELIVERING", "COMPLETED")
    pushes_before = len(list(await db.scalars(select(NotificationOutbox.id))))

    guest = world["guest"]
    checkout = await client.post(f"/api/v1/stays/{guest.stay_id}/checkout", headers=guest.reception)
    assert checkout.status_code == 200

    statuses = await _statuses(db)
    assert statuses[pending] is OrderStatus.CANCELLED
    assert statuses[confirmed] is OrderStatus.CANCELLED
    assert statuses[cooking] is OrderStatus.PREPARING
    assert statuses[done] is OrderStatus.COMPLETED
    reasons = set(
        await db.scalars(
            select(FoodOrder.cancel_reason).where(FoodOrder.cancel_reason.is_not(None))
        )
    )
    assert reasons == {"STAY_CLOSED"}
    # No "order cancelled" pushes at check-out (no device token here, and push is off anyway).
    assert len(list(await db.scalars(select(NotificationOutbox.id)))) == pushes_before


async def test_overdue_reminder_fires_once(db: AsyncSession, world: dict) -> None:
    order_id = await world["order"]()
    received: list[dict] = []
    conn = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", ""))
    await conn.add_listener(STAFF_EVENTS_CHANNEL, lambda *a: received.append(json.loads(a[3])))
    try:
        assert await remind_overdue_orders(db) == 0  # only just placed

        await db.execute(
            update(FoodOrder)
            .where(FoodOrder.id == uuid.UUID(order_id))
            .values(created_at=datetime.now(UTC) - timedelta(minutes=11))
        )
        await db.commit()
        assert await remind_overdue_orders(db) == 1
        assert await remind_overdue_orders(db) == 0  # once only
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.02)
    finally:
        await conn.close()
    assert [(e["event"], e["entity_id"], e["room_number"]) for e in received] == [
        ("order_overdue", order_id, "101")
    ]


async def test_food_bill(db: AsyncSession, world: dict) -> None:
    done = await world["order"](2)
    await world["move"](done, "CONFIRMED", "PREPARING", "DELIVERING", "COMPLETED")
    await world["order"]()  # still open
    stay_id = uuid.UUID(world["guest"].stay_id)

    bill = await get_stay_food_total(db, stay_id)
    assert bill.total_vnd == 130000
    assert [(str(o.order_id), o.total_vnd, o.item_count) for o in bill.orders] == [
        (done, 130000, 2)
    ]
    assert bill.open_orders == 1
    assert await count_open_orders(db, uuid.uuid4()) == 0
