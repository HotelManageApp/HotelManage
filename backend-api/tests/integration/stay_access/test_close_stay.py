"""Check-out, code re-issue, mark-vacant and the on-stay-closed hook (SPEC-stay-access SC 3, 4)."""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff_auth.models import StaffRole
from app.modules.stay_access import events
from app.modules.stay_access.codes import code_lookup
from app.modules.stay_access.models import (
    RevokeReason,
    Room,
    RoomStatus,
    Stay,
    StaySession,
    StayStatus,
)
from tests.conftest import TEST_ROOM_CODE_PEPPER
from tests.factories import checkout_in, create_room, create_staff, staff_headers


@pytest.fixture
async def reception(db: AsyncSession) -> dict[str, str]:
    return staff_headers(await create_staff(db, role=StaffRole.RECEPTION))


async def _check_in(client: httpx.AsyncClient, headers: dict[str, str], room: Room) -> dict:
    response = await client.post(
        "/api/v1/stays",
        json={
            "room_id": str(room.id),
            "expected_checkout_at": checkout_in(1),
            "room_charge_vnd": 500_000,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


async def _add_sessions(db: AsyncSession, stay_id: str, count: int = 2) -> None:
    for i in range(count):
        db.add(StaySession(stay_id=uuid.UUID(stay_id), device_id=f"device-{i}"))
    await db.commit()


async def _sessions(db: AsyncSession) -> list[tuple]:
    db.expire_all()
    rows = await db.execute(select(StaySession.revoked_at, StaySession.revoke_reason))
    return list(rows.all())


async def _state(db: AsyncSession, stay_id: str) -> tuple:
    db.expire_all()
    row = await db.execute(
        select(Stay.status, Stay.room_code_lookup, Room.status)
        .join(Room, Room.id == Stay.room_id)
        .where(Stay.id == uuid.UUID(stay_id))
    )
    return tuple(row.one())


async def test_checkout_closes_stay_revokes_sessions_and_frees_code(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    room = await create_room(db, "101")
    issued = await _check_in(client, reception, room)
    stay_id = issued["stay"]["id"]
    await _add_sessions(db, stay_id)

    response = await client.post(f"/api/v1/stays/{stay_id}/checkout", headers=reception)
    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"
    assert response.json()["closed_at"] is not None

    assert await _state(db, stay_id) == (StayStatus.CLOSED, None, RoomStatus.CLEANING)
    assert all(
        revoked is not None and reason == RevokeReason.CHECKOUT
        for revoked, reason in await _sessions(db)
    )

    again = await client.post(f"/api/v1/stays/{stay_id}/checkout", headers=reception)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "STAY_CLOSED"


async def test_reissue_replaces_code_and_signs_out_devices(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    room = await create_room(db, "101")
    issued = await _check_in(client, reception, room)
    stay_id = issued["stay"]["id"]
    old_raw = issued["room_code"].replace("-", "")
    await _add_sessions(db, stay_id)

    response = await client.post(f"/api/v1/stays/{stay_id}/reissue-code", headers=reception)
    assert response.status_code == 200
    new_raw = response.json()["room_code"].replace("-", "")
    assert new_raw != old_raw
    assert response.json()["qr_payload"].endswith(new_raw)

    status, lookup, room_status = await _state(db, stay_id)
    assert status == StayStatus.ACTIVE and room_status == RoomStatus.OCCUPIED
    assert lookup == code_lookup(new_raw, TEST_ROOM_CODE_PEPPER)
    assert all(reason == RevokeReason.REISSUE for _, reason in await _sessions(db))


async def test_reissue_of_closed_stay_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    stay_id = (await _check_in(client, reception, await create_room(db, "101")))["stay"]["id"]
    await client.post(f"/api/v1/stays/{stay_id}/checkout", headers=reception)
    response = await client.post(f"/api/v1/stays/{stay_id}/reissue-code", headers=reception)
    assert response.status_code == 409


async def test_mark_vacant_only_from_cleaning(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    room = await create_room(db, "101")
    room_id = str(room.id)
    stay_id = (await _check_in(client, reception, room))["stay"]["id"]

    occupied = await client.post(f"/api/v1/rooms/{room_id}/mark-vacant", headers=reception)
    assert occupied.status_code == 409

    await client.post(f"/api/v1/stays/{stay_id}/checkout", headers=reception)
    cleaned = await client.post(f"/api/v1/rooms/{room_id}/mark-vacant", headers=reception)
    assert cleaned.status_code == 200 and cleaned.json()["status"] == "VACANT"

    # The room can host a new stay.
    assert (await _check_in(client, reception, room))["stay"]["room_number"] == "101"


async def test_unknown_ids(client: httpx.AsyncClient, reception: dict[str, str]) -> None:
    unknown = uuid.uuid4()
    for path in (
        f"/api/v1/stays/{unknown}/checkout",
        f"/api/v1/stays/{unknown}/reissue-code",
        f"/api/v1/rooms/{unknown}/mark-vacant",
    ):
        assert (await client.post(path, headers=reception)).status_code == 404


@pytest.fixture
async def hook_calls() -> AsyncIterator[list[uuid.UUID]]:
    calls: list[uuid.UUID] = []

    async def record(db: AsyncSession, stay_id: uuid.UUID) -> None:
        # Runs inside the closing transaction: the stay is already CLOSED here.
        status = await db.scalar(select(Stay.status).where(Stay.id == stay_id))
        assert status == StayStatus.CLOSED
        calls.append(stay_id)

    events.register_on_stay_closed(record)
    events.register_on_stay_closed(record)  # registering twice is a no-op
    yield calls
    events.unregister_on_stay_closed(record)


async def test_hooks_run_once_inside_the_close(
    client: httpx.AsyncClient,
    db: AsyncSession,
    reception: dict[str, str],
    hook_calls: list[uuid.UUID],
) -> None:
    stay_id = (await _check_in(client, reception, await create_room(db, "101")))["stay"]["id"]
    await client.post(f"/api/v1/stays/{stay_id}/checkout", headers=reception)
    assert hook_calls == [uuid.UUID(stay_id)]


async def test_failing_hook_rolls_the_close_back(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
) -> None:
    async def broken(db: AsyncSession, stay_id: uuid.UUID) -> None:
        raise RuntimeError("downstream module failed")

    stay_id = (await _check_in(client, reception, await create_room(db, "101")))["stay"]["id"]
    await _add_sessions(db, stay_id, count=1)
    events.register_on_stay_closed(broken)
    try:
        response = await client.post(f"/api/v1/stays/{stay_id}/checkout", headers=reception)
    finally:
        events.unregister_on_stay_closed(broken)

    assert response.status_code == 500
    status, lookup, room_status = await _state(db, stay_id)
    assert (status, room_status) == (StayStatus.ACTIVE, RoomStatus.OCCUPIED)
    assert lookup is not None
    assert all(revoked is None for revoked, _ in await _sessions(db))


@pytest.mark.parametrize("role", [StaffRole.KITCHEN, StaffRole.HOUSEKEEPING])
async def test_only_reception(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str], role: StaffRole
) -> None:
    room = await create_room(db, "101")
    stay_id = (await _check_in(client, reception, room))["stay"]["id"]
    other = staff_headers(await create_staff(db, email=f"{role.value}@h.test", role=role))
    for path in (
        f"/api/v1/stays/{stay_id}/checkout",
        f"/api/v1/stays/{stay_id}/reissue-code",
        f"/api/v1/rooms/{room.id}/mark-vacant",
    ):
        assert (await client.post(path, headers=other)).status_code == 403
