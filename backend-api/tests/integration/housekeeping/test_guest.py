"""Guest housekeeping requests and do-not-disturb (SPEC-housekeeping, "Tạo yêu cầu")."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.housekeeping.models import HousekeepingRequest
from app.modules.stay_access.models import Stay, StayStatus
from tests.guests import Guest, check_in_guest

REQUESTS = "/api/v1/guest/housekeeping-requests"
DND = "/api/v1/guest/me/do-not-disturb"


@pytest.fixture
async def guest(client: httpx.AsyncClient, db: AsyncSession) -> Guest:
    return await check_in_guest(client, db)


def amenities(*pairs: tuple[str, int]) -> list[dict]:
    return [{"code": code, "quantity": qty} for code, qty in pairs]


async def _dnd(db: AsyncSession, stay_id: str) -> bool:
    db.expire_all()
    return bool(await db.scalar(select(Stay.do_not_disturb).where(Stay.id == uuid.UUID(stay_id))))


async def test_cleaning_request(client: httpx.AsyncClient, db: AsyncSession, guest: Guest) -> None:
    response = await client.post(
        REQUESTS, json={"type": "CLEANING", "note": "Thay ga"}, headers=guest.headers
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["type"], body["status"], body["preferred_time"], body["note"]) == (
        "CLEANING",
        "REQUESTED",
        None,
        "Thay ga",
    )
    assert body["amenities"] == [] and body["assignee"] is None

    db.expire_all()
    stored = await db.scalar(select(HousekeepingRequest))
    assert stored is not None and str(stored.stay_id) == guest.stay_id


async def test_amenity_request(client: httpx.AsyncClient, db: AsyncSession, guest: Guest) -> None:
    body = {"type": "AMENITY", "amenities": amenities(("TOWEL", 2), ("WATER", 4))}
    response = await client.post(REQUESTS, json=body, headers=guest.headers)
    assert response.status_code == 201
    assert response.json()["amenities"] == amenities(("TOWEL", 2), ("WATER", 4))


async def test_preferred_time(client: httpx.AsyncClient, db: AsyncSession, guest: Guest) -> None:
    in_two_hours = (datetime.now(UTC) + timedelta(hours=2)).replace(microsecond=0)
    ok = await client.post(
        REQUESTS,
        json={"type": "CLEANING", "preferred_time": in_two_hours.isoformat()},
        headers=guest.headers,
    )
    assert ok.status_code == 201
    assert datetime.fromisoformat(ok.json()["preferred_time"]) == in_two_hours


@pytest.mark.parametrize(
    "body",
    [
        {"type": "TURNOVER"},
        {"type": "AMENITY"},
        {"type": "CLEANING", "amenities": amenities(("TOWEL", 1))},
        {"type": "AMENITY", "amenities": amenities(("OTHER", 1))},
        {"type": "AMENITY", "amenities": amenities(("TOWEL", 6))},
        {"type": "CLEANING", "room_id": str(uuid.uuid4())},
        {"type": "CLEANING", "assigned_to": str(uuid.uuid4())},
        {"type": "CLEANING", "preferred_time": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
        {
            "type": "CLEANING",
            "preferred_time": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
        {"type": "CLEANING", "preferred_time": "2030-01-01T10:00:00"},
    ],
    ids=[
        "turnover",
        "amenity-without-items",
        "cleaning-with-items",
        "other-without-note",
        "too-many",
        "room_id",
        "assigned_to",
        "after-24h",
        "in-the-past",
        "naive-time",
    ],
)
async def test_invalid_requests(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest, body: dict
) -> None:
    response = await client.post(REQUESTS, json=body, headers=guest.headers)
    assert response.status_code == 400, response.text


async def test_other_with_a_note_is_fine(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    body = {"type": "AMENITY", "amenities": amenities(("OTHER", 1)), "note": "Bàn chải đánh răng"}
    assert (await client.post(REQUESTS, json=body, headers=guest.headers)).status_code == 201


async def test_one_open_cleaning_at_a_time(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    first = await client.post(REQUESTS, json={"type": "CLEANING"}, headers=guest.headers)
    second = await client.post(REQUESTS, json={"type": "CLEANING"}, headers=guest.headers)
    assert second.status_code == 409
    assert second.json()["error"]["details"] == [{"existing_request_id": first.json()["id"]}]

    # Two phones of another room asking at the same moment: the unique index lets one through.
    other = await check_in_guest(client, db, room_number="202")
    racing = await asyncio.gather(
        *(client.post(REQUESTS, json={"type": "CLEANING"}, headers=other.headers) for _ in range(3))
    )
    assert sorted(r.status_code for r in racing) == [201, 409, 409]


async def test_at_most_three_open_amenity_requests(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    body = {"type": "AMENITY", "amenities": amenities(("WATER", 1))}
    for _ in range(3):
        assert (await client.post(REQUESTS, json=body, headers=guest.headers)).status_code == 201
    fourth = await client.post(REQUESTS, json=body, headers=guest.headers)
    assert fourth.json()["error"]["code"] == "TOO_MANY_OPEN_REQUESTS"


async def test_checkout_pending_cannot_ask(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    await db.execute(
        update(Stay)
        .where(Stay.id == uuid.UUID(guest.stay_id))
        .values(status=StayStatus.CHECKOUT_PENDING)
    )
    await db.commit()
    response = await client.post(REQUESTS, json={"type": "CLEANING"}, headers=guest.headers)
    assert response.json()["error"]["code"] == "STAY_CHECKOUT_PENDING"
    assert (await client.put(DND, json={"enabled": True}, headers=guest.headers)).status_code == 409


async def test_idempotency(client: httpx.AsyncClient, db: AsyncSession, guest: Guest) -> None:
    headers = {**guest.headers, "Idempotency-Key": "hk-tap-000001"}
    body = {"type": "AMENITY", "amenities": amenities(("TOWEL", 1))}
    results = await asyncio.gather(
        *(client.post(REQUESTS, json=body, headers=headers) for _ in range(4))
    )
    assert len({r.json()["id"] for r in results}) == 1
    db.expire_all()
    assert len(list(await db.scalars(select(HousekeepingRequest.id)))) == 1


async def test_do_not_disturb_and_cleaning_turns_it_off(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    assert (await client.put(DND, json={"enabled": True}, headers=guest.headers)).status_code == 204
    assert await _dnd(db, guest.stay_id) is True
    await client.post(REQUESTS, json={"type": "CLEANING"}, headers=guest.headers)
    assert await _dnd(db, guest.stay_id) is False
    assert (
        await client.put(DND, json={"enabled": "yes please"}, headers=guest.headers)
    ).status_code == 400


async def test_list_detail_cancel_and_other_stays(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    other = await check_in_guest(client, db, room_number="202")
    created = (await client.post(REQUESTS, json={"type": "CLEANING"}, headers=guest.headers)).json()
    rid = created["id"]

    assert [r["id"] for r in (await client.get(REQUESTS, headers=guest.headers)).json()] == [rid]
    assert (await client.get(REQUESTS, headers=other.headers)).json() == []
    assert (await client.get(f"{REQUESTS}/{rid}", headers=other.headers)).status_code == 403
    assert (await client.post(f"{REQUESTS}/{rid}/cancel", headers=other.headers)).status_code == 403
    assert (
        await client.get(f"{REQUESTS}/{uuid.uuid4()}", headers=guest.headers)
    ).status_code == 404

    detail = (await client.get(f"{REQUESTS}/{rid}", headers=guest.headers)).json()
    assert [h["to_status"] for h in detail["history"]] == ["REQUESTED"]

    cancelled = await client.post(f"{REQUESTS}/{rid}/cancel", headers=guest.headers)
    assert cancelled.json()["status"] == "CANCELLED"
    again = await client.post(f"{REQUESTS}/{rid}/cancel", headers=guest.headers)
    assert again.json()["error"]["code"] == "INVALID_TRANSITION"
    # A new cleaning request is possible once the previous one is closed.
    assert (
        await client.post(REQUESTS, json={"type": "CLEANING"}, headers=guest.headers)
    ).status_code == 201
