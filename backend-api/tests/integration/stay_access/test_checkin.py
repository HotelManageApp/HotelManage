"""Rooms and check-in (SPEC-stay-access success criteria 1, 7; C3 RBAC)."""

import asyncio
import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.modules.staff_auth.models import StaffRole
from app.modules.stay_access.codes import code_lookup
from app.modules.stay_access.models import Room, RoomStatus, Stay, StayStatus
from tests.conftest import TEST_ROOM_CODE_PEPPER
from tests.factories import checkout_in, create_room, create_staff, new_id, staff_headers

CODE_FORMAT = re.compile(r"[ABCDEFGHJKMNPQRSTUVWXYZ2-9]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ2-9]{4}")


@pytest.fixture
async def reception(db: AsyncSession) -> dict[str, str]:
    return staff_headers(await create_staff(db, role=StaffRole.RECEPTION))


def checkin_body(room: Room, **overrides: object) -> dict:
    body = {
        "room_id": str(room.id),
        "guest_name": "Tran Thi B",
        "guest_count": 2,
        "expected_checkout_at": checkout_in(2),
        "room_charge_vnd": 1_200_000,
    }
    body.update(overrides)
    return body


async def test_check_in_issues_code_once_and_occupies_room(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    room = await create_room(db, "101")
    room_id = room.id  # captured before expire_all() below
    response = await client.post("/api/v1/stays", json=checkin_body(room), headers=reception)

    assert response.status_code == 201
    body = response.json()
    assert CODE_FORMAT.fullmatch(body["room_code"])
    raw = body["room_code"].replace("-", "")
    assert body["qr_payload"] == f"hotelapp://login?code={raw}"
    assert body["stay"]["room_number"] == "101"
    assert body["stay"]["status"] == "ACTIVE"

    db.expire_all()
    stay = await db.scalar(select(Stay))
    assert stay is not None
    assert stay.room_code_lookup == code_lookup(raw, TEST_ROOM_CODE_PEPPER)
    assert raw not in (stay.room_code_lookup or "")
    room_status = await db.scalar(select(Room.status).where(Room.id == room_id))
    assert room_status == RoomStatus.OCCUPIED

    # The code is never shown again.
    for path in ("/api/v1/stays", f"/api/v1/stays/{stay.id}", "/api/v1/rooms"):
        listing = await client.get(path, headers=reception)
        assert listing.status_code == 200
        assert raw not in listing.text and body["room_code"] not in listing.text
        assert "room_code" not in listing.text


async def test_cannot_check_in_an_occupied_room(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    room = await create_room(db, "101")
    assert (
        await client.post("/api/v1/stays", json=checkin_body(room), headers=reception)
    ).status_code == 201
    second = await client.post("/api/v1/stays", json=checkin_body(room), headers=reception)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ROOM_NOT_VACANT"


@pytest.mark.parametrize("status", [RoomStatus.CLEANING, RoomStatus.OCCUPIED])
async def test_cannot_check_in_unless_vacant(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str], status: RoomStatus
) -> None:
    room = await create_room(db, "101", status=status)
    response = await client.post("/api/v1/stays", json=checkin_body(room), headers=reception)
    assert response.status_code == 409


async def test_concurrent_check_ins_of_one_room(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    room = await create_room(db, "101")
    results = await asyncio.gather(
        *(
            client.post("/api/v1/stays", json=checkin_body(room), headers=reception)
            for _ in range(3)
        )
    )
    assert sorted(r.status_code for r in results) == [201, 409, 409]
    db.expire_all()
    assert len(list(await db.scalars(select(Stay)))) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_checkout_at": "2020-01-01T10:00:00+07:00"},
        {"expected_checkout_at": "2030-01-01T10:00:00"},  # naive datetime
        {"room_charge_vnd": -1},
        {"guest_count": 0},
        {"room_code_lookup": "x"},  # unknown field
    ],
    ids=["past", "naive", "negative-charge", "zero-guests", "extra-field"],
)
async def test_check_in_validation(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str], overrides: dict
) -> None:
    room = await create_room(db, "101")
    response = await client.post(
        "/api/v1/stays", json=checkin_body(room, **overrides), headers=reception
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_unknown_or_inactive_room(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    body = checkin_body(await create_room(db, "101"))
    body["room_id"] = new_id()
    assert (await client.post("/api/v1/stays", json=body, headers=reception)).status_code == 404
    inactive = await create_room(db, "999", is_active=False)
    response = await client.post("/api/v1/stays", json=checkin_body(inactive), headers=reception)
    assert response.status_code == 404


async def test_rooms_crud_and_board(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/rooms", json={"number": "301", "floor": 3, "room_type": "Suite"}, headers=reception
    )
    assert created.status_code == 201
    duplicate = await client.post("/api/v1/rooms", json={"number": "301"}, headers=reception)
    assert duplicate.status_code == 409

    room_id = created.json()["id"]
    patched = await client.patch(
        f"/api/v1/rooms/{room_id}", json={"room_type": "Grand Suite"}, headers=reception
    )
    assert patched.json()["room_type"] == "Grand Suite"

    await client.post("/api/v1/stays", json={**checkin_body(Room(id=room_id))}, headers=reception)
    board = (await client.get("/api/v1/rooms", headers=reception)).json()
    assert board[0]["number"] == "301"
    assert board[0]["status"] == "OCCUPIED"
    assert board[0]["open_stay"]["guest_name"] == "Tran Thi B"

    deactivate = await client.patch(
        f"/api/v1/rooms/{room_id}", json={"is_active": False}, headers=reception
    )
    assert deactivate.status_code == 409  # occupied rooms cannot be taken out of service


async def test_update_stay(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    room = await create_room(db, "101")
    stay_id = (
        await client.post("/api/v1/stays", json=checkin_body(room), headers=reception)
    ).json()["stay"]["id"]
    later = checkout_in(4)
    response = await client.patch(
        f"/api/v1/stays/{stay_id}",
        json={"expected_checkout_at": later, "room_charge_vnd": 2_000_000, "note": "late"},
        headers=reception,
    )
    assert response.status_code == 200
    assert response.json()["room_charge_vnd"] == 2_000_000
    assert response.json()["note"] == "late"

    stay = await db.get(Stay, stay_id)
    assert stay is not None
    stay.status = StayStatus.CLOSED
    await db.commit()
    closed = await client.patch(f"/api/v1/stays/{stay_id}", json={"note": "x"}, headers=reception)
    assert closed.status_code == 409


@pytest.mark.parametrize("role", [StaffRole.KITCHEN, StaffRole.HOUSEKEEPING])
async def test_other_roles_are_forbidden(
    client: httpx.AsyncClient, db: AsyncSession, role: StaffRole
) -> None:
    room = await create_room(db, "101")
    headers = staff_headers(await create_staff(db, email=f"{role.value}@h.test", role=role))
    calls = [
        client.get("/api/v1/rooms", headers=headers),
        client.post("/api/v1/rooms", json={"number": "9"}, headers=headers),
        client.post("/api/v1/stays", json=checkin_body(room), headers=headers),
        client.get("/api/v1/stays", headers=headers),
    ]
    assert [r.status_code for r in await asyncio.gather(*calls)] == [403, 403, 403, 403]


async def test_seed_rooms_cli(db: AsyncSession, tmp_path: Path) -> None:
    csv_file = tmp_path / "rooms.csv"
    csv_file.write_text("number,floor,room_type\n101,1,Double\n102,,Twin\n", encoding="utf-8")
    printed: list[str] = []
    from tests.conftest import make_settings

    await cli.run(
        ["seed-rooms", "--from-file", str(csv_file)], settings=make_settings(), out=printed.append
    )
    await cli.run(
        ["seed-rooms", "--from-file", str(csv_file)], settings=make_settings(), out=printed.append
    )
    assert printed == [
        "rooms created: 2, already existed: 0",
        "rooms created: 0, already existed: 2",
    ]

    bad = tmp_path / "bad.csv"
    bad.write_text("number,floor\n101,first\n", encoding="utf-8")
    with pytest.raises(cli.CliError, match="floor must be a number"):
        await cli.run(["seed-rooms", "--from-file", str(bad)], settings=make_settings())
