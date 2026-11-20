"""Shared pieces of the concierge-actions integration tests: a stateful fake backend-api and
helpers that script the model (FakeLLMClient)."""

import json
from typing import Any

import httpx

from app.llm.base import LLMResponse, ToolCall
from app.llm.fake import FakeLLMClient
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
            self.calls.pop()  # FakeBackend records it again
            response = super().__call__(request)
            data = response.json()
            data["status"] = self.status
            return httpx.Response(200, json=data)
        self.calls.pop()  # FakeBackend records it again
        return super().__call__(request)

    def posts(self, path: str) -> list[httpx.Request]:
        return [r for r in self.created if r.url.path == path]

    def last_trace(self) -> list[dict[str, Any]]:
        return self.lines[-1]["tool_trace"] or []


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
