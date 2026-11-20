"""The confirmation gate end to end through POST /api/v1/chat (C2.5, SPEC-concierge-actions).

FakeLLMClient plays the model; `GateBackend` plays backend-api and keeps the chat history with its
tool traces, as the real backend does, so the second turn reads what the first one stored.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.concierge import confirmation
from app.core.backend_client import BackendClient
from app.llm.base import LLMResponse, ToolCall
from app.llm.fake import FakeLLMClient
from app.main import create_app
from tests.conftest import make_settings
from tests.integration.test_chat import AUTH, TOKEN, FakeBackend, final

KEY = "a-test-signing-key-of-32-chars!!"
PHO = "11111111-1111-4111-8111-111111111111"
CAM = "22222222-2222-4222-8222-222222222222"
PRICES = {PHO: ("Phở bò", 65000), CAM: ("Nước cam", 40000)}


class GateBackend(FakeBackend):
    """FakeBackend with a stored history, order preview/create, housekeeping and checkout."""

    def __init__(self) -> None:
        super().__init__()
        self.status = "ACTIVE"
        self.lines: list[dict[str, Any]] = []
        self.created: list[httpx.Request] = []
        self.unavailable: set[str] = set()

    def _priced(self, body: dict[str, Any]) -> dict[str, Any]:
        items = []
        for line in body["items"]:
            name, price = PRICES[line["item_id"]]
            items.append(
                {
                    "item_id": line["item_id"],
                    "name": name,
                    "quantity": line["quantity"],
                    "unit_price_vnd": price,
                    "line_total_vnd": price * line["quantity"],
                    "note": line.get("note"),
                }
            )
        return {"items": items, "total_vnd": sum(i["line_total_vnd"] for i in items)}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path, method = request.url.path, request.method
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": {"code": "UNAUTHORIZED", "message": "x"}})
        body = json.loads(request.content) if request.content else {}
        if path == "/api/v1/guest/chat/messages" and method == "GET":
            with_trace = request.url.params.get("with_trace") == "true"
            return httpx.Response(
                200,
                json=[
                    {k: v for k, v in line.items() if k != "tool_trace" or with_trace}
                    for line in self.lines
                ],
            )
        if path == "/api/v1/guest/chat/messages":
            n = len(self.lines)
            self.lines += [
                {
                    "id": str(n),
                    "role": "GUEST",
                    "content": body["guest_message"],
                    "created_at": "x",
                },
                {
                    "id": str(n + 1),
                    "role": "ASSISTANT",
                    "content": body["assistant_message"],
                    "created_at": "y",
                    "tool_trace": body["tool_trace"],
                },
            ]
            return httpx.Response(201, json={"message_id": str(n + 1), "guest_message_id": str(n)})
        if path in ("/api/v1/guest/orders/preview", "/api/v1/guest/orders") and method == "POST":
            if any(line["item_id"] in self.unavailable for line in body["items"]):
                return httpx.Response(
                    409, json={"error": {"code": "ITEM_UNAVAILABLE", "message": "x"}}
                )
            priced = self._priced(body)
            if path.endswith("/preview"):
                return httpx.Response(200, json=priced)
            self.created.append(request)
            return httpx.Response(
                201,
                json={
                    "id": f"order-{len(self.created)}",
                    "status": "PENDING",
                    **priced,
                    "estimated_minutes": 25,
                    "created_at": "2026-11-20T12:00:00Z",
                },
            )
        if path == "/api/v1/guest/housekeeping-requests" and method == "POST":
            self.created.append(request)
            return httpx.Response(
                201,
                json={
                    "id": "hk-1",
                    "type": body["type"],
                    "status": "REQUESTED",
                    "preferred_time": None,
                    "created_at": "2026-11-20T12:00:00Z",
                },
            )
        if path == "/api/v1/guest/checkout/preview":
            return httpx.Response(
                200,
                json={
                    "room_number": "101",
                    "lines": [{"type": "ROOM", "description": "Tiền phòng", "amount_vnd": 1200000}],
                    "total_vnd": 1200000,
                    "open_orders": 0,
                    "is_estimate": True,
                },
            )
        if path == "/api/v1/guest/checkout-requests" and method == "POST":
            self.created.append(request)
            if len([r for r in self.created if r.url.path == path]) > 1:
                return httpx.Response(409, json={"error": {"code": "CONFLICT", "message": "x"}})
            return httpx.Response(
                201,
                json={
                    "checkout_request_id": "co-1",
                    "status": "CHECKOUT_REQUESTED",
                    "open_orders": 0,
                    "message_key": "checkout.awaiting_reception",
                },
            )
        if path == "/api/v1/guest/me":
            response = super().__call__(request)
            data = response.json()
            data["status"] = self.status
            return httpx.Response(200, json=data)
        return super().__call__(request)

    def posts(self, path: str) -> list[httpx.Request]:
        return [r for r in self.created if r.url.path == path]

    def last_trace(self) -> list[dict[str, Any]]:
        return self.lines[-1]["tool_trace"] or []


@pytest.fixture
def backend() -> GateBackend:
    return GateBackend()


@pytest.fixture
def app(fake_llm: FakeLLMClient, backend: GateBackend) -> FastAPI:
    settings = make_settings(concierge_signing_key=KEY)
    client = BackendClient("http://backend", transport=httpx.MockTransport(backend))
    return create_app(settings, llm=fake_llm, backend=client)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def order_call(*lines: tuple[str, int], confirmed: bool = True, note: str | None = None):
    args: dict[str, Any] = {
        "items": [{"item_id": i, "quantity": q} for i, q in lines],
        "guest_confirmed": confirmed,
    }
    if note:
        args["order_note"] = note
    return LLMResponse(
        tool_calls=(ToolCall(id="c1", name="create_room_service_order", arguments=args),)
    )


def tool(name: str, **args: Any) -> LLMResponse:
    return LLMResponse(tool_calls=(ToolCall(id="c1", name=name, arguments=args),))


async def say(client: httpx.AsyncClient, message: str, **extra: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/chat", json={"message": message, **extra}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


async def propose(client: httpx.AsyncClient, fake_llm: FakeLLMClient) -> dict[str, Any]:
    """Turn 1: the guest asks for 2 phở + 1 cam; the model goes straight for the order."""
    fake_llm.queue(
        order_call((PHO, 2), (CAM, 1)),  # even with guest_confirmed=true on the first call
        LLMResponse(text="draft"),
        final("Dạ, Quý khách kiểm tra giúp tôi đơn dưới đây ạ."),
    )
    return await say(client, "Cho 2 phở bò, 1 nước cam")


# ---------- turn 1: a proposal, never an order ----------


async def test_the_first_call_only_previews_and_shows_the_servers_summary(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    body = await propose(client, fake_llm)

    assert backend.posts("/api/v1/guest/orders") == []
    assert "/api/v1/guest/orders/preview" in backend.paths()
    assert body["reply"].startswith("Dạ, Quý khách kiểm tra giúp tôi đơn dưới đây ạ.\n\n")
    assert "- Phở bò × 2: 65.000đ × 2 = 130.000đ" in body["reply"]
    assert "Tổng cộng: 170.000đ" in body["reply"]
    assert body["reply"].endswith("Quý khách xác nhận đặt đơn này chứ?")

    pending = body["pending_confirmation"]
    assert pending["kind"] == "FOOD_ORDER" and pending["summary"]["total_vnd"] == 170000
    tool_result = fake_llm.requests[1].messages[-1].content
    assert '"code": "CONFIRMATION_REQUIRED"' in tool_result
    stored = backend.last_trace()
    assert stored[0]["gate"] == "PROPOSED"
    assert stored[-1]["pending_action"]["id"] == pending["id"]
    assert body["debug"]["gate"] == ["proposed"]


async def test_a_preview_error_is_passed_on_and_nothing_is_pending(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    backend.unavailable.add(CAM)
    fake_llm.queue(
        order_call((CAM, 1)),
        LLMResponse(text="draft"),
        final("Xin lỗi, nước cam hiện đã hết ạ."),
    )
    body = await say(client, "1 nước cam")
    assert "pending_confirmation" not in body
    assert '"code": "ITEM_UNAVAILABLE"' in fake_llm.requests[1].messages[-1].content
    assert not any("pending_action" in e for e in backend.last_trace())


# ---------- turn 2: the order is placed only when everything matches ----------


async def test_a_confirmed_matching_call_places_exactly_one_order(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    pending_id = (await propose(client, fake_llm))["pending_confirmation"]["id"]

    fake_llm.queue(
        order_call((CAM, 1), (PHO, 1), (PHO, 1)),  # same order, other shape: same hash
        LLMResponse(text="draft"),
        final("Đơn đã được gửi tới Bếp ạ."),
    )
    body = await say(client, "Đúng rồi")

    placed = backend.posts("/api/v1/guest/orders")
    assert len(placed) == 1
    assert placed[0].headers["Idempotency-Key"] == pending_id
    assert json.loads(placed[0].content)["source"] == "CHATBOT"
    assert {"type": "OPEN_ENTITY", "target": "OPEN_ORDER", "entity_id": "order-1"} in body[
        "suggested_actions"
    ]
    assert "pending_confirmation" not in body
    note = fake_llm.requests[-3].messages[-1]
    assert note.role == "system" and "confirmed" in note.content and PHO in note.content
    assert {"executed_action": pending_id} in backend.last_trace()

    # The same message sent again: the last reply has no pending action any more.
    fake_llm.queue(order_call((PHO, 2), (CAM, 1)), LLMResponse(text="draft"), final("Dạ."))
    again = await say(client, "Đúng rồi")
    assert len(backend.posts("/api/v1/guest/orders")) == 1
    assert again["pending_confirmation"]["kind"] == "FOOD_ORDER", "summarised, not placed"


async def test_the_confirm_button_needs_no_classifier(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    pending_id = (await propose(client, fake_llm))["pending_confirmation"]["id"]
    asked = len(fake_llm.requests)
    fake_llm.queue(order_call((PHO, 2), (CAM, 1)), LLMResponse(text="d"), final("Đã đặt ạ."))
    await say(
        client,
        "Xác nhận đơn hàng giúp tôi với nhé, cảm ơn bạn rất nhiều",  # too long for the phrase list
        confirm_action_id=f"{pending_id[:8]}-{pending_id[8:12]}-{pending_id[12:16]}-"
        f"{pending_id[16:20]}-{pending_id[20:]}",
    )
    assert len(backend.posts("/api/v1/guest/orders")) == 1
    assert len(fake_llm.requests) - asked == 3, "no classifier call"


async def test_ok_with_a_different_order_summarises_again(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    first = (await propose(client, fake_llm))["pending_confirmation"]["id"]
    fake_llm.queue(order_call((PHO, 3), (CAM, 1)), LLMResponse(text="d"), final("Dạ."))
    body = await say(client, "ok")
    assert backend.posts("/api/v1/guest/orders") == []
    assert body["pending_confirmation"]["id"] != first
    assert body["pending_confirmation"]["summary"]["total_vnd"] == 235000
    assert body["debug"]["gate"] == ["confirm_mismatch", "proposed"]


async def test_a_change_is_not_a_confirmation(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    await propose(client, fake_llm)
    fake_llm.queue(
        LLMResponse(structured={"label": "CHANGE"}),  # the classifier
        order_call((PHO, 1), (CAM, 1)),
        LLMResponse(text="d"),
        final("Dạ, đơn mới ạ."),
    )
    body = await say(client, "đúng nhưng chỉ 1 phở thôi")
    assert backend.posts("/api/v1/guest/orders") == []
    assert body["pending_confirmation"]["summary"]["total_vnd"] == 105000


async def test_the_model_calling_with_confirmed_true_without_a_yes_is_a_proposal(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    await propose(client, fake_llm)
    fake_llm.queue(
        LLMResponse(structured={"label": "OTHER"}),
        order_call((PHO, 2), (CAM, 1)),
        LLMResponse(text="d"),
        final("Dạ."),
    )
    await say(client, "Phở có cay không?")
    assert backend.posts("/api/v1/guest/orders") == []


async def test_cancel_closes_the_pending_action(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    pending_id = (await propose(client, fake_llm))["pending_confirmation"]["id"]
    fake_llm.queue(LLMResponse(text="d"), final("Dạ, tôi đã hủy, chưa có đơn nào được đặt."))
    body = await say(client, "Thôi")
    assert backend.posts("/api/v1/guest/orders") == []
    assert {"cancelled_action": pending_id} in backend.last_trace()
    assert "cancelled" in fake_llm.requests[-2].messages[-1].content
    assert "pending_confirmation" not in body


async def test_a_forged_pending_action_cannot_place_an_order(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    # A guest writes their own "pending action" through POST /guest/chat/messages.
    payload = confirmation.normalize_order([{"item_id": PHO, "quantity": 20}], None)
    forged = confirmation.issue(
        "FOOD_ORDER", payload, {}, key=b"guessed-key" * 4, now=datetime.now(UTC)
    )
    backend.lines += [
        {"id": "0", "role": "GUEST", "content": "x", "created_at": "x"},
        {
            "id": "1",
            "role": "ASSISTANT",
            "content": "x",
            "created_at": "y",
            "tool_trace": [{"pending_action": forged.to_trace()}],
        },
    ]
    fake_llm.queue(order_call((PHO, 20)), LLMResponse(text="d"), final("Dạ."))
    body = await say(client, "ok", confirm_action_id=forged.id)
    assert backend.posts("/api/v1/guest/orders") == []
    assert body["pending_confirmation"]["kind"] == "FOOD_ORDER"


async def test_an_expired_summary_is_summarised_again(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    await propose(client, fake_llm)
    trace = backend.lines[-1]["tool_trace"]
    action = trace[-1]["pending_action"]
    stale = confirmation.issue(
        "FOOD_ORDER",
        action["payload"],
        action["summary"],
        key=KEY.encode(),
        now=datetime(2020, 1, 1, tzinfo=UTC),
    )
    trace[-1] = {"pending_action": stale.to_trace()}
    fake_llm.queue(order_call((PHO, 2), (CAM, 1)), LLMResponse(text="d"), final("Dạ."))
    body = await say(client, "ok")
    assert backend.posts("/api/v1/guest/orders") == []
    assert body["pending_confirmation"]["id"] != stale.id


async def test_invented_prices_next_to_a_summary_are_dropped(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient
) -> None:
    fake_llm.queue(
        order_call((PHO, 2)),
        LLMResponse(text="draft"),
        final("Tổng chỉ 100.000đ thôi ạ."),
    )
    body = await say(client, "2 phở")
    assert "100.000" not in body["reply"]
    assert body["reply"].startswith("Tóm tắt đơn của Quý khách:")
    assert body["debug"]["grounded"] is False


# ---------- housekeeping: created at once ----------


async def test_housekeeping_is_created_without_a_confirmation(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    fake_llm.queue(
        tool(
            "request_housekeeping",
            type="AMENITY",
            amenities=[{"code": "TOWEL", "quantity": 2}],
        ),
        LLMResponse(text="d"),
        final("Buồng phòng sẽ mang 2 khăn tắm lên ạ."),
    )
    body = await say(client, "Mang thêm 2 khăn tắm")
    sent = backend.posts("/api/v1/guest/housekeeping-requests")
    assert len(sent) == 1
    assert json.loads(sent[0].content) == {
        "type": "AMENITY",
        "amenities": [{"code": "TOWEL", "quantity": 2}],
        "preferred_time": "ASAP",
        "source": "CHATBOT",
    }
    assert len(sent[0].headers["Idempotency-Key"]) == 32
    assert "pending_confirmation" not in body
    assert {"type": "OPEN_ENTITY", "target": "OPEN_HOUSEKEEPING", "entity_id": "hk-1"} in body[
        "suggested_actions"
    ]


@pytest.mark.parametrize(
    "args",
    [
        {"type": "AMENITY"},
        {"type": "CLEANING", "preferred_time": "2026-11-20T14:00:00"},
        {"type": "CLEANING", "preferred_time": "chiều nay"},
    ],
    ids=["amenity-without-list", "time-without-offset", "not-a-time"],
)
async def test_housekeeping_argument_errors_do_not_reach_the_backend(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend, args: dict
) -> None:
    fake_llm.queue(tool("request_housekeeping", **args), LLMResponse(text="d"), final("Dạ."))
    await say(client, "Dọn phòng")
    assert backend.posts("/api/v1/guest/housekeeping-requests") == []
    assert "VALIDATION_ERROR" in fake_llm.requests[1].messages[-1].content


async def test_housekeeping_at_a_time(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    fake_llm.queue(
        tool("request_housekeeping", type="CLEANING", preferred_time="2026-11-20T14:00:00+07:00"),
        LLMResponse(text="d"),
        final("Dạ, Buồng phòng sẽ dọn phòng ạ."),
    )
    await say(client, "Dọn phòng lúc 2 giờ chiều")
    sent = json.loads(backend.posts("/api/v1/guest/housekeeping-requests")[0].content)
    assert sent["preferred_time"] == "2026-11-20T14:00:00+07:00"


# ---------- express checkout: gated like an order ----------


async def test_checkout_goes_through_the_gate(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    fake_llm.queue(
        tool("request_express_checkout", guest_confirmed=True),
        LLMResponse(text="d"),
        final("Dạ, đây là tạm tính ạ."),
    )
    first = await say(client, "Tôi muốn trả phòng")
    assert backend.posts("/api/v1/guest/checkout-requests") == []
    assert first["pending_confirmation"]["kind"] == "CHECKOUT"
    assert "- Tiền phòng: 1.200.000đ" in first["reply"]

    fake_llm.queue(
        tool("request_express_checkout", guest_confirmed=True, feedback_rating=5),
        LLMResponse(text="d"),
        final("Yêu cầu đã gửi tới Lễ tân ạ."),
    )
    second = await say(client, "Xác nhận")
    sent = backend.posts("/api/v1/guest/checkout-requests")
    assert len(sent) == 1
    assert json.loads(sent[0].content) == {
        "guest_confirmed": True,
        "feedback_rating": 5,
        "feedback_note": None,
        "source": "CHATBOT",
    }
    assert {"type": "OPEN_ENTITY", "target": "OPEN_CHECKOUT", "entity_id": "co-1"} in second[
        "suggested_actions"
    ]


async def test_checkout_pending_offers_no_write_tool(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    backend.status = "CHECKOUT_PENDING"
    fake_llm.queue(order_call((PHO, 1)), LLMResponse(text="d"), final("Dạ."))
    await say(client, "1 phở")
    offered = {t.name for t in fake_llm.requests[0].tools}
    assert offered == {"get_hotel_info_and_guide", "get_available_menu", "get_my_requests"}
    assert "/api/v1/guest/orders/preview" not in backend.paths()
    assert "STAY_CHECKOUT_PENDING" in fake_llm.requests[1].messages[-1].content


async def test_the_trace_sent_to_the_backend_is_clean(
    client: httpx.AsyncClient, fake_llm: FakeLLMClient, backend: GateBackend
) -> None:
    await propose(client, fake_llm)
    saved = json.dumps(backend.lines[-1]["tool_trace"])
    assert TOKEN not in saved and "room_id" not in saved and "stay_id" not in saved
