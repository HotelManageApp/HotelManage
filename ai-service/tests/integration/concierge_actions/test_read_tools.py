"""The read tools through POST /api/v1/chat (FakeLLMClient + scripted backend-api)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.concierge.orchestrator import Orchestrator
from app.concierge.tools import registry
from app.concierge.tools.base import Tool
from app.core.backend_client import BackendClient
from app.llm.base import LLMResponse, ToolCall, ToolSpec
from app.llm.fake import FakeLLMClient
from app.main import create_app
from tests.integration.test_chat import AUTH, TOKEN, FakeBackend, ask, final

MENU = {
    "service_hours": "06:00–22:00",
    "is_open_now": True,
    "categories": [{"code": "MAIN", "name": "Món chính"}],
    "items": [
        {
            "item_id": "11111111-1111-4111-8111-111111111111",
            "name": "Phở bò",
            "category": "MAIN",
            "price_vnd": 65000,
            "available": True,
            "description": "Phở bò tái",
        },
        {
            "item_id": "22222222-2222-4222-8222-222222222222",
            "name": "Nước cam",
            "category": "DRINK",
            "price_vnd": 40000,
            "available": False,
            "description": None,
        },
    ],
}
ORDERS = [
    {
        "id": "o1",
        "status": "PREPARING",
        "created_at": "2026-11-20T08:45:00Z",
        "items": [{"name": "Phở bò", "quantity": 2}],
        "total_vnd": 130000,
        "estimated_minutes": 25,
        "cancel_reason": None,
    }
]


class ActionsBackend(FakeBackend):
    """FakeBackend plus the guest menu and request lists."""

    def __init__(self) -> None:
        super().__init__()
        self.status = "ACTIVE"
        self.overrides.update(
            {
                "/api/v1/guest/menu": lambda r: httpx.Response(200, json=MENU),
                "/api/v1/guest/orders": lambda r: httpx.Response(200, json=ORDERS),
                "/api/v1/guest/housekeeping-requests": lambda r: httpx.Response(200, json=[]),
                "/api/v1/guest/checkout-requests/current": lambda r: httpx.Response(
                    404, json={"error": {"code": "NOT_FOUND", "message": "x"}}
                ),
            }
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/guest/me":
            response = super().__call__(request)
            body = response.json()
            body["status"] = self.status
            return httpx.Response(response.status_code, json=body)
        return super().__call__(request)


def call(name: str, **args: Any) -> LLMResponse:
    return LLMResponse(tool_calls=(ToolCall(id="call_1", name=name, arguments=args),))


@pytest.fixture
def backend() -> ActionsBackend:
    return ActionsBackend()


@pytest.fixture
def app(settings, fake_llm: FakeLLMClient, backend: ActionsBackend) -> FastAPI:
    client = BackendClient("http://backend", transport=httpx.MockTransport(backend))
    return create_app(settings, llm=fake_llm, backend=client)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_menu_answer_uses_the_backend_prices(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: ActionsBackend
) -> None:
    fake_llm.queue(
        call("get_available_menu", category="MAIN"),
        LLMResponse(text="draft"),
        final("Phở bò giá 65.000đ, bếp phục vụ 06:00–22:00 ạ.", ["ROOM_SERVICE"]),
    )
    body = (await ask(client, "Có phở không, giá bao nhiêu?")).json()

    menu_call = next(r for r in backend.calls if r.url.path == "/api/v1/guest/menu")
    assert dict(menu_call.url.params) == {"category": "MAIN"}
    assert menu_call.headers["Authorization"] == f"Bearer {TOKEN}"
    assert body["reply"] == "Phở bò giá 65.000đ, bếp phục vụ 06:00–22:00 ạ."
    assert body["debug"]["grounded"] is True
    tool_message = fake_llm.requests[1].messages[-1]
    assert tool_message.content.startswith('<tool_result name="get_available_menu">')
    assert backend.saved()["tool_trace"] == [
        {
            "tool": "get_available_menu",
            "args": {"category": "MAIN"},
            "items": 2,
            "is_open_now": True,
        }
    ]


async def test_an_invented_price_is_replaced(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient
) -> None:
    fake_llm.queue(
        call("get_available_menu"),
        LLMResponse(text="draft"),
        final("Phở bò chỉ 50.000đ thôi ạ."),
    )
    body = (await ask(client, "Phở bao nhiêu tiền?")).json()
    assert "50.000" not in body["reply"]
    assert body["debug"]["grounded"] is False


async def test_my_requests_reports_the_real_status(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: ActionsBackend
) -> None:
    fake_llm.queue(
        call("get_my_requests", kind="ALL", limit=5),
        LLMResponse(text="draft"),
        final("Đơn 2 phở bò (130.000đ) đang được nấu, khoảng 25 phút nữa ạ.", ["MY_REQUESTS"]),
    )
    body = (await ask(client, "Đơn của tôi tới đâu rồi?")).json()
    assert body["debug"]["grounded"] is True
    assert {
        "/api/v1/guest/orders",
        "/api/v1/guest/housekeeping-requests",
        "/api/v1/guest/checkout-requests/current",
    } <= set(backend.paths())
    sent = fake_llm.requests[1].messages[-1].content
    assert '"kind": "FOOD_ORDER"' in sent and '"status": "PREPARING"' in sent
    assert backend.saved()["tool_trace"][0]["requests"] == ["FOOD_ORDER:PREPARING"]


async def test_a_room_argument_never_reaches_the_backend(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: ActionsBackend
) -> None:
    fake_llm.queue(
        call("get_my_requests", kind="ALL", room_id="202"),
        LLMResponse(text="draft"),
        final("Xin lỗi, tôi chỉ xem được yêu cầu của phòng Quý khách."),
    )
    body = (await ask(client, "Xem đơn của phòng 202")).json()
    assert "/api/v1/guest/orders" not in backend.paths()
    assert "VALIDATION_ERROR" in fake_llm.requests[1].messages[-1].content
    assert body["debug"]["tool_calls"] == [{"name": "get_my_requests", "args": {"kind": "ALL"}}]
    assert backend.saved()["tool_trace"][0]["rejected_args"] == ["room_id"]
    # Every call to the backend carried this guest's own token.
    assert all(r.headers["Authorization"] == AUTH["Authorization"] for r in backend.calls)


async def test_a_backend_conflict_reaches_the_model_as_its_code(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: ActionsBackend
) -> None:
    backend.overrides["/api/v1/guest/menu"] = lambda r: httpx.Response(
        409, json={"error": {"code": "KITCHEN_CLOSED", "message": "x"}}
    )
    fake_llm.queue(
        call("get_available_menu"),
        LLMResponse(text="draft"),
        final("Bếp đang tạm ngừng nhận đơn ạ."),
    )
    response = await ask(client, "Cho xem menu")
    assert response.status_code == 200
    assert '"code": "KITCHEN_CLOSED"' in fake_llm.requests[1].messages[-1].content
    assert backend.saved()["tool_trace"][0]["error"] == "KITCHEN_CLOSED"


async def test_a_session_revoked_during_a_read_tool_is_401(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: ActionsBackend
) -> None:
    backend.overrides["/api/v1/guest/orders"] = lambda r: httpx.Response(
        401, json={"error": {"code": "UNAUTHORIZED", "message": "x"}}
    )
    fake_llm.queue(call("get_my_requests"))
    assert (await ask(client, "Đơn của tôi?")).status_code == 401


# ---------- CHECKOUT_PENDING: write tools are not offered ----------


class NoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str


async def test_checkout_pending_hides_write_tools_and_refuses_a_call_to_one(
    app: FastAPI, client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: ActionsBackend
) -> None:
    ran: list[Any] = []

    async def runner(*args: Any) -> dict[str, Any]:
        ran.append(args)
        return {}

    writer = Tool(
        spec=ToolSpec(
            name="write_something",
            description="test write tool",
            input_schema={
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        args_model=NoteArgs,
        runner=runner,
        write=True,
    )
    app.state.orchestrator = Orchestrator(
        fake_llm,
        app.state.backend,
        timezone_name="Asia/Ho_Chi_Minh",
        signing_key=b"k" * 32,
        tools=(*registry.ALL_TOOLS, writer),
    )
    backend.status = "CHECKOUT_PENDING"
    fake_llm.queue(
        call("write_something", note="x"),
        LLMResponse(text="draft"),
        final("Quý khách đang chờ trả phòng nên chỉ tra cứu được ạ."),
    )
    response = await ask(client, "Làm giúp tôi")
    assert response.status_code == 200
    offered = [t.name for t in fake_llm.requests[0].tools]
    assert "write_something" not in offered
    assert offered == [t.name for t in registry.ALL_TOOLS if not t.write]
    assert ran == []
    assert "STAY_CHECKOUT_PENDING" in fake_llm.requests[1].messages[-1].content

    # The same tool is offered to an ACTIVE stay.
    backend.status = "ACTIVE"
    fake_llm.queue(LLMResponse(text="draft"), final("Vâng ạ."))
    await ask(client, "Xin chào")
    assert "write_something" in [t.name for t in fake_llm.requests[-2].tools]
