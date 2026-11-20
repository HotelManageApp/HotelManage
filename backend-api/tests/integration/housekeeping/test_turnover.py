"""TURNOVER after check-out, room back to VACANT, mark-vacant (SPEC-housekeeping SC 6)."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.housekeeping.models import HkStatus, HkType, HousekeepingRequest
from app.modules.notifications.models import NotificationOutbox
from app.modules.staff_auth.models import StaffRole
from app.modules.stay_access.models import Room, RoomStatus
from tests.factories import create_staff, staff_headers
from tests.guests import Guest, check_in_guest

GUEST = "/api/v1/guest/housekeeping-requests"
STAFF = "/api/v1/housekeeping-requests"


@pytest.fixture
async def guest(client: httpx.AsyncClient, db: AsyncSession) -> Guest:
    return await check_in_guest(client, db)


@pytest.fixture
async def housekeeper(db: AsyncSession) -> dict[str, str]:
    return staff_headers(await create_staff(db, email="hk@h.test", role=StaffRole.HOUSEKEEPING))


async def _requests(db: AsyncSession) -> list[HousekeepingRequest]:
    db.expire_all()
    return list(
        await db.scalars(select(HousekeepingRequest).order_by(HousekeepingRequest.created_at))
    )


async def _room_status(db: AsyncSession) -> RoomStatus:
    db.expire_all()
    status = await db.scalar(select(Room.status).where(Room.number == "101"))
    assert status is not None
    return status


async def _checkout(client: httpx.AsyncClient, guest: Guest) -> None:
    response = await client.post(f"/api/v1/stays/{guest.stay_id}/checkout", headers=guest.reception)
    assert response.status_code == 200, response.text


async def test_checkout_cancels_waiting_requests_and_opens_a_turnover(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest, housekeeper: dict
) -> None:
    waiting = (
        await client.post(
            GUEST,
            json={"type": "AMENITY", "amenities": [{"code": "WATER", "quantity": 1}]},
            headers=guest.headers,
        )
    ).json()
    claimed = (
        await client.post(
            GUEST,
            json={"type": "AMENITY", "amenities": [{"code": "TOWEL", "quantity": 1}]},
            headers=guest.headers,
        )
    ).json()
    working = (await client.post(GUEST, json={"type": "CLEANING"}, headers=guest.headers)).json()
    await client.post(
        f"{STAFF}/{claimed['id']}/transition",
        json={"to": "ASSIGNED", "version": 0},
        headers=housekeeper,
    )
    for version, to in enumerate(["ASSIGNED", "IN_PROGRESS"]):
        await client.post(
            f"{STAFF}/{working['id']}/transition",
            json={"to": to, "version": version},
            headers=housekeeper,
        )
    pushes_before = len(list(await db.scalars(select(NotificationOutbox.id))))

    await _checkout(client, guest)

    by_id = {str(r.id): r for r in await _requests(db)}
    assert by_id[waiting["id"]].status is HkStatus.CANCELLED
    assert by_id[claimed["id"]].status is HkStatus.CANCELLED
    assert by_id[waiting["id"]].cancel_reason == "STAY_CLOSED"
    assert by_id[working["id"]].status is HkStatus.IN_PROGRESS  # finished by the housekeeper
    turnovers = [r for r in by_id.values() if r.type is HkType.TURNOVER]
    assert len(turnovers) == 1
    assert turnovers[0].stay_id is None and turnovers[0].source == "SYSTEM"
    assert turnovers[0].status is HkStatus.REQUESTED
    assert await _room_status(db) is RoomStatus.CLEANING
    # Cancellations at check-out push nothing to the (leaving) guest.
    assert len(list(await db.scalars(select(NotificationOutbox.id)))) == pushes_before


async def test_finishing_the_turnover_frees_the_room(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest, housekeeper: dict
) -> None:
    await _checkout(client, guest)
    turnover = next(r for r in await _requests(db) if r.type is HkType.TURNOVER)
    for version, to in enumerate(["ASSIGNED", "IN_PROGRESS", "DONE"]):
        response = await client.post(
            f"{STAFF}/{turnover.id}/transition",
            json={"to": to, "version": version},
            headers=housekeeper,
        )
        assert response.status_code == 200, response.text
    assert await _room_status(db) is RoomStatus.VACANT

    queue = (await client.get(STAFF, headers=housekeeper)).json()
    assert queue[0]["type"] == "TURNOVER" and queue[0]["status"] == "DONE"


async def test_turnover_comes_first_and_guests_never_see_it(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest, housekeeper: dict
) -> None:
    other = await check_in_guest(client, db, room_number="202")
    await client.post(
        GUEST,
        json={"type": "AMENITY", "amenities": [{"code": "WATER", "quantity": 1}]},
        headers=other.headers,
    )
    await _checkout(client, guest)
    queue = (await client.get(STAFF, headers=housekeeper)).json()
    assert [r["type"] for r in queue][:2] == ["TURNOVER", "AMENITY"]
    turnover_id = queue[0]["id"]
    assert (await client.get(f"{GUEST}/{turnover_id}", headers=other.headers)).status_code == 404
    assert all(
        r["type"] != "TURNOVER" for r in (await client.get(GUEST, headers=other.headers)).json()
    )


async def test_marking_vacant_cancels_the_turnover(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    await _checkout(client, guest)
    room_id = await db.scalar(select(Room.id).where(Room.number == "101"))
    response = await client.post(f"/api/v1/rooms/{room_id}/mark-vacant", headers=guest.reception)
    assert response.status_code == 200
    turnover = next(r for r in await _requests(db) if r.type is HkType.TURNOVER)
    assert turnover.status is HkStatus.CANCELLED
    assert turnover.cancel_reason == "MARKED_VACANT_BY_RECEPTION"


async def test_one_open_turnover_per_room(client: httpx.AsyncClient, db: AsyncSession) -> None:
    first = await check_in_guest(client, db)
    await _checkout(client, first)
    room_id = await db.scalar(select(Room.id).where(Room.number == "101"))
    room = await db.get(Room, room_id)
    assert room is not None
    room.status = RoomStatus.VACANT  # skip cleaning on purpose: the turnover stays open
    await db.commit()

    second_issue = await client.post(
        "/api/v1/stays",
        json={
            "room_id": str(room_id),
            "expected_checkout_at": "2099-01-01T05:00:00Z",
            "room_charge_vnd": 1,
        },
        headers=first.reception,
    )
    await client.post(
        f"/api/v1/stays/{second_issue.json()['stay']['id']}/checkout", headers=first.reception
    )
    assert len([r for r in await _requests(db) if r.type is HkType.TURNOVER]) == 1
