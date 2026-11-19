"""Housekeeping staff API: claim, work, hand back, cancel, roles, overdue (SPEC-housekeeping)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.housekeeping.jobs import remind_overdue_requests
from app.modules.housekeeping.models import HousekeepingRequest
from app.modules.notifications.models import NotificationOutbox
from app.modules.staff_auth.models import StaffRole
from tests.factories import create_staff, staff_headers
from tests.guests import check_in_guest

STAFF = "/api/v1/housekeeping-requests"


@pytest.fixture
async def setup(client: httpx.AsyncClient, db: AsyncSession) -> dict:
    guest = await check_in_guest(client, db)
    created = await client.post(
        "/api/v1/guest/housekeeping-requests",
        json={"type": "AMENITY", "amenities": [{"code": "TOWEL", "quantity": 2}]},
        headers=guest.headers,
    )
    lan = await create_staff(
        db, email="lan@h.test", role=StaffRole.HOUSEKEEPING, full_name="Nguyen Thi Lan"
    )
    mai = await create_staff(
        db, email="mai@h.test", role=StaffRole.HOUSEKEEPING, full_name="Tran Thi Mai"
    )
    return {
        "guest": guest,
        "id": created.json()["id"],
        "lan": staff_headers(lan),
        "lan_id": str(lan.id),
        "mai": staff_headers(mai),
        "kitchen": staff_headers(await create_staff(db, email="k@h.test", role=StaffRole.KITCHEN)),
    }


async def _move(
    client: httpx.AsyncClient, setup: dict, who: str, to: str, version: int
) -> httpx.Response:
    return await client.post(
        f"{STAFF}/{setup['id']}/transition", json={"to": to, "version": version}, headers=setup[who]
    )


async def test_claim_work_finish(client: httpx.AsyncClient, db: AsyncSession, setup: dict) -> None:
    claimed = await _move(client, setup, "lan", "ASSIGNED", 0)
    assert claimed.status_code == 200
    body = claimed.json()
    assert body["assigned_to"] == setup["lan_id"]
    assert body["assignee_full_name"] == "Nguyen Thi Lan"
    assert body["room_number"] == "101" and body["guest_name"] is None

    guest_view = (
        await client.get(
            f"/api/v1/guest/housekeeping-requests/{setup['id']}", headers=setup["guest"].headers
        )
    ).json()
    assert guest_view["assignee"] == "Lan"  # given name only

    assert (await _move(client, setup, "mai", "IN_PROGRESS", 1)).status_code == 403  # not hers
    assert (await _move(client, setup, "lan", "IN_PROGRESS", 1)).status_code == 200
    done = await _move(client, setup, "lan", "DONE", 2)
    assert done.json()["status"] == "DONE"
    assert [h["to_status"] for h in done.json()["history"]] == [
        "REQUESTED",
        "ASSIGNED",
        "IN_PROGRESS",
        "DONE",
    ]
    assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == 3


async def test_two_people_claim_at_once(
    client: httpx.AsyncClient, db: AsyncSession, setup: dict
) -> None:
    results = await asyncio.gather(
        _move(client, setup, "lan", "ASSIGNED", 0), _move(client, setup, "mai", "ASSIGNED", 0)
    )
    assert sorted(r.status_code for r in results) == [200, 409]


async def test_hand_back(client: httpx.AsyncClient, db: AsyncSession, setup: dict) -> None:
    await _move(client, setup, "lan", "ASSIGNED", 0)
    assert (await _move(client, setup, "mai", "REQUESTED", 1)).status_code == 403
    back = await _move(client, setup, "lan", "REQUESTED", 1)
    assert back.status_code == 200
    assert back.json()["assigned_to"] is None and back.json()["status"] == "REQUESTED"
    assert (await _move(client, setup, "mai", "ASSIGNED", 2)).status_code == 200
    # Hand-back is internal: no push for it (assign x2 only).
    assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == 2


async def test_invalid_moves(client: httpx.AsyncClient, db: AsyncSession, setup: dict) -> None:
    response = await _move(client, setup, "lan", "DONE", 0)
    assert response.status_code == 409 and response.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_reception_cancels_with_reason(
    client: httpx.AsyncClient, db: AsyncSession, setup: dict
) -> None:
    reception = setup["guest"].reception
    url = f"{STAFF}/{setup['id']}/cancel"
    assert (
        await client.post(url, json={"version": 0, "reason": ""}, headers=reception)
    ).status_code == 400
    cancelled = await client.post(
        url, json={"version": 0, "reason": "Khách gọi lễ tân"}, headers=reception
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["guest_name"] == "Tran Thi B"
    assert cancelled.json()["cancel_reason"] == "Khách gọi lễ tân"


async def test_roles(client: httpx.AsyncClient, db: AsyncSession, setup: dict) -> None:
    reception = setup["guest"].reception
    one = f"{STAFF}/{setup['id']}"
    assert (
        await client.post(
            f"{one}/transition", json={"to": "ASSIGNED", "version": 0}, headers=reception
        )
    ).status_code == 403
    assert (
        await client.post(f"{one}/cancel", json={"version": 0, "reason": "x"}, headers=setup["lan"])
    ).status_code == 403
    for path in (STAFF, one):
        assert (await client.get(path, headers=setup["kitchen"])).status_code == 403
        assert (await client.get(path, headers=setup["guest"].headers)).status_code == 401


async def test_list_mine_and_do_not_disturb(
    client: httpx.AsyncClient, db: AsyncSession, setup: dict
) -> None:
    await client.put(
        "/api/v1/guest/me/do-not-disturb", json={"enabled": True}, headers=setup["guest"].headers
    )
    listed = (await client.get(STAFF, headers=setup["lan"])).json()
    assert [r["id"] for r in listed] == [setup["id"]]
    assert listed[0]["do_not_disturb"] is True
    assert (await client.get(STAFF, params={"mine": "true"}, headers=setup["lan"])).json() == []
    await _move(client, setup, "lan", "ASSIGNED", 0)
    assert len((await client.get(STAFF, params={"mine": "true"}, headers=setup["lan"])).json()) == 1
    assert (await client.get(STAFF, params={"type": "CLEANING"}, headers=setup["lan"])).json() == []


async def test_overdue_after_fifteen_minutes(db: AsyncSession, setup: dict) -> None:
    assert await remind_overdue_requests(db) == 0
    await db.execute(
        update(HousekeepingRequest)
        .where(HousekeepingRequest.id == uuid.UUID(setup["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(minutes=16))
    )
    await db.commit()
    assert await remind_overdue_requests(db) == 1
    assert await remind_overdue_requests(db) == 0


async def test_future_preferred_time_is_not_overdue(db: AsyncSession, setup: dict) -> None:
    await db.execute(
        update(HousekeepingRequest)
        .where(HousekeepingRequest.id == uuid.UUID(setup["id"]))
        .values(
            created_at=datetime.now(UTC) - timedelta(hours=2),
            preferred_time=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.commit()
    assert await remind_overdue_requests(db) == 0
