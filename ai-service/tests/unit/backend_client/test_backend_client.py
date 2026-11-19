"""backend_client: guest token on every call, 3 s timeout, error mapping (T39)."""

import json
import uuid

import httpx
import pytest

from app.core.backend_client import (
    BackendClient,
    BackendError,
    BackendRateLimited,
    BackendUnauthorized,
    BackendUnavailable,
)
from app.core.config import ConfigError
from tests.conftest import make_settings

TOKEN = "eyJ.guest-token.sig"


def envelope(status: int, code: str, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"code": code, "message": code.lower(), "details": [], "request_id": "r"}},
        headers=headers,
    )


class Backend:
    def __init__(self, answer: httpx.Response | Exception) -> None:
        self.answer = answer
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def client_for(backend: Backend) -> BackendClient:
    return BackendClient(
        "http://backend:8000/", timeout_seconds=3, transport=httpx.MockTransport(backend)
    )


async def test_every_call_carries_the_guest_token() -> None:
    backend = Backend(
        httpx.Response(
            200,
            json={
                "room_number": "101",
                "guest_name": "Tran Thi B",
                "expected_checkout_at": "2026-11-21T05:00:00Z",
                "status": "CHECKOUT_PENDING",
                "do_not_disturb": False,
                "lang": "en",
            },
        )
    )
    me = await client_for(backend).me(TOKEN)
    request = backend.requests[0]
    assert str(request.url) == "http://backend:8000/api/v1/guest/me"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert me.room_number == "101" and me.lang == "en" and me.checkout_pending


async def test_kb_search_history_quota_and_hotel_info_requests() -> None:
    backend = Backend(httpx.Response(200, json={"found": False, "entries": [], "places": []}))
    api = client_for(backend)
    data = await api.kb_search(TOKEN, topic="BREAKFAST", query="Mấy giờ ăn sáng?", lang="vi")
    assert data["found"] is False
    params = backend.requests[0].url.params
    assert (params["topic"], params["q"], params["lang"]) == ("BREAKFAST", "Mấy giờ ăn sáng?", "vi")

    backend.answer = httpx.Response(
        200, json=[{"id": "1", "role": "GUEST", "content": "hi", "created_at": "x"}]
    )
    lines = await api.history(TOKEN, limit=10)
    assert [(line.role, line.content) for line in lines] == [("GUEST", "hi")]
    assert backend.requests[-1].url.params["limit"] == "10"

    backend.answer = httpx.Response(200, json={"remaining_minute": 9, "remaining_day": 99})
    await api.take_quota(TOKEN)
    assert backend.requests[-1].method == "POST"
    assert backend.requests[-1].url.path == "/api/v1/guest/chat/quota"

    backend.answer = httpx.Response(
        200,
        json={
            "hotel_name": "Hoa Sen",
            "reception_phone": "028",
            "default_lang": "vi",
            "chat_enabled": False,
        },
    )
    info = await api.hotel_info(TOKEN)
    assert info.hotel_name == "Hoa Sen" and info.chat_enabled is False


async def test_save_exchange_body() -> None:
    backend = Backend(httpx.Response(201, json={"message_id": "m-2", "guest_message_id": "m-1"}))
    client_id = uuid.uuid4()
    message_id = await client_for(backend).save_exchange(
        TOKEN,
        guest_message="hi",
        assistant_message="hello",
        tool_trace=[{"tool": "get_hotel_info_and_guide"}],
        grounded=True,
        client_message_id=client_id,
    )
    assert message_id == "m-2"
    assert json.loads(backend.requests[0].content) == {
        "guest_message": "hi",
        "assistant_message": "hello",
        "tool_trace": [{"tool": "get_hotel_info_and_guide"}],
        "grounded": True,
        "client_message_id": str(client_id),
    }


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        (envelope(401, "UNAUTHORIZED"), BackendUnauthorized),
        (envelope(403, "FORBIDDEN"), BackendError),
        (envelope(400, "VALIDATION_ERROR"), BackendError),
        (envelope(500, "INTERNAL_ERROR"), BackendUnavailable),
        (envelope(503, "UNAVAILABLE"), BackendUnavailable),
        (httpx.Response(502, text="bad gateway"), BackendUnavailable),
        (httpx.ReadTimeout("slow"), BackendUnavailable),
        (httpx.ConnectError("refused"), BackendUnavailable),
    ],
)
async def test_errors_are_mapped(answer: httpx.Response | Exception, kind: type) -> None:
    with pytest.raises(kind) as caught:
        await client_for(Backend(answer)).me(TOKEN)
    assert TOKEN not in str(caught.value)


async def test_rate_limit_keeps_retry_after() -> None:
    limited = Backend(envelope(429, "RATE_LIMITED", {"Retry-After": "42"}))
    with pytest.raises(BackendRateLimited) as caught:
        await client_for(limited).take_quota(TOKEN)
    assert caught.value.retry_after_seconds == 42
    assert caught.value.message == "rate_limited"
    no_header = Backend(envelope(429, "RATE_LIMITED"))
    with pytest.raises(BackendRateLimited) as again:
        await client_for(no_header).take_quota(TOKEN)
    assert again.value.retry_after_seconds == 60


async def test_unauthorized_keeps_the_backend_code() -> None:
    with pytest.raises(BackendUnauthorized) as caught:
        await client_for(Backend(envelope(401, "UNAUTHORIZED"))).history(TOKEN)
    assert caught.value.status == 401 and caught.value.code == "UNAUTHORIZED"


async def test_timeout_is_three_seconds_by_default_from_settings() -> None:
    settings = make_settings()
    assert settings.backend_timeout_seconds == 3.0
    assert str(settings.backend_internal_url) == "http://localhost:8000/"
    api = BackendClient(str(settings.backend_internal_url))
    assert api._http.timeout.read == 3.0
    await api.aclose()


@pytest.mark.parametrize("provider", ["gemini", "openai"])
def test_a_real_provider_needs_its_key(provider: str) -> None:
    with pytest.raises(ConfigError, match=f"{provider.upper()}_API_KEY is required"):
        make_settings(llm_provider=provider)
