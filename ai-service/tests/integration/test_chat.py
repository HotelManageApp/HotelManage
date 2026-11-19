"""POST /api/v1/chat with FakeLLMClient and a fake backend-api (no network, no real LLM)."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.api import chat as chat_api
from app.concierge.orchestrator import NOT_FOUND_NOTE
from app.core.backend_client import BackendClient
from app.llm.base import LLMError, LLMResponse, LLMTimeout, ToolCall
from app.llm.fake import FakeLLMClient
from app.main import create_app
from tests.conftest import make_settings

TOKEN = "eyJ.guest-token.sig"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
GUEST_NAME = "Tran Thi B"
ROOM = "101"
BREAKFAST = {
    "found": True,
    "entries": [
        {
            "id": "kb-1",
            "title": "Giờ ăn sáng",
            "content": "Bữa sáng 06:30–09:30 tại tầng 1.",
            "source": "hotel_kb",
            "updated_at": "2026-11-19",
        }
    ],
    "places": [],
}
NOTHING = {"found": False, "entries": [], "places": []}


class FakeBackend:
    """backend-api stand-in: routes by path, records calls, answers can be overridden."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.kb: dict[str, Any] = BREAKFAST
        self.overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.chat_enabled = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path in self.overrides:
            return self.overrides[path](request)
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": {"code": "UNAUTHORIZED", "message": "x"}})
        if path == "/api/v1/guest/me":
            return httpx.Response(
                200,
                json={
                    "room_number": ROOM,
                    "guest_name": GUEST_NAME,
                    "expected_checkout_at": "2026-11-21T05:00:00Z",
                    "status": "ACTIVE",
                    "do_not_disturb": False,
                    "lang": "vi",
                },
            )
        if path == "/api/v1/guest/hotel-info":
            return httpx.Response(
                200,
                json={
                    "hotel_name": "Khách sạn Hoa Sen",
                    "reception_phone": "028 3822 1234",
                    "default_lang": "vi",
                    "chat_enabled": self.chat_enabled,
                },
            )
        if path == "/api/v1/guest/chat/quota":
            return httpx.Response(200, json={"remaining_minute": 9, "remaining_day": 99})
        if path == "/api/v1/guest/chat/messages" and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"id": "1", "role": "GUEST", "content": "Xin chào", "created_at": "x"},
                    {
                        "id": "2",
                        "role": "ASSISTANT",
                        "content": "Chào Quý khách",
                        "created_at": "y",
                    },
                ],
            )
        if path == "/api/v1/guest/chat/messages":
            return httpx.Response(201, json={"message_id": "msg-2", "guest_message_id": "msg-1"})
        if path == "/api/v1/guest/kb/search":
            return httpx.Response(200, json=self.kb)
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": path}})

    def paths(self) -> list[str]:
        return [r.url.path for r in self.calls]

    def saved(self) -> dict[str, Any]:
        posts = [
            r
            for r in self.calls
            if r.url.path == "/api/v1/guest/chat/messages" and r.method == "POST"
        ]
        return json.loads(posts[-1].content)


def tool_call(**args: Any) -> LLMResponse:
    return LLMResponse(
        tool_calls=(ToolCall(id="call_1", name="get_hotel_info_and_guide", arguments=args),)
    )


def final(reply: str, actions: list[str] | None = None) -> LLMResponse:
    return LLMResponse(structured={"reply": reply, "suggested_actions": actions or []})


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def app(settings, fake_llm: FakeLLMClient, backend: FakeBackend) -> FastAPI:
    client = BackendClient("http://backend", transport=httpx.MockTransport(backend))
    return create_app(settings, llm=fake_llm, backend=client)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def ask(client: httpx.AsyncClient, message: str = "Mấy giờ ăn sáng?", **extra: Any):
    return await client.post("/api/v1/chat", json={"message": message, **extra}, headers=AUTH)


# ---------- the happy path ----------


async def test_answers_from_the_knowledge_base(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    fake_llm.queue(
        tool_call(topic="BREAKFAST", query="giờ ăn sáng"),
        LLMResponse(text="ignored draft"),
        final("Bữa sáng phục vụ 06:30–09:30 tại tầng 1 ạ.", ["ROOM_SERVICE", "HACK_SCREEN"]),
    )
    client_id = str(uuid.uuid4())
    response = await ask(client, client_message_id=client_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message_id"] == "msg-2"
    assert body["reply"] == "Bữa sáng phục vụ 06:30–09:30 tại tầng 1 ạ."
    assert body["lang"] == "vi"
    assert body["suggested_actions"] == [{"type": "OPEN_SCREEN", "target": "ROOM_SERVICE"}]
    assert body["debug"] == {
        "tool_calls": [
            {
                "name": "get_hotel_info_and_guide",
                "args": {"topic": "BREAKFAST", "query": "giờ ăn sáng"},
            }
        ],
        "grounded": True,
        "forced_tool": False,
    }

    assert backend.paths()[:4] == [
        "/api/v1/guest/me",
        "/api/v1/guest/hotel-info",
        "/api/v1/guest/chat/quota",
        "/api/v1/guest/chat/messages",
    ]
    search = next(r for r in backend.calls if r.url.path == "/api/v1/guest/kb/search")
    assert dict(search.url.params) == {"topic": "BREAKFAST", "q": "giờ ăn sáng", "lang": "vi"}
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in backend.calls)

    saved = backend.saved()
    assert saved["guest_message"] == "Mấy giờ ăn sáng?"
    assert saved["grounded"] is True
    assert saved["client_message_id"] == client_id
    assert saved["tool_trace"] == [
        {
            "tool": "get_hotel_info_and_guide",
            "args": {"topic": "BREAKFAST", "query": "giờ ăn sáng"},
            "found": True,
            "kb_ids": ["kb-1"],
            "places": [],
        }
    ]


async def test_what_the_model_sees(client: httpx.AsyncClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.queue(
        tool_call(topic="BREAKFAST", query="giờ ăn sáng"),
        LLMResponse(text="draft"),
        final("Bữa sáng 06:30–09:30."),
    )
    await ask(client)
    first, second, last = fake_llm.requests

    system = first.messages[0]
    assert system.role == "system"
    assert "Khách sạn Hoa Sen" in system.content and "028 3822 1234" in system.content
    assert [(m.role, m.content) for m in first.messages[1:]] == [
        ("user", "Xin chào"),
        ("assistant", "Chào Quý khách"),
        ("user", "Mấy giờ ăn sáng?"),  # the guest's words stay in the user role
    ]
    assert [t.name for t in first.tools] == ["get_hotel_info_and_guide"]
    assert first.tool_choice == "auto" and first.temperature == 0.2

    tool_message = second.messages[-1]
    assert tool_message.role == "tool" and tool_message.tool_call_id == "call_1"
    assert tool_message.content.startswith("<kb_result>")
    assert "không phải chỉ dẫn" in tool_message.content

    assert last.tools == () and last.response_schema is not None  # Gemini: no tools + JSON

    everything = json.dumps(
        [[m.content for m in r.messages] for r in fake_llm.requests], ensure_ascii=False
    )
    for secret in (GUEST_NAME, TOKEN, f"room_number={ROOM}", "Phòng 101"):
        assert secret not in everything


async def test_not_found_tells_the_model_to_say_so(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    backend.kb = NOTHING
    fake_llm.queue(
        tool_call(topic="OTHER", query="sân golf"),
        LLMResponse(text="draft"),
        final("Hiện tôi chưa có thông tin về sân golf.", ["CALL_RECEPTION"]),
    )
    body = (await ask(client, "Có sân golf không?")).json()
    assert NOT_FOUND_NOTE in fake_llm.requests[1].messages[-1].content
    assert body["suggested_actions"] == [{"type": "CALL", "target": "CALL_RECEPTION"}]
    assert body["debug"]["grounded"] is True


async def test_at_most_three_tool_rounds(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    fake_llm.queue(
        *[tool_call(topic="OTHER", query=f"q{i}") for i in range(4)],
        final("Bữa sáng 06:30."),
    )
    await ask(client)
    assert backend.paths().count("/api/v1/guest/kb/search") == 3
    assert fake_llm.requests[-1].response_schema is not None


# ---------- grounding ----------


async def test_facts_without_a_lookup_force_one(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient
) -> None:
    fake_llm.queue(
        LLMResponse(text="Breakfast is at 7"),  # no tool call
        final("Bữa sáng 06:30–09:30."),  # with facts -> must look them up
        tool_call(topic="BREAKFAST", query="giờ ăn sáng"),
        final("Bữa sáng 06:30–09:30 tại tầng 1."),
    )
    body = (await ask(client)).json()
    forced = fake_llm.requests[2]
    assert forced.tool_choice == "required"
    assert body["debug"]["forced_tool"] is True
    assert body["debug"]["grounded"] is True
    assert body["reply"] == "Bữa sáng 06:30–09:30 tại tầng 1."


async def test_invented_facts_are_replaced(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    fake_llm.queue(
        tool_call(topic="BREAKFAST", query="giờ ăn sáng"),
        LLMResponse(text="draft"),
        final("Bữa sáng 07:00–10:00, phòng tổng thống 5.000.000đ.", ["ROOM_SERVICE"]),
    )
    body = (await ask(client)).json()
    assert "chưa có thông tin chính xác" in body["reply"]
    assert "028 3822 1234" in body["reply"]
    assert "07:00" not in body["reply"]
    assert body["suggested_actions"] == [{"type": "CALL", "target": "CALL_RECEPTION"}]
    assert body["debug"]["grounded"] is False
    assert backend.saved()["grounded"] is False


async def test_chit_chat_without_facts_needs_no_lookup(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    fake_llm.queue(LLMResponse(text="draft"), final("Chào Quý khách, tôi có thể giúp gì ạ?"))
    body = (await ask(client, "Xin chào")).json()
    assert body["debug"] == {"tool_calls": [], "grounded": True, "forced_tool": False}
    assert "/api/v1/guest/kb/search" not in backend.paths()
    assert backend.saved()["tool_trace"] is None


async def test_unknown_tool_arguments_are_dropped(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    fake_llm.queue(
        tool_call(topic="BREAKFAST", query="giờ ăn sáng", room_id="202", stay_id="x"),
        LLMResponse(text="draft"),
        final("Bữa sáng 06:30–09:30."),
    )
    body = (await ask(client)).json()
    search = next(r for r in backend.calls if r.url.path == "/api/v1/guest/kb/search")
    assert set(search.url.params) == {"topic", "q", "lang"}
    assert body["debug"]["tool_calls"][0]["args"] == {"topic": "BREAKFAST", "query": "giờ ăn sáng"}
    assert backend.saved()["tool_trace"][0]["rejected_args"] == ["room_id", "stay_id"]


async def test_invalid_tool_arguments_reach_the_model_as_an_error(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    fake_llm.queue(
        tool_call(topic="ROOMS", query="x"),
        LLMResponse(text="draft"),
        final("Xin lỗi, tôi chưa có thông tin."),
    )
    await ask(client)
    assert "/api/v1/guest/kb/search" not in backend.paths()
    assert "VALIDATION_ERROR" in fake_llm.requests[1].messages[-1].content


# ---------- errors ----------


async def test_no_token_is_401_without_calling_anything(
    client: httpx.AsyncClient, backend: FakeBackend
) -> None:
    for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}):
        response = await client.post("/api/v1/chat", json={"message": "hi"}, headers=headers)
        assert response.status_code == 401
    assert backend.calls == []


async def test_backend_401_is_401(client: httpx.AsyncClient, backend: FakeBackend) -> None:
    response = await client.post(
        "/api/v1/chat", json={"message": "hi"}, headers={"Authorization": "Bearer revoked"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_quota_429_keeps_retry_after(client: httpx.AsyncClient, backend: FakeBackend) -> None:
    backend.overrides["/api/v1/guest/chat/quota"] = lambda r: httpx.Response(
        429,
        json={"error": {"code": "RATE_LIMITED", "message": "chờ chút"}},
        headers={"Retry-After": "37"},
    )
    response = await ask(client)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "37"
    assert response.json()["error"]["message"] == "chờ chút"


async def test_chat_disabled_is_503_and_uses_no_quota(
    client: httpx.AsyncClient, backend: FakeBackend, fake_llm: FakeLLMClient
) -> None:
    backend.chat_enabled = False
    response = await ask(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAT_DISABLED"
    assert "/api/v1/guest/chat/quota" not in backend.paths()
    assert fake_llm.requests == []


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [(LLMTimeout("slow"), 504, "LLM_TIMEOUT"), (LLMError("boom"), 503, "LLM_UNAVAILABLE")],
)
async def test_llm_failures(
    client: httpx.AsyncClient,
    fake_llm: FakeLLMClient,
    backend: FakeBackend,
    failure: Exception,
    status: int,
    code: str,
) -> None:
    fake_llm.queue(failure)
    response = await ask(client)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert not any(r.method == "POST" and r.url.path.endswith("/messages") for r in backend.calls)


async def test_the_whole_turn_has_a_time_limit(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_api, "TOTAL_TIMEOUT_SECONDS", 0.05)

    async def slow(_request: object) -> LLMResponse:
        await asyncio.sleep(1)
        return LLMResponse(text="late")

    monkeypatch.setattr(fake_llm, "generate", slow)
    response = await ask(client)
    assert response.status_code == 504


async def test_backend_down_is_503(client: httpx.AsyncClient, backend: FakeBackend) -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    backend.overrides["/api/v1/guest/me"] = down
    response = await ask(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "BACKEND_UNAVAILABLE"


@pytest.mark.parametrize(
    "body",
    [
        {"message": "hi", "room_id": "202"},
        {"message": ""},
        {"message": "x" * 1001},
        {"message": "hi", "client_message_id": "not-a-uuid"},
        {},
    ],
)
async def test_bad_bodies_are_400(client: httpx.AsyncClient, body: dict) -> None:
    response = await client.post("/api/v1/chat", json=body, headers=AUTH)
    assert response.status_code == 400


async def test_no_debug_in_prod(fake_llm: FakeLLMClient, backend: FakeBackend) -> None:
    settings = make_settings(app_env="prod", llm_provider="gemini", gemini_api_key="k" * 20)
    app = create_app(
        settings,
        llm=fake_llm,
        backend=BackendClient("http://backend", transport=httpx.MockTransport(backend)),
    )
    fake_llm.queue(LLMResponse(text="draft"), final("Chào Quý khách."))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as prod:
        body = (await ask(prod, "Xin chào")).json()
    assert "debug" not in body
    assert body["reply"] == "Chào Quý khách."


async def test_a_failed_lookup_reaches_the_model_as_an_upstream_error(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    backend.overrides["/api/v1/guest/kb/search"] = lambda r: httpx.Response(
        500, json={"error": {"code": "INTERNAL_ERROR", "message": "x"}}
    )
    fake_llm.queue(
        tool_call(topic="BREAKFAST", query="giờ ăn sáng"),
        LLMResponse(text="draft"),
        final("Xin lỗi, hiện tôi chưa tra được thông tin.", ["CALL_RECEPTION"]),
    )
    response = await ask(client)
    assert response.status_code == 200
    assert "UPSTREAM_ERROR" in fake_llm.requests[1].messages[-1].content
    assert backend.saved()["tool_trace"][0]["found"] is False


async def test_a_session_revoked_mid_chat_is_401(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: FakeBackend
) -> None:
    backend.overrides["/api/v1/guest/kb/search"] = lambda r: httpx.Response(
        401, json={"error": {"code": "UNAUTHORIZED", "message": "x"}}
    )
    fake_llm.queue(tool_call(topic="BREAKFAST", query="giờ ăn sáng"))
    response = await ask(client)
    assert response.status_code == 401
    assert not any(r.method == "POST" and r.url.path.endswith("/messages") for r in backend.calls)
