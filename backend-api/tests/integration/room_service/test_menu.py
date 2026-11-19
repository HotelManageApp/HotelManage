"""Menu for guests and kitchen, opening hours, settings (SPEC-room-service)."""

from datetime import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.modules.room_service.hours import is_open_at, label
from app.modules.staff_auth.models import StaffRole
from tests.conftest import make_settings
from tests.factories import (
    create_menu,
    create_staff,
    create_stay,
    kitchen_open_all_day,
    staff_headers,
)
from tests.integration.stay_access.test_guest_auth import login_body

GUEST_MENU = "/api/v1/guest/menu"


@pytest.mark.parametrize(
    ("now", "opens", "closes", "expected"),
    [
        (time(6, 0), time(6), time(22), True),
        (time(21, 59), time(6), time(22), True),
        (time(22, 0), time(6), time(22), False),
        (time(5, 59), time(6), time(22), False),
        (time(23, 30), time(18), time(2), True),  # overnight
        (time(1, 0), time(18), time(2), True),
        (time(3, 0), time(18), time(2), False),
        (time(12, 0), time(0), time(0), True),  # around the clock
    ],
)
def test_is_open_at(now: time, opens: time, closes: time, expected: bool) -> None:
    assert is_open_at(now, opens, closes) is expected


def test_label() -> None:
    assert label(time(6), time(22)) == "06:00–22:00"


async def guest_headers(client: httpx.AsyncClient, db: AsyncSession, lang: str = "vi") -> dict:
    reception = staff_headers(
        await create_staff(db, email=f"rx-{lang}@h.test", role=StaffRole.RECEPTION)
    )
    room = await client.post("/api/v1/rooms", json={"number": f"9{lang}"}, headers=reception)
    issued = await client.post(
        "/api/v1/stays",
        json={
            "room_id": room.json()["id"],
            "expected_checkout_at": "2099-01-01T05:00:00Z",
            "room_charge_vnd": 1,
        },
        headers=reception,
    )
    login = await client.post(
        "/api/v1/guest/auth/room-code",
        json={**login_body(issued.json()["room_code"], f"device-{lang}-00001"), "lang": lang},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_guest_menu_in_vietnamese(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await create_menu(db)
    await kitchen_open_all_day(db)
    menu = (await client.get(GUEST_MENU, headers=await guest_headers(client, db))).json()

    assert menu["is_open_now"] is True
    assert menu["service_hours"] == "00:00–00:00"
    assert [c["code"] for c in menu["categories"]] == ["BREAKFAST", "DRINK"]
    names = {i["name"]: i for i in menu["items"]}
    assert set(names) == {"Phở bò", "Bánh mì", "Nước cam"}  # archived + hidden category excluded
    assert names["Bánh mì"]["available"] is False
    assert names["Nước cam"] == {
        "item_id": names["Nước cam"]["item_id"],
        "name": "Nước cam",
        "category": "DRINK",
        "price_vnd": 40000,
        "available": True,
        "description": "Cam tươi",
    }


async def test_guest_menu_in_english_with_filters(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await create_menu(db)
    headers = await guest_headers(client, db, "en")
    drinks = (await client.get(GUEST_MENU, params={"category": "drink"}, headers=headers)).json()
    assert [i["name"] for i in drinks["items"]] == ["Orange juice"]
    assert drinks["categories"] == [{"code": "DRINK", "name": "Drinks"}]

    # Search ignores Vietnamese accents.
    found = (await client.get(GUEST_MENU, params={"search": "pho bo"}, headers=headers)).json()
    assert [i["name"] for i in found["items"]] == ["Beef pho"]


async def test_menu_shows_closed_when_paused(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await create_menu(db)
    await kitchen_open_all_day(db, paused=True)
    menu = (await client.get(GUEST_MENU, headers=await guest_headers(client, db))).json()
    assert menu["is_open_now"] is False


async def test_guest_menu_needs_a_guest(client: httpx.AsyncClient, db: AsyncSession) -> None:
    assert (await client.get(GUEST_MENU)).status_code == 401
    kitchen = staff_headers(await create_staff(db, role=StaffRole.KITCHEN))
    assert (await client.get(GUEST_MENU, headers=kitchen)).status_code == 401


async def test_kitchen_manages_the_menu(client: httpx.AsyncClient, db: AsyncSession) -> None:
    kitchen = staff_headers(await create_staff(db, role=StaffRole.KITCHEN))
    category = await client.post(
        "/api/v1/menu/categories",
        json={"code": "main", "name_vi": "Món chính", "name_en": "Mains"},
        headers=kitchen,
    )
    assert category.status_code == 201 and category.json()["code"] == "MAIN"
    dup = await client.post(
        "/api/v1/menu/categories",
        json={"code": "MAIN", "name_vi": "x", "name_en": "x"},
        headers=kitchen,
    )
    assert dup.status_code == 409

    item = await client.post(
        "/api/v1/menu/items",
        json={
            "category_id": category.json()["id"],
            "name_vi": "Cơm rang",
            "name_en": "Fried rice",
            "price_vnd": 75000,
        },
        headers=kitchen,
    )
    assert item.status_code == 201
    item_id = item.json()["id"]

    sold_out = await client.post(
        f"/api/v1/menu/items/{item_id}/availability", json={"available": False}, headers=kitchen
    )
    assert sold_out.json()["available"] is False

    repriced = await client.patch(
        f"/api/v1/menu/items/{item_id}", json={"price_vnd": 80000}, headers=kitchen
    )
    assert repriced.json()["price_vnd"] == 80000

    archived = await client.patch(
        f"/api/v1/menu/items/{item_id}", json={"is_archived": True}, headers=kitchen
    )
    assert archived.json()["is_archived"] is True
    listed = (await client.get("/api/v1/menu/items", headers=kitchen)).json()
    assert item_id not in [i["id"] for i in listed]
    all_items = (
        await client.get("/api/v1/menu/items", params={"include_archived": "true"}, headers=kitchen)
    ).json()
    assert item_id in [i["id"] for i in all_items]


@pytest.mark.parametrize(
    "body",
    [{"price_vnd": -1}, {"name_vi": ""}, {"category_id": "00000000-0000-0000-0000-000000000000"}],
    ids=["negative-price", "empty-name", "unknown-category"],
)
async def test_bad_item_updates(client: httpx.AsyncClient, db: AsyncSession, body: dict) -> None:
    items = await create_menu(db)
    kitchen = staff_headers(await create_staff(db, role=StaffRole.KITCHEN))
    response = await client.patch(
        f"/api/v1/menu/items/{items['pho'].id}", json=body, headers=kitchen
    )
    assert response.status_code in (400, 404)


async def test_settings_roles(client: httpx.AsyncClient, db: AsyncSession) -> None:
    kitchen = staff_headers(await create_staff(db, email="k@h.test", role=StaffRole.KITCHEN))
    reception = staff_headers(await create_staff(db, email="r@h.test", role=StaffRole.RECEPTION))
    housekeeping = staff_headers(
        await create_staff(db, email="h@h.test", role=StaffRole.HOUSEKEEPING)
    )

    paused = await client.patch(
        "/api/v1/settings/room-service", json={"paused": True}, headers=kitchen
    )
    assert paused.json()["room_service_paused"] is True
    assert (
        await client.patch(
            "/api/v1/settings/room-service", json={"paused": False}, headers=reception
        )
    ).status_code == 403

    hours = {"open": "07:00", "close": "21:30", "default_prep_minutes": 30}
    assert (
        await client.patch("/api/v1/settings/room-service/hours", json=hours, headers=kitchen)
    ).status_code == 403
    updated = await client.patch(
        "/api/v1/settings/room-service/hours", json=hours, headers=reception
    )
    assert updated.json()["room_service_open"] == "07:00:00"
    assert updated.json()["default_prep_minutes"] == 30

    for path in ("/api/v1/settings/room-service", "/api/v1/menu/items", "/api/v1/menu/categories"):
        assert (await client.get(path, headers=housekeeping)).status_code == 403
    assert (
        await client.post(
            "/api/v1/menu/categories",
            json={"code": "X", "name_vi": "x", "name_en": "x"},
            headers=reception,
        )
    ).status_code == 403


@pytest.fixture
def bad_menu_csv(tmp_path: Path) -> Path:
    bad = tmp_path / "bad.csv"
    bad.write_text("category_code,name_vi,price_vnd\nMAIN,Cơm,abc\n", encoding="utf-8")
    return bad


SEED_MENU = Path(__file__).resolve().parents[3] / "seeds" / "menu.example.csv"


async def test_seed_menu_cli(db: AsyncSession, bad_menu_csv: Path) -> None:
    printed: list[str] = []
    for _ in range(2):
        args = ["seed-menu", "--from-file", str(SEED_MENU)]
        await cli.run(args, settings=make_settings(), out=printed.append)
    assert printed == [
        "dishes created: 7, already existed: 0",
        "dishes created: 0, already existed: 7",
    ]
    with pytest.raises(cli.CliError, match="price_vnd"):
        await cli.run(["seed-menu", "--from-file", str(bad_menu_csv)], settings=make_settings())


async def test_stay_fixture_is_usable(db: AsyncSession) -> None:
    assert (await create_stay(db)).status.value == "ACTIVE"
