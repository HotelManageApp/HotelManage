"""`get_available_menu` (docs/chatbot-tools-spec.md §4.2): the room-service menu with the
server's prices and the kitchen's hours. Read-only; prices shown to the guest come from here (C2.4).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.concierge.tools.base import Tool
from app.core.backend_client import BackendClient
from app.llm.base import ToolSpec


class MenuArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, max_length=40, pattern=r"^[A-Za-z_]+$")
    search: str | None = Field(default=None, min_length=1, max_length=100)


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "description": "Lọc theo nhóm, VD BREAKFAST, MAIN, DRINK. Bỏ trống = tất cả",
        },
        "search": {"type": "string", "maxLength": 100},
    },
    "additionalProperties": False,
}

SPEC = ToolSpec(
    name="get_available_menu",
    description=(
        "The in-room dining menu: dishes with item_id, price_vnd and availability, the service "
        "hours and whether the kitchen takes orders now. Use it before talking about dishes or "
        "prices; never quote a price that is not in its result."
    ),
    input_schema=SCHEMA,
)


async def _run(backend: BackendClient, token: str, args: MenuArgs, lang: str) -> dict[str, Any]:
    data = await backend.menu(token, category=args.category, search=args.search)
    # Exactly the tool's output shape (§4.2); the backend's category list is not needed.
    return {
        "service_hours": data.get("service_hours"),
        "is_open_now": bool(data.get("is_open_now")),
        "items": [
            {
                "item_id": item.get("item_id"),
                "name": item.get("name"),
                "category": item.get("category"),
                "price_vnd": item.get("price_vnd"),
                "available": bool(item.get("available")),
                "description": item.get("description"),
            }
            for item in data.get("items", [])
        ],
    }


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    return {"items": len(data.get("items", [])), "is_open_now": data.get("is_open_now")}


TOOL = Tool(spec=SPEC, args_model=MenuArgs, runner=_run, summarize=_summary)
