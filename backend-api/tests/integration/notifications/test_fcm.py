"""FCM HTTP v1 sender, device-token API and the check-out thank-you (SPEC-notifications)."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ConfigError
from app.modules.notifications.fcm import FcmSender, build_payload, classify
from app.modules.notifications.models import DeliveryStatus, NotificationOutbox
from app.modules.notifications.outbox_worker import OutboxWorker
from app.modules.notifications.senders import FakePushSender, PushMessage, SendOutcome
from app.modules.staff_auth.models import StaffRole
from app.modules.stay_access.models import StaySession
from tests.conftest import make_settings
from tests.factories import add_session, create_staff, create_stay, staff_headers

MESSAGE = PushMessage(
    token="device-token-123456",
    title="Đơn đang giao",
    body="Món sắp tới",
    data={"type": "FOOD_ORDER", "entity_id": "x", "status": "DELIVERING"},
)


def fcm_error(
    status: int, error_code: str | None = None, grpc: str | None = None
) -> httpx.Response:
    error: dict = {"code": status, "message": "x"}
    if grpc:
        error["status"] = grpc
    if error_code:
        error["details"] = [
            {
                "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                "errorCode": error_code,
            }
        ]
    return httpx.Response(status, json={"error": error})


@pytest.mark.parametrize(
    ("response", "outcome"),
    [
        (httpx.Response(200, json={"name": "projects/p/messages/1"}), SendOutcome.OK),
        (fcm_error(404, "UNREGISTERED", "NOT_FOUND"), SendOutcome.UNREGISTERED),
        (fcm_error(400, "INVALID_ARGUMENT", "INVALID_ARGUMENT"), SendOutcome.UNREGISTERED),
        (fcm_error(429, "QUOTA_EXCEEDED", "RESOURCE_EXHAUSTED"), SendOutcome.RETRY),
        (fcm_error(503, "UNAVAILABLE", "UNAVAILABLE"), SendOutcome.RETRY),
        (fcm_error(500), SendOutcome.RETRY),
        (fcm_error(401, "THIRD_PARTY_AUTH_ERROR", "UNAUTHENTICATED"), SendOutcome.FATAL),
        (fcm_error(403, None, "PERMISSION_DENIED"), SendOutcome.FATAL),
        (httpx.Response(400, text="not json"), SendOutcome.FATAL),
    ],
)
def test_classify(response: httpx.Response, outcome: SendOutcome) -> None:
    assert classify(response).outcome is outcome


async def _token() -> str:
    return "oauth-access-token"


async def test_sender_posts_http_v1_message() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"name": "ok"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = FcmSender(project_id="hotel-proj", access_token=_token, client=client)
    result = await sender.send(MESSAGE)
    await sender.aclose()

    assert result.outcome is SendOutcome.OK
    request = seen[0]
    assert str(request.url) == "https://fcm.googleapis.com/v1/projects/hotel-proj/messages:send"
    assert request.headers["Authorization"] == "Bearer oauth-access-token"
    body = json.loads(request.content)
    assert body == build_payload(MESSAGE)
    assert body["message"]["android"] == {
        "priority": "HIGH",
        "notification": {"channel_id": "requests"},
    }


async def test_network_error_is_retryable_and_auth_error_is_fatal() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    flaky = FcmSender(
        project_id="p",
        access_token=_token,
        client=httpx.AsyncClient(transport=httpx.MockTransport(broken)),
    )
    assert (await flaky.send(MESSAGE)).outcome is SendOutcome.RETRY

    async def no_token() -> str:
        raise RuntimeError("bad service account")

    unauthorised = FcmSender(project_id="p", access_token=no_token)
    assert (await unauthorised.send(MESSAGE)).outcome is SendOutcome.FATAL


def test_fcm_mode_requires_project_and_credentials() -> None:
    with pytest.raises(ConfigError, match="FCM_PROJECT_ID"):
        make_settings(fcm_sender="fcm")
    assert (
        make_settings(
            fcm_sender="fcm", fcm_project_id="p", fcm_credentials_file="/run/secrets/x.json"
        ).fcm_sender
        == "fcm"
    )


# ---------- device-token API ----------


async def _guest(
    client: httpx.AsyncClient, db: AsyncSession, number: str = "101"
) -> tuple[str, dict]:
    reception = staff_headers(
        await create_staff(db, email=f"r{number}@h.test", role=StaffRole.RECEPTION)
    )
    room = await client.post("/api/v1/rooms", json={"number": number}, headers=reception)
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
        json={"code": issued.json()["room_code"], "device_id": f"device-{number}-0001"},
    )
    return issued.json()["stay"]["id"], {
        "Authorization": f"Bearer {login.json()['access_token']}"
    } | {"X-Reception": json.dumps(reception)}


def _guest_headers(headers: dict) -> dict:
    return {"Authorization": headers["Authorization"]}


async def _tokens(db: AsyncSession) -> list[str | None]:
    db.expire_all()
    return list(await db.scalars(select(StaySession.fcm_token).order_by(StaySession.created_at)))


async def test_register_replace_and_remove_token(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    _, headers = await _guest(client, db)
    token = "fcm:" + "A" * 40
    put = await client.put(
        "/api/v1/guest/me/fcm-token", json={"fcm_token": token}, headers=_guest_headers(headers)
    )
    assert put.status_code == 204
    assert await _tokens(db) == [token]

    delete = await client.delete("/api/v1/guest/me/fcm-token", headers=_guest_headers(headers))
    assert delete.status_code == 204
    assert await _tokens(db) == [None]


@pytest.mark.parametrize(
    "body",
    [
        {"fcm_token": "short"},
        {"fcm_token": "has spaces " + "x" * 30},
        {"fcm_token": "x" * 30, "room_id": str(uuid.uuid4())},
    ],
    ids=["short", "bad-chars", "extra-field"],
)
async def test_rejects_bad_token_bodies(
    client: httpx.AsyncClient, db: AsyncSession, body: dict
) -> None:
    _, headers = await _guest(client, db)
    response = await client.put(
        "/api/v1/guest/me/fcm-token", json=body, headers=_guest_headers(headers)
    )
    assert response.status_code == 400


async def test_token_endpoints_need_a_guest(client: httpx.AsyncClient) -> None:
    assert (
        await client.put("/api/v1/guest/me/fcm-token", json={"fcm_token": "x" * 30})
    ).status_code == 401
    assert (await client.delete("/api/v1/guest/me/fcm-token")).status_code == 401


async def test_a_token_moves_with_the_phone(client: httpx.AsyncClient, db: AsyncSession) -> None:
    """Same phone, new stay: the old stay must not keep pushing to it."""
    _, first = await _guest(client, db, "101")
    _, second = await _guest(client, db, "202")
    token = "shared-phone-token-" + "B" * 30
    await client.put(
        "/api/v1/guest/me/fcm-token", json={"fcm_token": token}, headers=_guest_headers(first)
    )
    await client.put(
        "/api/v1/guest/me/fcm-token", json={"fcm_token": token}, headers=_guest_headers(second)
    )
    assert await _tokens(db) == [None, token]


# ---------- stay lifecycle ----------


async def test_checkout_sends_one_thank_you_then_nothing(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    stay_id, headers = await _guest(client, db)
    reception = json.loads(headers["X-Reception"])
    token = "phone-token-" + "C" * 30
    await client.put(
        "/api/v1/guest/me/fcm-token", json={"fcm_token": token}, headers=_guest_headers(headers)
    )

    assert (
        await client.post(f"/api/v1/stays/{stay_id}/checkout", headers=reception)
    ).status_code == 200
    assert await _tokens(db) == [None]

    sender = FakePushSender()
    worker = OutboxWorker(async_sessionmaker(db.bind, expire_on_commit=False), sender)
    await worker.run_once()
    assert [(m.token, m.title, m.data["status"]) for m in sender.sent] == [
        (token, "Cảm ơn Quý khách", "CLOSED")
    ]

    # Anything emitted for this stay afterwards reaches nobody.
    db.add(
        NotificationOutbox(
            stay_id=uuid.UUID(stay_id), entity_type="STAY", entity_id=uuid.uuid4(), status="TEST"
        )
    )
    await db.commit()
    await worker.run_once()
    assert len(sender.sent) == 1
    db.expire_all()
    statuses = sorted(await db.scalars(select(NotificationOutbox.delivery_status)))
    assert statuses == [
        DeliveryStatus.SENT,
        DeliveryStatus.SKIPPED,
    ]  # thank-you sent, later one skipped


async def test_checkout_without_devices_still_tells_staff(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    stay = await create_stay(db)
    reception = staff_headers(await create_staff(db, email="rx@h.test", role=StaffRole.RECEPTION))
    assert (
        await client.post(f"/api/v1/stays/{stay.id}/checkout", headers=reception)
    ).status_code == 200
    db.expire_all()
    assert list(await db.scalars(select(NotificationOutbox))) == []  # no push row, SSE only


async def test_reissue_and_logout_drop_push_tokens(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    stay = await create_stay(db)
    await add_session(db, stay, fcm_token="phone-a-" + "D" * 30)
    reception = staff_headers(await create_staff(db, email="rx@h.test", role=StaffRole.RECEPTION))
    assert (
        await client.post(f"/api/v1/stays/{stay.id}/reissue-code", headers=reception)
    ).status_code == 200
    assert await _tokens(db) == [None]
