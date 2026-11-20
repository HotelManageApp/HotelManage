"""Error envelope, request id and log hygiene, through the real app stack."""

import json

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.core.errors import Conflict, InvalidTransition, NotFound, RateLimited


class _Item(BaseModel):
    quantity: int = Field(ge=1)


class _Body(BaseModel):
    items: list[_Item]


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    """Add throw-away routes that exercise each error path. They exist only in tests."""

    @app.post("/_test/validate")
    async def validate(body: _Body) -> dict[str, int]:
        return {"count": len(body.items)}

    @app.get("/_test/conflict")
    async def conflict() -> None:
        raise Conflict("Phòng đang có khách", code="ROOM_NOT_VACANT")

    @app.get("/_test/transition")
    async def transition() -> None:
        raise InvalidTransition()

    @app.get("/_test/missing")
    async def missing() -> None:
        raise NotFound()

    @app.get("/_test/limited")
    async def limited() -> None:
        raise RateLimited(retry_after_seconds=30)

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    @app.get("/_test/echo")
    async def echo() -> dict[str, str]:
        return {"ok": "yes"}

    return app


def _assert_envelope(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], list)
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


async def test_validation_error_is_400_with_field_paths(client: httpx.AsyncClient) -> None:
    response = await client.post("/_test/validate", json={"items": [{"quantity": 0}]})
    error = _assert_envelope(response, 400, "VALIDATION_ERROR")
    assert error["details"][0]["field"] == "items[0].quantity"


async def test_validation_error_for_malformed_json(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/_test/validate", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    _assert_envelope(response, 400, "VALIDATION_ERROR")


async def test_conflict_keeps_custom_code(client: httpx.AsyncClient) -> None:
    error = _assert_envelope(await client.get("/_test/conflict"), 409, "ROOM_NOT_VACANT")
    assert error["message"] == "Phòng đang có khách"


async def test_invalid_transition(client: httpx.AsyncClient) -> None:
    _assert_envelope(await client.get("/_test/transition"), 409, "INVALID_TRANSITION")


async def test_app_not_found(client: httpx.AsyncClient) -> None:
    _assert_envelope(await client.get("/_test/missing"), 404, "NOT_FOUND")


async def test_unknown_route_uses_envelope(client: httpx.AsyncClient) -> None:
    _assert_envelope(await client.get("/does-not-exist"), 404, "NOT_FOUND")


async def test_method_not_allowed_uses_envelope(client: httpx.AsyncClient) -> None:
    _assert_envelope(await client.delete("/_test/echo"), 405, "METHOD_NOT_ALLOWED")


async def test_rate_limited_sets_retry_after(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/limited")
    _assert_envelope(response, 429, "RATE_LIMITED")
    assert response.headers["Retry-After"] == "30"


async def test_unhandled_error_is_500_without_leaking(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    response = await client.get("/_test/boom")
    _assert_envelope(response, 500, "INTERNAL_ERROR")
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
    logged = capsys.readouterr().out
    assert "unhandled_error" in logged  # the error is still logged for us


async def test_client_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/echo", headers={"X-Request-ID": "client-req-0001"})
    assert response.headers["X-Request-ID"] == "client-req-0001"


async def test_unsafe_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/echo", headers={"X-Request-ID": "bad id"})
    assert response.headers["X-Request-ID"] != "bad id"
    assert len(response.headers["X-Request-ID"]) == 26


async def test_access_log_has_request_fields_and_no_token(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    response = await client.get(
        "/_test/echo", headers={"Authorization": "Bearer super-secret-token-value"}
    )
    output = capsys.readouterr().out
    assert "super-secret-token-value" not in output
    records = [json.loads(line) for line in output.strip().splitlines()]
    access = next(r for r in records if r["event"] == "request")
    assert access["request_id"] == response.headers["X-Request-ID"]
    assert access["path"] == "/_test/echo"
    assert access["status"] == 200
    assert access["method"] == "GET"
    assert isinstance(access["duration_ms"], float)
