"""Concierge chat history, message quota and hotel info (SPEC-concierge-guide, T38)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import RateLimitBucket
from app.modules.concierge_data.models import ChatMessage
from app.modules.staff_auth.models import StaffRole
from tests.factories import create_staff, staff_headers
from tests.guests import Guest, check_in_guest

MESSAGES = "/api/v1/guest/chat/messages"
QUOTA = "/api/v1/guest/chat/quota"


@pytest.fixture
async def guest(client: httpx.AsyncClient, db: AsyncSession) -> Guest:
    return await check_in_guest(client, db)


def exchange(n: int = 1, **extra: object) -> dict:
    return {
        "guest_message": f"Câu hỏi {n}",
        "assistant_message": f"Trả lời {n}",
        "tool_trace": {"tool": "get_hotel_info_and_guide", "args": {"topic": "BREAKFAST"}},
        "grounded": True,
        **extra,
    }


async def _count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(ChatMessage)) or 0


# ---------- history ----------


async def test_saves_pairs_and_lists_them_oldest_first(
    client: httpx.AsyncClient, guest: Guest
) -> None:
    for n in (1, 2, 3):
        saved = await client.post(MESSAGES, json=exchange(n), headers=guest.headers)
        assert saved.status_code == 201, saved.text
        assert set(saved.json()) == {"message_id", "guest_message_id"}

    lines = (await client.get(MESSAGES, headers=guest.headers)).json()
    assert [(m["role"], m["content"]) for m in lines] == [
        ("GUEST", "Câu hỏi 1"),
        ("ASSISTANT", "Trả lời 1"),
        ("GUEST", "Câu hỏi 2"),
        ("ASSISTANT", "Trả lời 2"),
        ("GUEST", "Câu hỏi 3"),
        ("ASSISTANT", "Trả lời 3"),
    ]
    assert set(lines[0]) == {"id", "role", "content", "created_at"}, "no tool trace for the app"

    last_two = (await client.get(MESSAGES, params={"limit": 2}, headers=guest.headers)).json()
    assert [m["content"] for m in last_two] == ["Câu hỏi 3", "Trả lời 3"]
    older = (
        await client.get(
            MESSAGES,
            params={"limit": 2, "before": last_two[0]["created_at"]},
            headers=guest.headers,
        )
    ).json()
    assert [m["content"] for m in older] == ["Câu hỏi 2", "Trả lời 2"]


async def test_a_retried_send_is_stored_once(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    body = exchange(client_message_id=str(uuid.uuid4()))
    first = await client.post(MESSAGES, json=body, headers=guest.headers)
    again = await client.post(MESSAGES, json=body, headers=guest.headers)
    assert first.json() == again.json()
    assert await _count(db) == 2

    racing = exchange(2, client_message_id=str(uuid.uuid4()))
    results = await asyncio.gather(
        *[client.post(MESSAGES, json=racing, headers=guest.headers) for _ in range(5)]
    )
    assert {r.status_code for r in results} == {201}
    assert len({r.json()["message_id"] for r in results}) == 1
    assert await _count(db) == 4


async def test_devices_of_a_stay_share_the_history_and_other_stays_do_not_see_it(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    reception = staff_headers(await create_staff(db, role=StaffRole.RECEPTION))
    room = await client.post("/api/v1/rooms", json={"number": "301"}, headers=reception)
    stay = await client.post(
        "/api/v1/stays",
        json={
            "room_id": room.json()["id"],
            "expected_checkout_at": "2099-01-01T05:00:00Z",
            "room_charge_vnd": 0,
        },
        headers=reception,
    )
    code = stay.json()["room_code"]

    async def device(name: str) -> dict:
        login = await client.post(
            "/api/v1/guest/auth/room-code",
            json={"code": code, "device_id": f"device-{name}-0001", "lang": "vi"},
        )
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    phone, tablet = await device("phone"), await device("tablet")
    await client.post(MESSAGES, json=exchange(), headers=phone)
    shared = (await client.get(MESSAGES, headers=tablet)).json()
    assert [m["content"] for m in shared] == ["Câu hỏi 1", "Trả lời 1"]

    other = await check_in_guest(client, db, room_number="302")
    assert (await client.get(MESSAGES, headers=other.headers)).json() == []


@pytest.mark.parametrize(
    "body",
    [
        exchange(tool_trace={"tool": "x", "args": {"token": "eyJ..."}}),
        exchange(tool_trace=[{"headers": {"Authorization": "Bearer x"}}]),
        exchange(tool_trace={"room_id": "101"}),
        exchange(tool_trace={"blob": "x" * 17_000}),
        exchange(room_id=str(uuid.uuid4())),  # unknown fields are refused
        exchange(guest_message=""),
        exchange(guest_message="x" * 1001),
        exchange(assistant_message="x" * 4001),
    ],
)
async def test_bad_exchanges_are_400(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest, body: dict
) -> None:
    assert (await client.post(MESSAGES, json=body, headers=guest.headers)).status_code == 400
    assert await _count(db) == 0


async def test_chat_needs_a_guest_token(client: httpx.AsyncClient, db: AsyncSession) -> None:
    staff = staff_headers(await create_staff(db, role=StaffRole.RECEPTION))
    for headers in ({}, staff):
        assert (await client.get(MESSAGES, headers=headers)).status_code == 401
        assert (await client.post(MESSAGES, json=exchange(), headers=headers)).status_code == 401
        assert (await client.post(QUOTA, headers=headers)).status_code == 401
        assert (await client.get("/api/v1/guest/hotel-info", headers=headers)).status_code == 401


# ---------- quota ----------


async def test_ten_messages_a_minute_per_device(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    for left in range(9, -1, -1):
        ok = await client.post(QUOTA, headers=guest.headers)
        assert ok.status_code == 200
        assert ok.json() == {"remaining_minute": left, "remaining_day": 90 + left}
    refused = await client.post(QUOTA, headers=guest.headers)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= int(refused.headers["Retry-After"]) <= 61

    day = await db.scalar(
        select(RateLimitBucket.count).where(RateLimitBucket.key == f"chat:stay:{guest.stay_id}")
    )
    assert day == 10, "a refused attempt does not use up the day"


async def test_a_new_minute_opens_again(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    for _ in range(10):
        await client.post(QUOTA, headers=guest.headers)
    # Move the minute window into the past, as if a minute went by.
    bucket = await db.scalar(
        select(RateLimitBucket).where(RateLimitBucket.key.like("chat:session:%"))
    )
    assert bucket is not None
    bucket.window_start = datetime.now(UTC) - timedelta(seconds=61)
    await db.commit()
    assert (await client.post(QUOTA, headers=guest.headers)).status_code == 200


async def test_a_hundred_messages_a_day_per_stay(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    db.add(
        RateLimitBucket(
            key=f"chat:stay:{guest.stay_id}",
            window_start=datetime.now(UTC) - timedelta(hours=1),
            count=100,
        )
    )
    await db.commit()
    refused = await client.post(QUOTA, headers=guest.headers)
    assert refused.status_code == 429
    # About 23 hours until the day window opens again.
    assert 22 * 3600 < int(refused.headers["Retry-After"]) <= 23 * 3600 + 1


# ---------- hotel info ----------


async def test_hotel_info_for_the_guest(client: httpx.AsyncClient, guest: Guest) -> None:
    await client.patch(
        "/api/v1/settings/hotel",
        json={"hotel_name": "Khách sạn Hoa Sen", "reception_phone": "028 3822 1234"},
        headers=guest.reception,
    )
    info = await client.get("/api/v1/guest/hotel-info", headers=guest.headers)
    assert info.json() == {
        "hotel_name": "Khách sạn Hoa Sen",
        "reception_phone": "028 3822 1234",
        "default_lang": "vi",
        "chat_enabled": True,
    }


# ---------- end of stay ----------


async def test_check_out_deletes_the_chat_and_ends_access(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    other = await check_in_guest(client, db, room_number="202")
    await client.post(MESSAGES, json=exchange(), headers=guest.headers)
    await client.post(MESSAGES, json=exchange(), headers=other.headers)

    out = await client.post(f"/api/v1/stays/{guest.stay_id}/checkout", headers=guest.reception)
    assert out.status_code == 200, out.text
    db.expire_all()
    remaining = list(await db.scalars(select(ChatMessage.stay_id)))
    assert remaining == [uuid.UUID(other.stay_id), uuid.UUID(other.stay_id)]
    assert (await client.get(MESSAGES, headers=guest.headers)).status_code == 401
    assert (await client.post(QUOTA, headers=guest.headers)).status_code == 401


async def test_a_send_racing_its_retry_returns_the_stored_pair(
    client: httpx.AsyncClient,
    db: AsyncSession,
    guest: Guest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry passed the "already stored?" check before the first send committed: the insert
    hits the unique constraint and the stored pair is returned instead of a 500."""
    from app.modules.concierge_data import chat

    body = exchange(client_message_id=str(uuid.uuid4()))
    first = (await client.post(MESSAGES, json=body, headers=guest.headers)).json()

    real_pair = chat._pair
    calls = {"n": 0}

    async def miss_once(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real_pair(*args, **kwargs)

    monkeypatch.setattr(chat, "_pair", miss_once)
    again = await client.post(MESSAGES, json=body, headers=guest.headers)
    assert again.status_code == 201
    assert again.json() == first
    assert await _count(db) == 2
