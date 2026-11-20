"""`create_room_service_order` (docs/chatbot-tools-spec.md §4.3). Gated: the first call only
previews the order (`POST /guest/orders/preview`, nothing stored) and the guest sees the server's
summary; the order is placed once they confirm (`POST /guest/orders`, Idempotency-Key = the
pending action id). Prices and totals always come from the backend (C2.4, C2.5).
"""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.concierge.confirmation import normalize_order
from app.concierge.tools.base import Gate, Tool
from app.core.backend_client import BackendClient
from app.llm.base import ToolSpec


class OrderLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    quantity: int = Field(ge=1, le=20)
    note: str | None = Field(default=None, max_length=200)


class OrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OrderLine] = Field(min_length=1, max_length=20)
    order_note: str | None = Field(default=None, max_length=300)
    # Ignored by the server: the gate, not this flag, decides when the order is placed.
    guest_confirmed: bool | None = None


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "format": "uuid"},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 20},
                    "note": {"type": "string", "maxLength": 200},
                },
                "required": ["item_id", "quantity"],
                "additionalProperties": False,
            },
        },
        "order_note": {"type": "string", "maxLength": 300},
        "guest_confirmed": {
            "type": "boolean",
            "const": True,
            "description": "Khách đã xác nhận bản tóm tắt",
        },
    },
    "required": ["items", "guest_confirmed"],
    "additionalProperties": False,
}

SPEC = ToolSpec(
    name="create_room_service_order",
    description=(
        "Order food for the guest's room. Use item_id values from get_available_menu. The server "
        "first shows the guest a summary with prices and asks them to confirm; the order is only "
        "placed after they confirm, by calling this tool again with the same items."
    ),
    input_schema=SCHEMA,
)


def _payload(args: OrderArgs) -> dict[str, Any]:
    return normalize_order([line.model_dump(mode="json") for line in args.items], args.order_note)


def _body(args: OrderArgs) -> dict[str, Any]:
    payload = _payload(args)
    return {
        "items": [
            {"item_id": line["item_id"], "quantity": line["quantity"], "note": line["note"] or None}
            for line in payload["items"]
        ],
        "order_note": payload["order_note"] or None,
        "source": "CHATBOT",
    }


async def _preview(
    backend: BackendClient, token: str, args: OrderArgs, lang: str
) -> dict[str, Any]:
    data = await backend.preview_order(token, _body(args))
    return {
        "items": data.get("items", []),
        "total_vnd": data.get("total_vnd"),
        "order_note": _payload(args)["order_note"] or None,
    }


async def _place(
    backend: BackendClient, token: str, args: OrderArgs, lang: str, *, idempotency_key: str
) -> dict[str, Any]:
    order = await backend.create_order(token, _body(args), idempotency_key=idempotency_key)
    return {
        "order_id": order.get("id"),
        "status": order.get("status"),
        "items": [
            {
                "name": i.get("name"),
                "quantity": i.get("quantity"),
                "unit_price_vnd": i.get("unit_price_vnd"),
                "line_total_vnd": i.get("line_total_vnd"),
            }
            for i in order.get("items", [])
        ],
        "total_vnd": order.get("total_vnd"),
        "estimated_minutes": order.get("estimated_minutes"),
        "created_at": order.get("created_at"),
    }


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    return {"order_id": data.get("order_id"), "status": data.get("status")} if data else {}


TOOL = Tool(
    spec=SPEC,
    args_model=OrderArgs,
    runner=_place,
    write=True,
    gate=Gate(kind="FOOD_ORDER", payload=_payload, preview=_preview),
    summarize=_summary,
)
