"""Tool flags, argument checks and backend error mapping (SPEC-concierge-actions, "Bộ tool")."""

from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from app.concierge import grounding
from app.concierge.tools import menu, my_requests, registry
from app.concierge.tools.base import Tool, backend_error_code, execute
from app.core.backend_client import (
    BackendClient,
    BackendError,
    BackendRateLimited,
    BackendUnauthorized,
    BackendUnavailable,
)
from app.llm.base import ToolSpec


class NoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str


class Recorder:
    def __init__(self, result: Any = None, raises: Exception | None = None) -> None:
        self.calls: list[Any] = []
        self.result, self.raises = result, raises

    async def __call__(self, backend: Any, token: str, args: Any, lang: str) -> Any:
        self.calls.append(args)
        if self.raises:
            raise self.raises
        return self.result if self.result is not None else {"done": True}


def tool(runner: Recorder, *, write: bool = False) -> Tool:
    spec = ToolSpec(
        name="write_note" if write else "read_note",
        description="test",
        input_schema={
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
            "additionalProperties": False,
        },
    )
    return Tool(spec=spec, args_model=NoteArgs, runner=runner, write=write)


def unreachable(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected backend call {request.url.path}")


BACKEND = BackendClient("http://backend", transport=httpx.MockTransport(unreachable))


# ---------- flags ----------


def test_the_read_tools_are_read_only_and_ungated() -> None:
    for t in registry.ALL_TOOLS:
        assert t.write is False and t.requires_confirmation is False, t.name
    assert [t.name for t in registry.ALL_TOOLS] == [
        "get_hotel_info_and_guide",
        "get_available_menu",
        "get_my_requests",
    ]


def test_write_tools_are_hidden_while_checkout_is_pending() -> None:
    tools = (tool(Recorder()), tool(Recorder(), write=True))
    assert [t.name for t in registry.available("ACTIVE", tools)] == ["read_note", "write_note"]
    assert [t.name for t in registry.available("CHECKOUT_PENDING", tools)] == ["read_note"]
    assert registry.available("CHECKOUT_PENDING") == registry.ALL_TOOLS


def test_no_tool_schema_has_a_room_or_stay_field() -> None:
    for t in registry.ALL_TOOLS:
        schema = t.spec.input_schema
        assert schema["additionalProperties"] is False, t.name
        assert not {"room_id", "stay_id", "guest_id", "room"} & set(schema["properties"]), t.name
        assert t.args_model.model_config.get("extra") == "forbid", t.name


# ---------- arguments ----------


@pytest.mark.parametrize("extra", ["room_id", "stay_id", "price_vnd"])
async def test_unknown_arguments_are_refused_before_the_backend(extra: str) -> None:
    runner = Recorder()
    run = await execute(tool(runner), BACKEND, "tok", {"note": "x", extra: "202"}, "vi")
    assert runner.calls == []
    assert run.output["ok"] is False and run.error_code == "VALIDATION_ERROR"
    assert run.rejected_args == [extra]
    assert run.args == {"note": "x"}
    assert run.trace()["rejected_args"] == [extra] and run.trace()["error"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("raw", [{}, {"note": 3}, "not an object"])
async def test_invalid_values_are_refused_before_the_backend(raw: Any) -> None:
    runner = Recorder()
    run = await execute(tool(runner), BACKEND, "tok", raw, "vi")
    assert runner.calls == [] and run.error_code == "VALIDATION_ERROR"


async def test_a_valid_call_returns_the_data() -> None:
    runner = Recorder({"value": 1})
    run = await execute(tool(runner), BACKEND, "tok", {"note": "x"}, "vi")
    assert run.ok and run.output == {"ok": True, "data": {"value": 1}}
    assert run.trace() == {"tool": "read_note", "args": {"note": "x"}}


# ---------- backend errors ----------


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (BackendError(400, "VALIDATION_ERROR"), "VALIDATION_ERROR"),
        (BackendError(403, "FORBIDDEN"), "FORBIDDEN"),
        (BackendError(404, "NOT_FOUND"), "NOT_FOUND"),
        (BackendError(409, "ITEM_UNAVAILABLE"), "ITEM_UNAVAILABLE"),
        (BackendError(409, "STAY_CHECKOUT_PENDING"), "STAY_CHECKOUT_PENDING"),
        (BackendError(409, ""), "CONFLICT"),
        (BackendRateLimited(30), "UPSTREAM_ERROR"),
        (BackendUnavailable(503, "INTERNAL_ERROR"), "UPSTREAM_ERROR"),
        (BackendUnavailable(0, "TIMEOUT"), "UPSTREAM_ERROR"),
        (BackendError(418, "TEAPOT"), "UPSTREAM_ERROR"),
    ],
)
async def test_backend_errors_map_to_tool_codes(exc: BackendError, code: str) -> None:
    assert backend_error_code(exc) == code
    run = await execute(tool(Recorder(raises=exc)), BACKEND, "tok", {"note": "x"}, "vi")
    assert run.output["ok"] is False and run.error_code == code


async def test_a_revoked_session_is_not_swallowed() -> None:
    runner = Recorder(raises=BackendUnauthorized(401, "UNAUTHORIZED"))
    with pytest.raises(BackendUnauthorized):
        await execute(tool(runner), BACKEND, "tok", {"note": "x"}, "vi")


# ---------- the read tools against a scripted backend ----------


def client_for(routes: dict[str, httpx.Response]) -> tuple[BackendClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        missing = httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "x"}})
        return routes.get(request.url.path, missing)

    return BackendClient("http://backend", transport=httpx.MockTransport(handle)), seen


MENU = {
    "service_hours": "06:00–22:00",
    "is_open_now": True,
    "categories": [{"code": "MAIN", "name": "Món chính"}],
    "items": [
        {
            "item_id": "i1",
            "name": "Phở bò",
            "category": "MAIN",
            "price_vnd": 65000,
            "available": True,
            "description": None,
        }
    ],
}


async def test_menu_passes_filters_and_returns_the_spec_shape() -> None:
    backend, seen = client_for({"/api/v1/guest/menu": httpx.Response(200, json=MENU)})
    run = await execute(menu.TOOL, backend, "tok", {"category": "MAIN", "search": "phở"}, "vi")
    assert dict(seen[0].url.params) == {"category": "MAIN", "search": "phở"}
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert run.output["data"] == {
        "service_hours": "06:00–22:00",
        "is_open_now": True,
        "items": MENU["items"],
    }
    assert run.trace() == {
        "tool": "get_available_menu",
        "args": {"category": "MAIN", "search": "phở"},
        "items": 1,
        "is_open_now": True,
    }


async def test_menu_without_filters_sends_none() -> None:
    backend, seen = client_for({"/api/v1/guest/menu": httpx.Response(200, json=MENU)})
    await execute(menu.TOOL, backend, "tok", {}, "vi")
    assert dict(seen[0].url.params) == {}


def order(order_id: str, at: str, status: str = "PREPARING") -> dict[str, Any]:
    return {
        "id": order_id,
        "status": status,
        "created_at": at,
        "items": [{"name": "Phở bò", "quantity": 2, "unit_price_vnd": 65000}],
        "total_vnd": 130000,
        "estimated_minutes": 25,
        "cancel_reason": None,
        "source": "APP",
        "version": 3,
    }


HK = {
    "id": "h1",
    "type": "AMENITY",
    "status": "ASSIGNED",
    "created_at": "2026-11-20T08:30:00Z",
    "amenities": [{"code": "TOWEL", "quantity": 2}],
    "preferred_time": None,
    "assignee": "Lan",
    "cancel_reason": None,
    "note": "x",
    "version": 1,
}
CHECKOUT = {
    "id": "c1",
    "status": "BILLING_VERIFIED",
    "created_at": "2026-11-20T09:00:00Z",
    "feedback_rating": 5,
    "reject_reason": None,
    "bill": {"total_vnd": 1340000, "lines": []},
}


async def test_my_requests_merges_newest_first_with_display_fields_only() -> None:
    orders = [order("o2", "2026-11-20T08:45:00Z"), order("o1", "2026-11-20T07:00:00Z")]
    backend, seen = client_for(
        {
            "/api/v1/guest/orders": httpx.Response(200, json=orders),
            "/api/v1/guest/housekeeping-requests": httpx.Response(200, json=[HK]),
            "/api/v1/guest/checkout-requests/current": httpx.Response(200, json=CHECKOUT),
        }
    )
    run = await execute(my_requests.TOOL, backend, "tok", {}, "vi")
    requests = run.output["data"]["requests"]
    assert [(r["kind"], r["id"]) for r in requests] == [
        ("CHECKOUT", "c1"),
        ("FOOD_ORDER", "o2"),
        ("HOUSEKEEPING", "h1"),
        ("FOOD_ORDER", "o1"),
    ]
    assert requests[1]["items"] == [{"name": "Phở bò", "quantity": 2}]
    assert "version" not in requests[1] and "note" not in requests[2]
    assert requests[0]["total_vnd"] == 1340000
    assert all(r.headers["Authorization"] == "Bearer tok" for r in seen)
    assert run.trace()["requests"][0] == "CHECKOUT:BILLING_VERIFIED"


async def test_my_requests_by_kind_and_limit_and_no_checkout_yet() -> None:
    orders = [order(f"o{n}", f"2026-11-20T0{n}:00:00Z") for n in range(1, 4)]
    backend, seen = client_for({"/api/v1/guest/orders": httpx.Response(200, json=orders)})
    run = await execute(my_requests.TOOL, backend, "tok", {"kind": "FOOD_ORDER", "limit": 2}, "vi")
    assert [r["id"] for r in run.output["data"]["requests"]] == ["o3", "o2"]
    assert [r.url.path for r in seen] == ["/api/v1/guest/orders"]

    run = await execute(my_requests.TOOL, backend, "tok", {"kind": "CHECKOUT"}, "vi")
    assert run.ok and run.output["data"]["requests"] == []  # 404: no request yet


@pytest.mark.parametrize("args", [{"limit": 0}, {"limit": 11}, {"kind": "ROOM"}])
async def test_my_requests_rejects_bad_values(args: dict[str, Any]) -> None:
    backend, seen = client_for({})
    run = await execute(my_requests.TOOL, backend, "tok", args, "vi")
    assert run.error_code == "VALIDATION_ERROR" and seen == []


# ---------- grounding sees the new sources ----------


def test_grounding_accepts_prices_from_menu_and_order_lines() -> None:
    sources = ['{"unit_price_vnd": 65000, "line_total_vnd": 130000, "total_vnd": 170000}']
    assert grounding.unsupported("2 phở 130.000đ, tổng 170.000đ (65k/tô)", sources) == set()
    assert grounding.unsupported("tổng 180.000đ", sources) == {grounding.Fact("price", "180000")}
