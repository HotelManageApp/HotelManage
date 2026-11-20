"""`get_my_requests` (docs/chatbot-tools-spec.md §4.6): the current stay's own food orders,
housekeeping requests and checkout request, newest first. Read-only; only the fields a guest sees.
The stay is the token's — there is no argument to ask about another one (C4.1).
"""

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.concierge.tools.base import Tool
from app.core.backend_client import BackendClient
from app.llm.base import ToolSpec

Kind = Literal["FOOD_ORDER", "HOUSEKEEPING", "CHECKOUT", "ALL"]


class MyRequestsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind = "ALL"
    limit: int = Field(default=5, ge=1, le=10)


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(Kind.__args__)},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "additionalProperties": False,
}

SPEC = ToolSpec(
    name="get_my_requests",
    description=(
        "The guest's own food orders, housekeeping requests and check-out request with their "
        "current status, newest first. Use it when the guest asks where their order or request is."
    ),
    input_schema=SCHEMA,
)


def _order(o: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "FOOD_ORDER",
        "id": o.get("id"),
        "status": o.get("status"),
        "created_at": o.get("created_at"),
        "items": [
            {"name": i.get("name"), "quantity": i.get("quantity")} for i in o.get("items", [])
        ],
        "total_vnd": o.get("total_vnd"),
        "estimated_minutes": o.get("estimated_minutes"),
        "cancel_reason": o.get("cancel_reason"),
    }


def _housekeeping(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "HOUSEKEEPING",
        "id": r.get("id"),
        "type": r.get("type"),
        "status": r.get("status"),
        "created_at": r.get("created_at"),
        "amenities": r.get("amenities", []),
        "preferred_time": r.get("preferred_time"),
        "assignee": r.get("assignee"),
        "cancel_reason": r.get("cancel_reason"),
    }


def _checkout(c: dict[str, Any]) -> dict[str, Any]:
    bill = c.get("bill") or {}
    return {
        "kind": "CHECKOUT",
        "id": c.get("id"),
        "status": c.get("status"),
        "created_at": c.get("created_at"),
        "total_vnd": bill.get("total_vnd"),  # only once reception verified the bill
        "reject_reason": c.get("reject_reason"),
    }


async def _none() -> None:
    return None


async def _run(
    backend: BackendClient, token: str, args: MyRequestsArgs, lang: str
) -> dict[str, Any]:
    want = {args.kind} if args.kind != "ALL" else {"FOOD_ORDER", "HOUSEKEEPING", "CHECKOUT"}
    orders, housekeeping, checkout = await asyncio.gather(
        backend.my_orders(token) if "FOOD_ORDER" in want else _none(),
        backend.my_housekeeping(token) if "HOUSEKEEPING" in want else _none(),
        backend.current_checkout(token) if "CHECKOUT" in want else _none(),
    )
    requests = [
        *(_order(o) for o in orders or []),
        *(_housekeeping(r) for r in housekeeping or []),
        *([_checkout(checkout)] if checkout else []),
    ]
    requests.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return {"requests": requests[: args.limit]}


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    return {"requests": [f"{r['kind']}:{r['status']}" for r in data.get("requests", [])]}


TOOL = Tool(spec=SPEC, args_model=MyRequestsArgs, runner=_run, summarize=_summary)
