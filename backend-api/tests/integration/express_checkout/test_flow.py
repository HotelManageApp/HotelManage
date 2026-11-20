"""Express checkout end to end (SPEC-express-checkout "Testing Strategy", T45)."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.concierge_data.models import ChatMessage
from app.modules.express_checkout.jobs import remind_overdue_requests
from app.modules.express_checkout.models import CheckoutRequest, CheckoutStatus
from app.modules.housekeeping.models import HkStatus, HkType, HousekeepingRequest
from app.modules.notifications.models import NotificationOutbox
from app.modules.room_service.models import MenuItem, OrderStatus
from app.modules.staff_auth.models import StaffRole
from app.modules.stay_access.models import Room, RoomStatus, Stay, StayStatus
from tests.factories import (
    add_food_order,
    create_menu,
    create_staff,
    kitchen_open_all_day,
    staff_headers,
)

GUEST = "/api/v1/guest"
REQUESTS = "/api/v1/checkout-requests"


@dataclass
class Stayer:
    stay_id: str
    code: str
    phone: dict[str, str]
    tablet: dict[str, str]


@pytest.fixture
async def reception(db: AsyncSession) -> dict[str, str]:
    return staff_headers(await create_staff(db, email="rx@h.test", role=StaffRole.RECEPTION))


async def check_in(
    client: httpx.AsyncClient, reception: dict[str, str], number: str = "101"
) -> Stayer:
    room = await client.post("/api/v1/rooms", json={"number": number}, headers=reception)
    issued = await client.post(
        "/api/v1/stays",
        json={
            "room_id": room.json()["id"],
            "guest_name": "Tran Thi B",
            "expected_checkout_at": "2099-01-01T05:00:00Z",
            "room_charge_vnd": 1_200_000,
        },
        headers=reception,
    )
    code = issued.json()["room_code"]

    async def device(name: str) -> dict[str, str]:
        login = await client.post(
            "/api/v1/guest/auth/room-code",
            json={"code": code, "device_id": f"device-{number}-{name}", "lang": "vi"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        await client.put(
            f"{GUEST}/me/fcm-token",
            json={"fcm_token": f"fid-{number}-{name}-0123456789abcdef"},
            headers=headers,
        )
        return headers

    return Stayer(issued.json()["stay"]["id"], code, await device("phone"), await device("tablet"))


@pytest.fixture
async def guest(client: httpx.AsyncClient, reception: dict[str, str]) -> Stayer:
    return await check_in(client, reception)


async def ask(client: httpx.AsyncClient, guest: Stayer, **extra: object) -> httpx.Response:
    return await client.post(
        f"{GUEST}/checkout-requests",
        json={"guest_confirmed": True, "feedback_rating": 5, **extra},
        headers=guest.phone,
    )


async def stay_of(db: AsyncSession, guest: Stayer) -> Stay:
    # Refresh just this row: expire_all() would also expire the menu items a test holds.
    stay = await db.get(Stay, uuid.UUID(guest.stay_id))
    assert stay is not None
    await db.refresh(stay)
    return stay


async def outbox(db: AsyncSession) -> list[tuple[str, str]]:
    rows = await db.scalars(
        select(NotificationOutbox)
        .order_by(NotificationOutbox.created_at)
        .execution_options(populate_existing=True)
    )
    return [(r.entity_type, r.status) for r in rows]


# ---------- the guest asks ----------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"guest_confirmed": False},
        {"guest_confirmed": True, "room_id": str(uuid.uuid4())},
        {"guest_confirmed": True, "total_vnd": 0},
        {"guest_confirmed": True, "feedback_rating": 6},
        {"guest_confirmed": True, "feedback_note": "x" * 501},
        {"guest_confirmed": True, "source": "EMAIL"},
    ],
)
async def test_bad_requests_are_400(client: httpx.AsyncClient, guest: Stayer, body: dict) -> None:
    response = await client.post(f"{GUEST}/checkout-requests", json=body, headers=guest.phone)
    assert response.status_code == 400


async def test_asking_pauses_the_stay(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer
) -> None:
    await kitchen_open_all_day(db)
    menu = await create_menu(db)
    preview = (await client.get(f"{GUEST}/checkout/preview", headers=guest.phone)).json()
    assert preview["is_estimate"] is True
    assert preview["total_vnd"] == 1_200_000
    assert "guest_name" not in preview and "stay" not in preview

    created = await ask(client, guest, feedback_note="Phòng sạch")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "CHECKOUT_REQUESTED"
    assert body["open_orders"] == 0
    assert body["message_key"] == "checkout.awaiting_reception"
    assert (await stay_of(db, guest)).status is StayStatus.CHECKOUT_PENDING

    order = await client.post(
        f"{GUEST}/orders",
        json={"items": [{"item_id": str(menu["pho"].id), "quantity": 1}]},
        headers=guest.tablet,
    )
    cleaning = await client.post(
        f"{GUEST}/housekeeping-requests", json={"type": "CLEANING"}, headers=guest.tablet
    )
    again = await ask(client, guest)
    for refused in (order, cleaning, again):
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "STAY_CHECKOUT_PENDING"
    assert await outbox(db) == [], "no push for the guest's own request"

    current = (await client.get(f"{GUEST}/checkout-requests/current", headers=guest.tablet)).json()
    assert current["status"] == "CHECKOUT_REQUESTED"
    assert current["bill"] is None
    assert current["feedback_rating"] == 5


async def test_current_is_404_before_any_request(client: httpx.AsyncClient, guest: Stayer) -> None:
    response = await client.get(f"{GUEST}/checkout-requests/current", headers=guest.phone)
    assert response.status_code == 404


async def test_open_orders_are_reported_when_asking(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer
) -> None:
    menu = await create_menu(db)
    await add_food_order(db, await stay_of(db, guest), OrderStatus.DELIVERING, [(menu["pho"], 1)])
    assert (await ask(client, guest)).json()["open_orders"] == 1


# ---------- reception verifies ----------


async def test_verify_needs_no_open_orders_then_freezes_the_bill(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer, reception: dict
) -> None:
    menu = await create_menu(db)
    stay = await stay_of(db, guest)
    await add_food_order(db, stay, OrderStatus.COMPLETED, [(menu["pho"], 2)])
    delivering = await add_food_order(db, stay, OrderStatus.DELIVERING, [(menu["cam"], 1)])
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    await client.post(
        f"/api/v1/stays/{guest.stay_id}/charges",
        json={"kind": "EXTRA", "description": "Minibar", "amount_vnd": 60000},
        headers=reception,
    )

    blocked = await client.post(
        f"{REQUESTS}/{request_id}/verify", json={"version": 0}, headers=reception
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "OPEN_ORDERS_EXIST"
    assert blocked.json()["error"]["details"] == [{"order_id": str(delivering.id)}]
    detail = (await client.get(f"{REQUESTS}/{request_id}", headers=reception)).json()
    assert detail["open_order_ids"] == [str(delivering.id)]
    assert detail["open_orders"] == 1
    queue = (await client.get(REQUESTS, headers=reception)).json()
    assert queue[0]["open_orders"] == 1, "the queue card warns about open orders"
    assert detail["bill_is_snapshot"] is False

    await db.execute(
        update(type(delivering))
        .where(type(delivering).id == delivering.id)
        .values(status=OrderStatus.COMPLETED)
    )
    await db.commit()
    verified = await client.post(
        f"{REQUESTS}/{request_id}/verify", json={"version": 0}, headers=reception
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "BILLING_VERIFIED"
    assert body["bill_is_snapshot"] is True
    assert body["total_vnd"] == 1_200_000 + 130_000 + 40_000 + 60_000
    assert body["bill"]["total_vnd"] == body["total_vnd"]
    assert ("CHECKOUT", "BILLING_VERIFIED") in await outbox(db)

    locked = await client.post(
        f"/api/v1/stays/{guest.stay_id}/charges",
        json={"kind": "EXTRA", "description": "Thêm", "amount_vnd": 1000},
        headers=reception,
    )
    assert locked.json()["error"]["code"] == "BILL_LOCKED"

    # Later price changes do not touch the frozen bill.
    await db.execute(update(MenuItem).values(price_vnd=999_000))
    await db.commit()
    again = (await client.get(f"{REQUESTS}/{request_id}", headers=reception)).json()
    assert again["bill"] == body["bill"]
    guest_view = (
        await client.get(f"{GUEST}/checkout-requests/current", headers=guest.phone)
    ).json()
    assert guest_view["bill"]["total_vnd"] == body["total_vnd"]
    assert guest_view["bill"]["is_estimate"] is False
    assert "guest_name" not in guest_view["bill"]


async def test_two_receptionists_at_once_one_conflict(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer, reception: dict
) -> None:
    other = staff_headers(await create_staff(db, email="rx2@h.test", role=StaffRole.RECEPTION))
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    results = await asyncio.gather(
        client.post(f"{REQUESTS}/{request_id}/verify", json={"version": 0}, headers=reception),
        client.post(f"{REQUESTS}/{request_id}/verify", json={"version": 0}, headers=other),
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] in {"CONFLICT", "INVALID_TRANSITION"}


@pytest.mark.parametrize(
    ("step", "body", "status", "code"),
    [
        ("complete", {"version": 0, "payment_method": "CASH"}, 409, "INVALID_TRANSITION"),
        ("complete", {"version": 0}, 400, None),
        ("reject", {"version": 0}, 400, None),
        ("reject", {"version": 0, "reason": ""}, 400, None),
        ("verify", {"version": 7}, 409, "CONFLICT"),
    ],
)
async def test_invalid_steps(
    client: httpx.AsyncClient,
    guest: Stayer,
    reception: dict,
    step: str,
    body: dict,
    status: int,
    code: str | None,
) -> None:
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    response = await client.post(f"{REQUESTS}/{request_id}/{step}", json=body, headers=reception)
    assert response.status_code == status
    if code:
        assert response.json()["error"]["code"] == code


# ---------- completion ----------


async def test_complete_ends_the_stay_everywhere(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer, reception: dict
) -> None:
    waiting = await client.post(
        f"{GUEST}/housekeeping-requests", json={"type": "CLEANING"}, headers=guest.phone
    )
    await client.post(
        f"{GUEST}/chat/messages",
        json={"guest_message": "Mấy giờ ăn sáng?", "assistant_message": "06:30"},
        headers=guest.phone,
    )
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    await client.post(f"{REQUESTS}/{request_id}/verify", json={"version": 0}, headers=reception)

    done = await client.post(
        f"{REQUESTS}/{request_id}/complete",
        json={"version": 1, "payment_method": "CASH"},
        headers=reception,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "COMPLETED"
    assert done.json()["payment_method"] == "CASH"

    for device in (guest.phone, guest.tablet):
        ended = await client.get(f"{GUEST}/me", headers=device)
        assert ended.status_code == 401
        assert ended.json()["error"]["details"] == [{"reason": "STAY_CLOSED"}]
    relogin = await client.post(
        "/api/v1/guest/auth/room-code",
        json={"code": guest.code, "device_id": "device-new-0001", "lang": "vi"},
    )
    assert relogin.status_code == 401

    stay = await stay_of(db, guest)
    assert stay.status is StayStatus.CLOSED
    room = await db.get(Room, stay.room_id)
    assert room is not None and room.status is RoomStatus.CLEANING
    requests = list(await db.scalars(select(HousekeepingRequest)))
    turnovers = [r for r in requests if r.type is HkType.TURNOVER]
    assert len(turnovers) == 1
    cancelled = next(r for r in requests if str(r.id) == waiting.json()["id"])
    assert cancelled.status is HkStatus.CANCELLED
    chat_left = await db.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.stay_id == uuid.UUID(guest.stay_id))
    )
    assert chat_left == 0
    pushes = await outbox(db)
    assert pushes.count(("STAY", "CLOSED")) == 1, "one thank-you"
    assert ("CHECKOUT", "COMPLETED") not in pushes, "no second notification"


# ---------- rejection ----------


async def test_reject_gives_the_stay_back(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer, reception: dict
) -> None:
    await kitchen_open_all_day(db)
    menu = await create_menu(db)
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    rejected = await client.post(
        f"{REQUESTS}/{request_id}/reject",
        json={"version": 0, "reason": "Cần kiểm tra minibar"},
        headers=reception,
    )
    assert rejected.status_code == 200
    assert rejected.json()["reject_reason"] == "Cần kiểm tra minibar"
    assert (await stay_of(db, guest)).status is StayStatus.ACTIVE
    assert ("CHECKOUT", "REJECTED") in await outbox(db)
    current = (await client.get(f"{GUEST}/checkout-requests/current", headers=guest.phone)).json()
    assert current["status"] == "REJECTED" and current["reject_reason"] == "Cần kiểm tra minibar"

    order = await client.post(
        f"{GUEST}/orders",
        json={"items": [{"item_id": str(menu["pho"].id), "quantity": 1}]},
        headers=guest.phone,
    )
    assert order.status_code == 201
    assert (await ask(client, guest)).status_code == 201, "may ask again"


async def test_a_disputed_bill_can_be_rejected_and_unlocked(
    client: httpx.AsyncClient, guest: Stayer, reception: dict
) -> None:
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    await client.post(f"{REQUESTS}/{request_id}/verify", json={"version": 0}, headers=reception)
    rejected = await client.post(
        f"{REQUESTS}/{request_id}/reject",
        json={"version": 1, "reason": "Khách không đồng ý phụ phí"},
        headers=reception,
    )
    assert rejected.status_code == 200
    unlocked = await client.patch(
        f"/api/v1/stays/{guest.stay_id}", json={"room_charge_vnd": 1_000_000}, headers=reception
    )
    assert unlocked.status_code == 200


# ---------- desk check-out, lists, roles ----------


async def test_desk_checkout_waits_for_an_open_request(
    client: httpx.AsyncClient, guest: Stayer, reception: dict
) -> None:
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    desk = await client.post(f"/api/v1/stays/{guest.stay_id}/checkout", headers=reception)
    assert desk.status_code == 409
    assert desk.json()["error"]["code"] == "CHECKOUT_REQUEST_OPEN"
    assert desk.json()["error"]["details"] == [{"checkout_request_id": request_id}]
    await client.post(
        f"{REQUESTS}/{request_id}/reject", json={"version": 0, "reason": "x"}, headers=reception
    )
    assert (
        await client.post(f"/api/v1/stays/{guest.stay_id}/checkout", headers=reception)
    ).status_code == 200


async def test_queue_and_detail(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer, reception: dict
) -> None:
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    queue = (await client.get(REQUESTS, headers=reception)).json()
    assert [r["id"] for r in queue] == [request_id]
    assert queue[0]["room_number"] == "101" and queue[0]["guest_name"] == "Tran Thi B"
    assert queue[0]["overdue"] is False
    assert queue[0]["open_orders"] == 0
    filtered = (
        await client.get(REQUESTS, params={"status": "COMPLETED"}, headers=reception)
    ).json()
    assert filtered == []
    detail = (await client.get(f"{REQUESTS}/{request_id}", headers=reception)).json()
    assert detail["bill"]["total_vnd"] == 1_200_000
    assert [h["to_status"] for h in detail["history"]] == ["CHECKOUT_REQUESTED"]
    assert detail["history"][0]["by"] == "GUEST"
    assert (await client.get(f"{REQUESTS}/{uuid.uuid4()}", headers=reception)).status_code == 404


async def test_overdue_reminder_once(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer, reception: dict
) -> None:
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    assert await remind_overdue_requests(db) == 0
    await db.execute(
        update(CheckoutRequest)
        .where(CheckoutRequest.id == uuid.UUID(request_id))
        .values(created_at=datetime.now(UTC) - timedelta(minutes=11))
    )
    await db.commit()
    assert (await client.get(REQUESTS, headers=reception)).json()[0]["overdue"] is True
    assert await remind_overdue_requests(db) == 1
    assert await remind_overdue_requests(db) == 0


async def test_another_stay_only_sees_its_own(
    client: httpx.AsyncClient, guest: Stayer, reception: dict
) -> None:
    other = await check_in(client, reception, "202")
    await ask(client, guest)
    mine = await client.get(f"{GUEST}/checkout-requests/current", headers=other.phone)
    assert mine.status_code == 404
    preview = (await client.get(f"{GUEST}/checkout/preview", headers=other.phone)).json()
    assert preview["room_number"] == "202"


@pytest.mark.parametrize("role", [StaffRole.KITCHEN, StaffRole.HOUSEKEEPING])
async def test_only_reception_handles_requests(
    client: httpx.AsyncClient, db: AsyncSession, guest: Stayer, role: StaffRole
) -> None:
    request_id = (await ask(client, guest)).json()["checkout_request_id"]
    staff = staff_headers(await create_staff(db, email=f"{role.value}@h.test", role=role))
    calls = [
        client.get(REQUESTS, headers=staff),
        client.get(f"{REQUESTS}/{request_id}", headers=staff),
        client.post(f"{REQUESTS}/{request_id}/verify", json={"version": 0}, headers=staff),
        client.post(
            f"{REQUESTS}/{request_id}/complete",
            json={"version": 0, "payment_method": "CASH"},
            headers=staff,
        ),
        client.post(
            f"{REQUESTS}/{request_id}/reject", json={"version": 0, "reason": "x"}, headers=staff
        ),
    ]
    for call in calls:
        assert (await call).status_code == 403
    guest_on_staff = await client.get(REQUESTS, headers=guest.phone)
    assert guest_on_staff.status_code == 401
    assert (
        await db.scalar(
            select(CheckoutRequest.status).where(CheckoutRequest.id == uuid.UUID(request_id))
        )
    ) is CheckoutStatus.CHECKOUT_REQUESTED
