"""`POST /guest/orders/preview`: the summary the concierge shows before the guest confirms
(SPEC-concierge-actions). Same body, same checks, same prices as placing the order; no writes."""

import uuid
from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import NotificationOutbox
from app.modules.room_service.models import FoodOrder, MenuItem
from app.modules.shared.status_history import StatusHistory
from app.modules.stay_access.models import Stay, StayStatus
from tests.factories import create_menu, kitchen_open_all_day
from tests.guests import Guest, check_in_guest

ORDERS = "/api/v1/guest/orders"
PREVIEW = f"{ORDERS}/preview"


@pytest.fixture
async def menu(db: AsyncSession) -> dict[str, MenuItem]:
    items = await create_menu(db)
    await kitchen_open_all_day(db)
    return items


@pytest.fixture
async def guest(client: httpx.AsyncClient, db: AsyncSession) -> Guest:
    return await check_in_guest(client, db)


def body_for(menu: dict[str, MenuItem]) -> dict:
    return {
        "items": [
            {"item_id": str(menu["pho"].id), "quantity": 2, "note": "ít cay"},
            {"item_id": str(menu["cam"].id), "quantity": 1},
            {"item_id": str(menu["pho"].id), "quantity": 1},  # merged like a real order
        ],
        "order_note": "Gõ cửa nhẹ",
        "source": "CHATBOT",
    }


async def rows(db: AsyncSession) -> tuple[int, int, int]:
    return (
        await db.scalar(select(func.count()).select_from(FoodOrder)) or 0,
        await db.scalar(select(func.count()).select_from(StatusHistory)) or 0,
        await db.scalar(select(func.count()).select_from(NotificationOutbox)) or 0,
    )


async def test_preview_matches_the_order_placed_with_the_same_body(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    body = body_for(menu)
    before = await rows(db)
    preview = await client.post(PREVIEW, json=body, headers=guest.headers)
    assert preview.status_code == 200
    assert await rows(db) == before, "a preview writes nothing"

    placed = await client.post(ORDERS, json=body, headers=guest.headers)
    assert placed.status_code == 201
    assert preview.json() == {
        "items": placed.json()["items"],
        "total_vnd": placed.json()["total_vnd"],
    }
    assert preview.json()["total_vnd"] == 3 * 65000 + 40000
    assert [(i["name"], i["quantity"]) for i in preview.json()["items"]] == [
        ("Phở bò", 3),
        ("Nước cam", 1),
    ]


async def test_preview_names_follow_the_session_language(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict
) -> None:
    english = await check_in_guest(client, db, room_number="202", lang="en")
    preview = await client.post(PREVIEW, json=body_for(menu), headers=english.headers)
    assert preview.json()["items"][0]["name"] == "Beef pho"


Scenario = Callable[[AsyncSession, dict, Guest], Awaitable[dict]]


async def _sold_out(db: AsyncSession, menu: dict, guest: Guest) -> dict:
    return {"items": [{"item_id": str(menu["banhmi"].id), "quantity": 1}]}


async def _unknown(db: AsyncSession, menu: dict, guest: Guest) -> dict:
    return {"items": [{"item_id": str(uuid.uuid4()), "quantity": 1}]}


async def _kitchen_paused(db: AsyncSession, menu: dict, guest: Guest) -> dict:
    await kitchen_open_all_day(db, paused=True)
    return body_for(menu)


async def _checkout_pending(db: AsyncSession, menu: dict, guest: Guest) -> dict:
    await db.execute(
        update(Stay)
        .where(Stay.id == uuid.UUID(guest.stay_id))
        .values(status=StayStatus.CHECKOUT_PENDING)
    )
    await db.commit()
    return body_for(menu)


async def _over_limit(db: AsyncSession, menu: dict, guest: Guest) -> dict:
    return {"items": [{"item_id": str(menu["pho"].id), "quantity": 15}] * 2}


async def _room_in_body(db: AsyncSession, menu: dict, guest: Guest) -> dict:
    return {**body_for(menu), "room_id": str(uuid.uuid4())}


async def _total_in_body(db: AsyncSession, menu: dict, guest: Guest) -> dict:
    return {**body_for(menu), "total_vnd": 1}


@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        (_sold_out, 409),
        (_unknown, 409),
        (_kitchen_paused, 409),
        (_checkout_pending, 409),
        (_over_limit, 400),
        (_room_in_body, 400),
        (_total_in_body, 400),
    ],
    ids=[
        "sold-out",
        "unknown-dish",
        "kitchen-paused",
        "checkout-pending",
        "quantity-over-limit",
        "room-id",
        "total",
    ],
)
async def test_preview_refuses_exactly_what_placing_refuses(
    client: httpx.AsyncClient,
    db: AsyncSession,
    menu: dict,
    guest: Guest,
    scenario: Scenario,
    status: int,
) -> None:
    body = await scenario(db, menu, guest)
    preview = await client.post(PREVIEW, json=body, headers=guest.headers)
    placed = await client.post(ORDERS, json=body, headers=guest.headers)
    assert preview.status_code == placed.status_code == status

    def same(response: httpx.Response) -> dict:
        error = dict(response.json()["error"])
        error.pop("request_id", None)
        return error

    assert same(preview) == same(placed)
    assert await db.scalar(select(func.count()).select_from(FoodOrder)) == 0


async def test_preview_counts_the_pending_order_limit(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict, guest: Guest
) -> None:
    for _ in range(5):
        await client.post(ORDERS, json=body_for(menu), headers=guest.headers)
    preview = await client.post(PREVIEW, json=body_for(menu), headers=guest.headers)
    assert preview.status_code == 409
    assert preview.json()["error"]["code"] == "TOO_MANY_PENDING_ORDERS"


async def test_preview_needs_a_guest_token(
    client: httpx.AsyncClient, db: AsyncSession, menu: dict
) -> None:
    assert (await client.post(PREVIEW, json=body_for(menu))).status_code == 401
