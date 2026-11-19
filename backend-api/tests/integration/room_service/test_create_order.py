"""Placing, listing and cancelling food orders as a guest (SPEC-room-service, "Tạo đơn")."""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.room_service.models import FoodOrder, MenuItem
from app.modules.shared.status_history import StatusHistory
from app.modules.stay_access.models import Stay, StayStatus
from tests.factories import create_menu, kitchen_open_all_day
from tests.guests import Guest, check_in_guest

ORDERS = "/api/v1/guest/orders"


@pytest.fixture
async def menu(db: AsyncSession) -> dict[str, MenuItem]:
    items = await create_menu(db)
    await kitchen_open_all_day(db)
    return items


@pytest.fixture
async def guest(client: httpx.AsyncClient, db: AsyncSession) -> Guest:
    return await check_in_guest(client, db)


def order_body(menu: dict[str, MenuItem], **extra: object) -> dict:
    return {
        "items": [
            {"item_id": str(menu["pho"].id), "quantity": 2, "note": "ít cay"},
            {"item_id": str(menu["cam"].id), "quantity": 1},
        ],
        **extra,
    }


async def test_place_order_prices_from_the_menu(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    response = await client.post(
        ORDERS, json=order_body(menu, order_note="Gõ cửa nhẹ"), headers=guest.headers
    )
    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "PENDING"
    assert order["total_vnd"] == 2 * 65000 + 40000
    assert [
        (i["name"], i["quantity"], i["unit_price_vnd"], i["line_total_vnd"], i["note"])
        for i in order["items"]
    ] == [
        ("Phở bò", 2, 65000, 130000, "ít cay"),
        ("Nước cam", 1, 40000, 40000, None),
    ]
    assert order["source"] == "APP" and order["order_note"] == "Gõ cửa nhẹ"

    db.expire_all()
    stored = await db.scalar(select(FoodOrder))
    assert stored is not None and str(stored.stay_id) == guest.stay_id
    history = list(await db.scalars(select(StatusHistory.to_status)))
    assert history == ["PENDING"]


async def test_price_change_later_keeps_the_ordered_price(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    order_id = (await client.post(ORDERS, json=order_body(menu), headers=guest.headers)).json()[
        "id"
    ]
    await db.execute(update(MenuItem).where(MenuItem.id == menu["pho"].id).values(price_vnd=99000))
    await db.commit()
    order = (await client.get(f"{ORDERS}/{order_id}", headers=guest.headers)).json()
    assert order["total_vnd"] == 170000


async def test_duplicate_lines_are_merged(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    body = {"items": [{"item_id": str(menu["pho"].id), "quantity": 1}] * 3}
    order = (await client.post(ORDERS, json=body, headers=guest.headers)).json()
    assert [(i["quantity"], i["line_total_vnd"]) for i in order["items"]] == [(3, 195000)]


@pytest.mark.parametrize(
    "extra",
    [
        {"price_vnd": 1},
        {"total_vnd": 1},
        {"room_id": str(uuid.uuid4())},
        {"stay_id": str(uuid.uuid4())},
        {"source": "WEB"},
    ],
    ids=["price", "total", "room_id", "stay_id", "bad-source"],
)
async def test_client_cannot_set_price_room_or_stay(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest, extra: dict
) -> None:
    response = await client.post(ORDERS, json=order_body(menu, **extra), headers=guest.headers)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "items",
    [[], [{"item_id": str(uuid.uuid4()), "quantity": 0}], [{"item_id": "x", "quantity": 1}]],
    ids=["empty", "zero-quantity", "bad-id"],
)
async def test_invalid_lines(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest, items: list
) -> None:
    assert (
        await client.post(ORDERS, json={"items": items}, headers=guest.headers)
    ).status_code == 400


async def test_merged_quantity_over_limit(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    body = {"items": [{"item_id": str(menu["pho"].id), "quantity": 15}] * 2}
    assert (await client.post(ORDERS, json=body, headers=guest.headers)).status_code == 400


@pytest.mark.parametrize(
    "dish", ["banhmi", "old", "mango"], ids=["sold-out", "archived", "hidden-category"]
)
async def test_unavailable_dishes(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest, dish: str
) -> None:
    body = {
        "items": [
            {"item_id": str(menu["pho"].id), "quantity": 1},
            {"item_id": str(menu[dish].id), "quantity": 1},
        ]
    }
    response = await client.post(ORDERS, json=body, headers=guest.headers)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "ITEM_UNAVAILABLE"
    assert error["details"] == [{"item_id": str(menu[dish].id)}]


async def test_unknown_dish(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    body = {"items": [{"item_id": str(uuid.uuid4()), "quantity": 1}]}
    assert (await client.post(ORDERS, json=body, headers=guest.headers)).json()["error"][
        "code"
    ] == "ITEM_UNAVAILABLE"


async def test_kitchen_closed_or_paused(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    items = await create_menu(db)
    await kitchen_open_all_day(db, paused=True)
    response = await client.post(ORDERS, json=order_body(items), headers=guest.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "KITCHEN_CLOSED"


async def test_checkout_pending_cannot_order(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    await db.execute(
        update(Stay)
        .where(Stay.id == uuid.UUID(guest.stay_id))
        .values(status=StayStatus.CHECKOUT_PENDING)
    )
    await db.commit()
    response = await client.post(ORDERS, json=order_body(menu), headers=guest.headers)
    assert response.json()["error"]["code"] == "STAY_CHECKOUT_PENDING"


async def test_at_most_five_pending_orders(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    for _ in range(5):
        assert (
            await client.post(ORDERS, json=order_body(menu), headers=guest.headers)
        ).status_code == 201
    sixth = await client.post(ORDERS, json=order_body(menu), headers=guest.headers)
    assert sixth.status_code == 409
    assert sixth.json()["error"]["code"] == "TOO_MANY_PENDING_ORDERS"


async def test_idempotency_key_returns_the_same_order(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    headers = {**guest.headers, "Idempotency-Key": "tap-0001-abcdef"}
    first = await client.post(ORDERS, json=order_body(menu), headers=headers)
    retry = await client.post(ORDERS, json=order_body(menu), headers=headers)
    assert (first.status_code, retry.status_code) == (201, 200)
    assert first.json()["id"] == retry.json()["id"]

    racing = await asyncio.gather(
        *(
            client.post(
                ORDERS,
                json=order_body(menu),
                headers={**guest.headers, "Idempotency-Key": "tap-0002-race"},
            )
            for _ in range(3)
        )
    )
    assert len({r.json()["id"] for r in racing}) == 1
    db.expire_all()
    assert len(list(await db.scalars(select(FoodOrder.id)))) == 2


async def test_many_concurrent_retries_create_one_order(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    """Stress the race: ten parallel requests with one key must all see the same order."""
    headers = {**guest.headers, "Idempotency-Key": "tap-burst-000001"}
    responses = await asyncio.gather(
        *(client.post(ORDERS, json=order_body(menu), headers=headers) for _ in range(10))
    )
    assert {r.status_code for r in responses} <= {200, 201}
    assert len({r.json()["id"] for r in responses}) == 1
    db.expire_all()
    assert len(list(await db.scalars(select(FoodOrder.id)))) == 1


async def test_bad_idempotency_key(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    response = await client.post(
        ORDERS, json=order_body(menu), headers={**guest.headers, "Idempotency-Key": "short"}
    )
    assert response.status_code == 400


async def test_list_detail_and_language(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict
) -> None:
    english = await check_in_guest(client, db, room_number="202", lang="en")
    order_id = (await client.post(ORDERS, json=order_body(menu), headers=english.headers)).json()[
        "id"
    ]
    listed = (await client.get(ORDERS, headers=english.headers)).json()
    assert [o["id"] for o in listed] == [order_id]
    assert listed[0]["items"][0]["name"] == "Beef pho"
    detail = (await client.get(f"{ORDERS}/{order_id}", headers=english.headers)).json()
    assert detail["history"][0]["to_status"] == "PENDING" and detail["history"][0]["by"] == "GUEST"
    assert (
        await client.get(ORDERS, params={"status": "CANCELLED"}, headers=english.headers)
    ).json() == []


async def test_other_stays_orders_are_forbidden(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    other = await check_in_guest(client, db, room_number="202")
    order_id = (await client.post(ORDERS, json=order_body(menu), headers=guest.headers)).json()[
        "id"
    ]
    assert (await client.get(f"{ORDERS}/{order_id}", headers=other.headers)).status_code == 403
    assert (
        await client.post(f"{ORDERS}/{order_id}/cancel", headers=other.headers)
    ).status_code == 403
    assert (await client.get(ORDERS, headers=other.headers)).json() == []
    assert (await client.get(f"{ORDERS}/{uuid.uuid4()}", headers=guest.headers)).status_code == 404


async def test_guest_cancels_only_pending_orders(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    order_id = (await client.post(ORDERS, json=order_body(menu), headers=guest.headers)).json()[
        "id"
    ]
    cancelled = await client.post(f"{ORDERS}/{order_id}/cancel", headers=guest.headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert [h["to_status"] for h in cancelled.json()["history"]] == ["PENDING", "CANCELLED"]

    again = await client.post(f"{ORDERS}/{order_id}/cancel", headers=guest.headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_TRANSITION"
