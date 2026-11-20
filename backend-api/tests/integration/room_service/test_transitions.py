"""Kitchen and reception moving orders through the API (C5.3, C5.4; SPEC-room-service)."""

import asyncio

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import NotificationOutbox
from app.modules.staff_auth.models import StaffRole
from tests.factories import create_menu, create_staff, kitchen_open_all_day, staff_headers
from tests.guests import check_in_guest


@pytest.fixture
async def setup(client: httpx.AsyncClient, db: AsyncSession) -> dict:
    menu = await create_menu(db)
    await kitchen_open_all_day(db)
    guest = await check_in_guest(client, db)
    order = await client.post(
        "/api/v1/guest/orders",
        json={"items": [{"item_id": str(menu["pho"].id), "quantity": 2}]},
        headers=guest.headers,
    )
    return {
        "guest": guest,
        "order_id": order.json()["id"],
        "kitchen": staff_headers(await create_staff(db, email="k@h.test", role=StaffRole.KITCHEN)),
        "housekeeping": staff_headers(
            await create_staff(db, email="h@h.test", role=StaffRole.HOUSEKEEPING)
        ),
    }


async def _move(
    client: httpx.AsyncClient, setup: dict, to: str, version: int, **extra
) -> httpx.Response:
    return await client.post(
        f"/api/v1/orders/{setup['order_id']}/transition",
        json={"to": to, "version": version, **extra},
        headers=setup["kitchen"],
    )


async def _pushes(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(NotificationOutbox)) or 0


async def test_kitchen_takes_an_order_all_the_way(
    client: httpx.AsyncClient, db: AsyncSession, setup: dict
) -> None:
    confirmed = await _move(client, setup, "CONFIRMED", 0, estimated_minutes=25)
    assert confirmed.status_code == 200
    assert confirmed.json()["estimated_minutes"] == 25
    assert confirmed.json()["room_number"] == "101"
    assert confirmed.json()["guest_name"] is None  # the kitchen does not see guest names

    for version, to in enumerate(["PREPARING", "DELIVERING", "COMPLETED"], start=1):
        response = await _move(client, setup, to, version)
        assert response.status_code == 200, response.text
    done = response.json()
    assert done["status"] == "COMPLETED"
    assert [h["to_status"] for h in done["history"]] == [
        "PENDING",
        "CONFIRMED",
        "PREPARING",
        "DELIVERING",
        "COMPLETED",
    ]
    assert await _pushes(db) == 4  # one push per kitchen step; none for the guest's own order

    guest_view = await client.get(
        f"/api/v1/guest/orders/{setup['order_id']}", headers=setup["guest"].headers
    )
    assert guest_view.json()["status"] == "COMPLETED"


@pytest.mark.parametrize(
    ("to", "expected"),
    [("PREPARING", 409), ("COMPLETED", 409), ("DELIVERING", 409)],
)
async def test_skipping_steps_is_409(
    client: httpx.AsyncClient, db: AsyncSession, setup: dict, to: str, expected: int
) -> None:
    response = await _move(client, setup, to, 0)
    assert response.status_code == expected
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_stale_version_is_409(
    client: httpx.AsyncClient, db: AsyncSession, setup: dict
) -> None:
    results = await asyncio.gather(*(_move(client, setup, "CONFIRMED", 0) for _ in range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "CONFLICT"


async def test_cancel_needs_a_reason_and_both_roles_may_cancel(
    client: httpx.AsyncClient, db: AsyncSession, setup: dict
) -> None:
    assert (await _move(client, setup, "CANCELLED", 0)).status_code == 400  # no reason
    await _move(client, setup, "CONFIRMED", 0)

    reception = setup["guest"].reception
    cancel_url = f"/api/v1/orders/{setup['order_id']}/cancel"
    assert (
        await client.post(cancel_url, json={"version": 1, "reason": ""}, headers=reception)
    ).status_code == 400
    cancelled = await client.post(
        cancel_url, json={"version": 1, "reason": "Khách gọi điện hủy"}, headers=reception
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "CANCELLED" and body["cancel_reason"] == "Khách gọi điện hủy"
    assert body["guest_name"] == "Tran Thi B"  # reception sees the guest


async def test_roles(client: httpx.AsyncClient, db: AsyncSession, setup: dict) -> None:
    order = f"/api/v1/orders/{setup['order_id']}"
    reception = setup["guest"].reception
    body = {"to": "CONFIRMED", "version": 0}
    assert (
        await client.post(f"{order}/transition", json=body, headers=reception)
    ).status_code == 403
    for path in ("/api/v1/orders", order):
        assert (await client.get(path, headers=setup["housekeeping"])).status_code == 403
        assert (await client.get(path, headers=setup["guest"].headers)).status_code == 401
    assert (
        await client.post(
            f"{order}/cancel", json={"version": 0, "reason": "x"}, headers=setup["housekeeping"]
        )
    ).status_code == 403


async def test_queue_shows_open_and_recent_orders(
    client: httpx.AsyncClient, db: AsyncSession, setup: dict
) -> None:
    queue = (await client.get("/api/v1/orders", headers=setup["kitchen"])).json()
    assert [o["id"] for o in queue] == [setup["order_id"]]
    assert queue[0]["status"] == "PENDING" and queue[0]["overdue"] is False
    filtered = await client.get(
        "/api/v1/orders", params={"status": "COMPLETED"}, headers=setup["kitchen"]
    )
    assert filtered.json() == []
    by_room = await client.get("/api/v1/orders", params={"room": "999"}, headers=setup["kitchen"])
    assert by_room.json() == []
