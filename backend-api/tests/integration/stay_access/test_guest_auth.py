"""Guest login with a room code (CONSTRAINTS C4.1–C4.5, C5.1, C5.2; SPEC-stay-access)."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.modules.staff_auth.models import StaffRole
from app.modules.stay_access.deps import ActiveStay, CurrentStay, ensure_same_stay
from app.modules.stay_access.models import Stay, StayStatus
from tests.conftest import TEST_STAY_JWT_SECRET
from tests.factories import checkout_in, create_room, create_staff, staff_headers

LOGIN = "/api/v1/guest/auth/room-code"
ME = "/api/v1/guest/me"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    """Test-only guest endpoints for the write-guard and the cross-stay check."""

    @app.post("/api/v1/guest/_test/write")
    async def write(ctx: ActiveStay) -> dict[str, str]:
        return {"stay_id": str(ctx.stay_id)}

    @app.get("/api/v1/guest/_test/stays/{owner}")
    async def read_other(owner: uuid.UUID, ctx: CurrentStay) -> dict[str, str]:
        ensure_same_stay(ctx, owner)
        return {"ok": "yes"}

    return app


@asynccontextmanager
async def from_ip(app: FastAPI, ip: str) -> AsyncIterator[httpx.AsyncClient]:
    """A second client with another source IP. Use together with the `client` fixture, which
    runs the app lifespan (database engine) that this client shares."""
    transport = httpx.ASGITransport(app=app, client=(ip, 40000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def reception(db: AsyncSession) -> dict[str, str]:
    return staff_headers(await create_staff(db, role=StaffRole.RECEPTION))


async def check_in(
    client: httpx.AsyncClient, db: AsyncSession, headers: dict[str, str], number: str = "101"
) -> dict:
    room = await create_room(db, number)
    response = await client.post(
        "/api/v1/stays",
        json={
            "room_id": str(room.id),
            "guest_name": "Tran Thi B",
            "expected_checkout_at": checkout_in(2),
            "room_charge_vnd": 900_000,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def login_body(code: str, device: str = "device-0001", **extra: object) -> dict:
    return {"code": code, "device_id": device, "lang": "vi", **extra}


def bearer(response: httpx.Response) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestLogin:
    async def test_valid_code_logs_in_and_exposes_only_own_stay(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        issued = await check_in(client, db, reception)
        response = await client.post(LOGIN, json=login_body(issued["room_code"]))
        assert response.status_code == 200
        body = response.json()
        assert body["stay"]["room_number"] == "101"
        assert body["stay"]["guest_name"] == "Tran Thi B"
        assert response.headers["cache-control"] == "no-store"

        claims = jwt.decode(body["access_token"], TEST_STAY_JWT_SECRET, algorithms=["HS256"])
        assert claims["typ"] == "stay"
        assert claims["stay_id"] == issued["stay"]["id"]

        me = await client.get(ME, headers=bearer(response))
        assert me.status_code == 200
        assert me.json() == {
            "room_number": "101",
            "guest_name": "Tran Thi B",
            "expected_checkout_at": body["stay"]["expected_checkout_at"],
            "status": "ACTIVE",
            "lang": "vi",
        }

    async def test_friendly_input(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        code = (await check_in(client, db, reception))["room_code"]
        messy = f"  {code[:4].lower()} {code[5:].lower()} "
        assert (await client.post(LOGIN, json=login_body(messy))).status_code == 200

    @pytest.mark.parametrize("code", ["AAAA-BBBB", "ABCD", "0000-0000", "not a code at all"])
    async def test_unknown_code_is_401_with_generic_message(
        self, client: httpx.AsyncClient, db: AsyncSession, code: str
    ) -> None:
        response = await client.post(LOGIN, json=login_body(code))
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Mã phòng không hợp lệ hoặc đã hết hạn"

    @pytest.mark.parametrize(
        "body",
        [
            {"code": "AAAA-BBBB", "device_id": "device-0001", "room_id": str(uuid.uuid4())},
            {"code": "AAAA-BBBB", "device_id": "device-0001", "stay_id": str(uuid.uuid4())},
            {"code": "AAAA-BBBB", "device_id": "x"},
            {"code": "AAAA-BBBB", "device_id": "device-0001", "lang": "fr"},
        ],
        ids=["room_id", "stay_id", "short-device", "bad-lang"],
    )
    async def test_rejects_smuggled_or_bad_fields(
        self, client: httpx.AsyncClient, db: AsyncSession, body: dict
    ) -> None:
        response = await client.post(LOGIN, json=body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_code_expires_after_grace_period(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        issued = await check_in(client, db, reception)
        await db.execute(
            update(Stay)
            .where(Stay.id == uuid.UUID(issued["stay"]["id"]))
            .values(expected_checkout_at=datetime.now(UTC) - timedelta(hours=7))
        )
        await db.commit()
        assert (await client.post(LOGIN, json=login_body(issued["room_code"]))).status_code == 401

    async def test_checkout_pending_can_log_in_but_not_write(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        issued = await check_in(client, db, reception)
        await db.execute(
            update(Stay)
            .where(Stay.id == uuid.UUID(issued["stay"]["id"]))
            .values(status=StayStatus.CHECKOUT_PENDING)
        )
        await db.commit()
        login = await client.post(LOGIN, json=login_body(issued["room_code"]))
        assert login.status_code == 200
        assert (await client.get(ME, headers=bearer(login))).status_code == 200
        write = await client.post("/api/v1/guest/_test/write", headers=bearer(login))
        assert write.status_code == 409
        assert write.json()["error"]["code"] == "STAY_CHECKOUT_PENDING"


class TestRevocation:
    """C5.1: not checked in / checked out / revoked -> 401; other stay -> 403."""

    async def test_checkout_kills_code_and_tokens_at_once(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        issued = await check_in(client, db, reception)
        login = await client.post(LOGIN, json=login_body(issued["room_code"]))
        assert (
            await client.post("/api/v1/guest/_test/write", headers=bearer(login))
        ).status_code == 200

        await client.post(f"/api/v1/stays/{issued['stay']['id']}/checkout", headers=reception)

        me = await client.get(ME, headers=bearer(login))
        assert me.status_code == 401
        assert me.json()["error"]["details"] == [{"reason": "STAY_CLOSED"}]
        assert (await client.post(LOGIN, json=login_body(issued["room_code"]))).status_code == 401

    async def test_reissue_kills_old_code_and_devices(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        issued = await check_in(client, db, reception)
        phone_a = await client.post(LOGIN, json=login_body(issued["room_code"], "device-aaaa"))
        phone_b = await client.post(LOGIN, json=login_body(issued["room_code"], "device-bbbb"))

        new = await client.post(
            f"/api/v1/stays/{issued['stay']['id']}/reissue-code", headers=reception
        )
        for phone in (phone_a, phone_b):
            me = await client.get(ME, headers=bearer(phone))
            assert me.status_code == 401
            assert me.json()["error"]["details"] == [{"reason": "CODE_REISSUED"}]
        assert (await client.post(LOGIN, json=login_body(issued["room_code"]))).status_code == 401
        assert (
            await client.post(LOGIN, json=login_body(new.json()["room_code"], "device-cccc"))
        ).status_code == 200

    async def test_logout_revokes_only_this_device(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        code = (await check_in(client, db, reception))["room_code"]
        a = await client.post(LOGIN, json=login_body(code, "device-aaaa"))
        b = await client.post(LOGIN, json=login_body(code, "device-bbbb"))
        assert (
            await client.post("/api/v1/guest/auth/logout", headers=bearer(a))
        ).status_code == 204
        assert (await client.get(ME, headers=bearer(a))).status_code == 401
        assert (await client.get(ME, headers=bearer(b))).status_code == 200

    async def test_other_stays_resources_are_forbidden(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        stay_a = await check_in(client, db, reception, "101")
        stay_b = await check_in(client, db, reception, "202")
        token_b = bearer(await client.post(LOGIN, json=login_body(stay_b["room_code"])))
        own = await client.get(f"/api/v1/guest/_test/stays/{stay_b['stay']['id']}", headers=token_b)
        other = await client.get(
            f"/api/v1/guest/_test/stays/{stay_a['stay']['id']}", headers=token_b
        )
        assert own.status_code == 200
        assert other.status_code == 403

    async def test_tokens_do_not_cross_between_guest_and_staff(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        guest = bearer(
            await client.post(
                LOGIN, json=login_body((await check_in(client, db, reception))["room_code"])
            )
        )
        assert (await client.get("/api/v1/rooms", headers=guest)).status_code == 401
        assert (await client.get("/api/v1/staff/me", headers=guest)).status_code == 401
        assert (await client.get(ME, headers=reception)).status_code == 401
        assert (await client.get(ME)).status_code == 401

    async def test_forged_token_for_another_room(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        stay_a = await check_in(client, db, reception, "101")
        stay_b = await check_in(client, db, reception, "202")
        login_b = await client.post(LOGIN, json=login_body(stay_b["room_code"]))
        claims = jwt.decode(
            login_b.json()["access_token"], TEST_STAY_JWT_SECRET, algorithms=["HS256"]
        )
        claims["room_id"] = stay_a["stay"]["room_id"]
        forged = jwt.encode(claims, TEST_STAY_JWT_SECRET, algorithm="HS256")
        response = await client.get(ME, headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401


class TestDevicesAndRenewal:
    async def test_device_limit_and_relogin_same_device(
        self, app: FastAPI, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        code = (await check_in(client, db, reception))["room_code"]
        for i in range(6):
            async with from_ip(app, f"10.0.0.{i + 1}") as c:
                assert (
                    await c.post(LOGIN, json=login_body(code, f"device-{i:04d}"))
                ).status_code == 200
        async with from_ip(app, "10.0.1.1") as c:
            seventh = await c.post(LOGIN, json=login_body(code, "device-9999"))
            assert seventh.status_code == 409
            assert seventh.json()["error"]["code"] == "TOO_MANY_DEVICES"
            # The same phone logging in again replaces its own session.
            assert (await c.post(LOGIN, json=login_body(code, "device-0000"))).status_code == 200

    async def test_renew_follows_extended_checkout(
        self, client: httpx.AsyncClient, db: AsyncSession, reception: dict[str, str]
    ) -> None:
        issued = await check_in(client, db, reception)
        login = await client.post(LOGIN, json=login_body(issued["room_code"]))
        later = (datetime.now(UTC) + timedelta(days=5)).replace(microsecond=0)
        await client.patch(
            f"/api/v1/stays/{issued['stay']['id']}",
            json={"expected_checkout_at": later.isoformat()},
            headers=reception,
        )
        renewed = await client.post("/api/v1/guest/auth/renew", headers=bearer(login))
        assert renewed.status_code == 200
        expires_at = datetime.fromisoformat(renewed.json()["expires_at"])
        assert expires_at == later + timedelta(hours=6)
        assert (await client.get(ME, headers=bearer(renewed))).status_code == 200


class TestRateLimits:
    """C4.3 / C5.2."""

    async def test_sixth_request_per_minute_from_one_ip_is_429(
        self, app: FastAPI, db: AsyncSession, client: httpx.AsyncClient
    ) -> None:
        async with from_ip(app, "203.0.113.7") as c:
            for i in range(5):
                assert (
                    await c.post(LOGIN, json=login_body("AAAA-BBBB", f"dev-{i:06d}"))
                ).status_code == 401
            blocked = await c.post(LOGIN, json=login_body("AAAA-BBBB", "dev-999999"))
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
        assert 0 < int(blocked.headers["Retry-After"]) <= 60

    async def test_ten_failures_lock_the_ip_for_15_minutes(
        self, app: FastAPI, db: AsyncSession, reception: dict[str, str], client: httpx.AsyncClient
    ) -> None:
        code = (await check_in(client, db, reception))["room_code"]
        ip = "198.51.100.9"
        async with from_ip(app, ip) as c:
            for i in range(10):
                if i and i % 5 == 0:  # stay under the per-minute budget; we test the failure lock
                    await rate_limit.reset(db, f"room_code:ip:{ip}")
                    await db.commit()
                assert (
                    await c.post(LOGIN, json=login_body("AAAA-BBBB", f"dev-{i:06d}"))
                ).status_code == 401
            await rate_limit.reset(db, f"room_code:ip:{ip}")
            await db.commit()
            locked = await c.post(LOGIN, json=login_body(code, "dev-correct"))
        assert locked.status_code == 429  # even the right code, while locked
        assert 840 <= int(locked.headers["Retry-After"]) <= 900

    async def test_ten_failures_lock_the_device_across_ips(
        self, app: FastAPI, db: AsyncSession, reception: dict[str, str], client: httpx.AsyncClient
    ) -> None:
        code = (await check_in(client, db, reception))["room_code"]
        for i in range(10):
            async with from_ip(app, f"192.0.2.{i + 1}") as c:
                assert (
                    await c.post(LOGIN, json=login_body("AAAA-BBBB", "stolen-phone"))
                ).status_code == 401
        async with from_ip(app, "192.0.2.200") as c:
            assert (await c.post(LOGIN, json=login_body(code, "stolen-phone"))).status_code == 429
            assert (await c.post(LOGIN, json=login_body(code, "other-phone"))).status_code == 200


async def test_room_code_never_reaches_the_logs(
    client: httpx.AsyncClient,
    db: AsyncSession,
    reception: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    issued = await check_in(client, db, reception)
    capsys.readouterr()
    login = await client.post(LOGIN, json=login_body(issued["room_code"]))
    await client.post(LOGIN, json=login_body("WXYZ-2345"))
    await client.get(ME, headers=bearer(login))
    output = capsys.readouterr().out
    for secret in (
        issued["room_code"],
        issued["room_code"].replace("-", ""),
        "WXYZ",
        login.json()["access_token"],
    ):
        assert secret not in output
