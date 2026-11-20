"""Staff login / refresh / logout / password change through the HTTP API (SPEC-staff-auth)."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff_auth.models import Staff, StaffRefreshToken
from tests.factories import DEFAULT_PASSWORD, create_staff

ORIGIN = {"Origin": "http://localhost:3000"}
LOGIN = "/api/v1/staff/auth/login"
REFRESH = "/api/v1/staff/auth/refresh"
LOGOUT = "/api/v1/staff/auth/logout"
ME = "/api/v1/staff/me"
PASSWORD = "/api/v1/staff/me/password"


async def _login(client: httpx.AsyncClient, email: str = "le.tan@hotel.test") -> httpx.Response:
    return await client.post(LOGIN, json={"email": email, "password": DEFAULT_PASSWORD})


def _bearer(response: httpx.Response) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _refresh(client: httpx.AsyncClient, cookie: str) -> httpx.Response:
    client.cookies.clear()
    return await client.post(REFRESH, headers={**ORIGIN, "Cookie": f"staff_refresh={cookie}"})


class TestLogin:
    async def test_success_returns_token_and_hardened_cookie(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        staff = await create_staff(db)
        response = await _login(client, "LE.TAN@hotel.test")  # email is case-insensitive

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 15 * 60
        assert body["staff"] == {
            "id": str(staff.id),
            "email": "le.tan@hotel.test",
            "full_name": "Nguyen Van A",
            "role": "RECEPTION",
        }
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=strict", "path=/api/v1/staff/auth"):
            assert flag in cookie
        assert response.headers["cache-control"] == "no-store"

        me = await client.get(ME, headers=_bearer(response))
        assert me.status_code == 200 and me.json()["id"] == str(staff.id)

    @pytest.mark.parametrize(
        ("email", "password", "active"),
        [
            ("le.tan@hotel.test", "wrong-password", True),
            ("nobody@hotel.test", DEFAULT_PASSWORD, True),
            ("le.tan@hotel.test", DEFAULT_PASSWORD, False),
        ],
        ids=["wrong-password", "unknown-email", "locked-account"],
    )
    async def test_failures_look_identical(
        self, client: httpx.AsyncClient, db: AsyncSession, email: str, password: str, active: bool
    ) -> None:
        await create_staff(db, is_active=active)
        response = await client.post(LOGIN, json={"email": email, "password": password})
        assert response.status_code == 401
        error = response.json()["error"]
        assert (error["code"], error["message"]) == (
            "UNAUTHORIZED",
            "Email hoặc mật khẩu không đúng",
        )
        assert "set-cookie" not in response.headers

    async def test_sixth_failure_is_rate_limited(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        await create_staff(db)
        bad = {"email": "le.tan@hotel.test", "password": "nope"}
        for _ in range(5):
            assert (await client.post(LOGIN, json=bad)).status_code == 401

        response = await client.post(LOGIN, json=bad)
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "RATE_LIMITED"
        assert int(response.headers["Retry-After"]) > 0
        # Even the right password is refused while locked.
        assert (await _login(client)).status_code == 429

    async def test_success_resets_the_failure_counter(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        await create_staff(db)
        bad = {"email": "le.tan@hotel.test", "password": "nope"}
        for _ in range(4):
            await client.post(LOGIN, json=bad)
        assert (await _login(client)).status_code == 200
        for _ in range(4):
            assert (await client.post(LOGIN, json=bad)).status_code == 401

    async def test_rejects_unknown_fields(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            LOGIN, json={"email": "a@b.c", "password": "x", "role": "RECEPTION"}
        )
        assert response.status_code == 400


class TestRefresh:
    async def test_rotates_and_detects_reuse(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        await create_staff(db)
        first_cookie = (await _login(client)).cookies["staff_refresh"]

        rotated = await _refresh(client, first_cookie)
        assert rotated.status_code == 200
        second_cookie = rotated.cookies["staff_refresh"]
        assert second_cookie != first_cookie
        assert (await client.get(ME, headers=_bearer(rotated))).status_code == 200

        # Replaying the old cookie revokes the whole family, including the new token.
        assert (await _refresh(client, first_cookie)).status_code == 401
        assert (await _refresh(client, second_cookie)).status_code == 401

    async def test_requires_allowed_origin(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        await create_staff(db)
        cookie = (await _login(client)).cookies["staff_refresh"]
        client.cookies.clear()
        evil = await client.post(
            REFRESH, headers={"Origin": "https://evil.test", "Cookie": f"staff_refresh={cookie}"}
        )
        assert evil.status_code == 403
        missing = await client.post(REFRESH, headers={"Cookie": f"staff_refresh={cookie}"})
        assert missing.status_code == 403

    async def test_without_cookie_or_with_garbage(self, client: httpx.AsyncClient) -> None:
        client.cookies.clear()
        assert (await client.post(REFRESH, headers=ORIGIN)).status_code == 401
        assert (await _refresh(client, "garbage")).status_code == 401

    async def test_locked_account_cannot_refresh(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        staff = await create_staff(db)
        cookie = (await _login(client)).cookies["staff_refresh"]
        staff.is_active = False
        await db.commit()
        assert (await _refresh(client, cookie)).status_code == 401


class TestLogout:
    async def test_revokes_refresh_token_and_clears_cookie(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        await create_staff(db)
        cookie = (await _login(client)).cookies["staff_refresh"]
        client.cookies.clear()
        response = await client.post(
            LOGOUT, headers={**ORIGIN, "Cookie": f"staff_refresh={cookie}"}
        )
        assert response.status_code == 204
        assert 'staff_refresh=""' in response.headers["set-cookie"]
        assert (await _refresh(client, cookie)).status_code == 401

    async def test_logout_without_session_is_harmless(self, client: httpx.AsyncClient) -> None:
        client.cookies.clear()
        assert (await client.post(LOGOUT, headers=ORIGIN)).status_code == 204


class TestAccessTokenInvalidation:
    async def test_lock_makes_access_token_unusable(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        staff = await create_staff(db)
        headers = _bearer(await _login(client))
        staff.is_active = False
        await db.commit()
        assert (await client.get(ME, headers=headers)).status_code == 401

    async def test_bumped_token_version_rejects_old_token(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        staff = await create_staff(db)
        headers = _bearer(await _login(client))
        staff.token_version += 1
        await db.commit()
        assert (await client.get(ME, headers=headers)).status_code == 401

    @pytest.mark.parametrize(
        "header", [None, "Bearer", "Bearer not-a-jwt", "Basic dXNlcjpwYXNz"], ids=str
    )
    async def test_missing_or_bad_credentials(
        self, client: httpx.AsyncClient, header: str | None
    ) -> None:
        headers = {"Authorization": header} if header else {}
        assert (await client.get(ME, headers=headers)).status_code == 401


class TestChangePassword:
    async def test_changes_password_and_invalidates_other_sessions(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        await create_staff(db)
        other_device = (await _login(client)).cookies["staff_refresh"]
        this_device = await _login(client)
        this_cookie = this_device.cookies["staff_refresh"]

        client.cookies.clear()
        response = await client.post(
            PASSWORD,
            headers={**_bearer(this_device), "Cookie": f"staff_refresh={this_cookie}"},
            json={"current_password": DEFAULT_PASSWORD, "new_password": "a-brand-new-pass"},
        )
        assert response.status_code == 204

        # Old access token is dead; this device's refresh still works; the other device's not.
        assert (await client.get(ME, headers=_bearer(this_device))).status_code == 401
        assert (await _refresh(client, this_cookie)).status_code == 200
        assert (await _refresh(client, other_device)).status_code == 401
        new_login = await client.post(
            LOGIN, json={"email": "le.tan@hotel.test", "password": "a-brand-new-pass"}
        )
        assert new_login.status_code == 200

    async def test_wrong_current_password(
        self, client: httpx.AsyncClient, db: AsyncSession
    ) -> None:
        await create_staff(db)
        response = await client.post(
            PASSWORD,
            headers=_bearer(await _login(client)),
            json={"current_password": "wrong", "new_password": "a-brand-new-pass"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"

    @pytest.mark.parametrize("new_password", ["short", "le.tan@hotel.test"])
    async def test_weak_new_password(
        self, client: httpx.AsyncClient, db: AsyncSession, new_password: str
    ) -> None:
        await create_staff(db)
        response = await client.post(
            PASSWORD,
            headers=_bearer(await _login(client)),
            json={"current_password": DEFAULT_PASSWORD, "new_password": new_password},
        )
        assert response.status_code == 400


async def test_password_and_tokens_are_never_stored_in_clear(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await create_staff(db)
    cookie = (await _login(client)).cookies["staff_refresh"]
    staff = await db.scalar(select(Staff))
    assert staff is not None and DEFAULT_PASSWORD not in staff.password_hash
    stored = list(await db.scalars(select(StaffRefreshToken.token_hash)))
    assert stored and cookie not in stored


async def test_login_logs_do_not_contain_secrets(
    client: httpx.AsyncClient, db: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    await create_staff(db)
    capsys.readouterr()
    await client.post(LOGIN, json={"email": "le.tan@hotel.test", "password": "secret-typo-123"})
    response = await _login(client)
    output = capsys.readouterr().out
    assert "secret-typo-123" not in output
    assert DEFAULT_PASSWORD not in output
    assert "le.tan@hotel.test" not in output
    assert response.json()["access_token"] not in output
