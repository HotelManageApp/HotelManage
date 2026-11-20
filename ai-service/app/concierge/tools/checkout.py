"""`request_express_checkout` (docs/chatbot-tools-spec.md §4.5). Gated: the first call shows the
guest the backend's estimate (`GET /guest/checkout/preview`); the request is sent once they
confirm (`POST /guest/checkout-requests`). Reception then verifies the bill on the web.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.concierge.tools.base import Gate, Tool
from app.core.backend_client import BackendClient
from app.llm.base import ToolSpec


class CheckoutArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guest_confirmed: bool | None = None  # ignored: the gate decides
    feedback_rating: int | None = Field(default=None, ge=1, le=5)
    feedback_note: str | None = Field(default=None, max_length=500)


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "guest_confirmed": {"type": "boolean", "const": True},
        "feedback_rating": {"type": "integer", "minimum": 1, "maximum": 5},
        "feedback_note": {"type": "string", "maxLength": 500},
    },
    "required": ["guest_confirmed"],
    "additionalProperties": False,
}

SPEC = ToolSpec(
    name="request_express_checkout",
    description=(
        "Send the guest's express check-out request to reception. The server first shows the "
        "guest the estimated bill and asks them to confirm; the request is only sent after they "
        "confirm, by calling this tool again."
    ),
    input_schema=SCHEMA,
)


def _payload(args: CheckoutArgs) -> dict[str, Any]:
    # What the guest confirms is "check out now"; a rating given later does not change it.
    return {}


async def _preview(
    backend: BackendClient, token: str, args: CheckoutArgs, lang: str
) -> dict[str, Any]:
    bill = await backend.checkout_preview(token)
    return {
        "lines": [
            {
                "type": line.get("type"),
                "description": line.get("description"),
                "amount_vnd": line.get("amount_vnd"),
            }
            for line in bill.get("lines", [])
        ],
        "total_vnd": bill.get("total_vnd"),
        "open_orders": bill.get("open_orders", 0),
    }


async def _send(
    backend: BackendClient, token: str, args: CheckoutArgs, lang: str, *, idempotency_key: str
) -> dict[str, Any]:
    # The backend allows one open request per stay, so a repeat is a 409, never a second request.
    return await backend.create_checkout(
        token,
        {
            "guest_confirmed": True,
            "feedback_rating": args.feedback_rating,
            "feedback_note": args.feedback_note,
            "source": "CHATBOT",
        },
    )


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        return {}
    return {"checkout_request_id": data.get("checkout_request_id"), "status": data.get("status")}


TOOL = Tool(
    spec=SPEC,
    args_model=CheckoutArgs,
    runner=_send,
    write=True,
    gate=Gate(kind="CHECKOUT", payload=_payload, preview=_preview),
    summarize=_summary,
)
