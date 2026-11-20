"""`request_housekeeping` (docs/chatbot-tools-spec.md §4.4): cleaning or amenities, created at
once (no confirmation gate). A write tool: not offered while the stay is CHECKOUT_PENDING.
"""

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.concierge.tools.base import Tool
from app.core.backend_client import BackendClient
from app.llm.base import ToolSpec

Amenity = Literal["TOWEL", "WATER", "TOILETRIES", "PILLOW", "BLANKET", "SLIPPERS", "OTHER"]


class AmenityLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Amenity
    quantity: int = Field(ge=1, le=5)


class HousekeepingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["CLEANING", "AMENITY"]
    amenities: list[AmenityLine] | None = Field(default=None, max_length=10)
    preferred_time: str = "ASAP"
    note: str | None = Field(default=None, max_length=300)

    @field_validator("preferred_time")
    @classmethod
    def _asap_or_aware(cls, value: str) -> str:
        if value.upper() == "ASAP":
            return "ASAP"
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("ISO-8601 with a UTC offset (e.g. +07:00) or 'ASAP'") from None
        if parsed.tzinfo is None:
            raise ValueError("include the UTC offset, e.g. 2026-11-20T14:00:00+07:00")
        return parsed.isoformat()

    @model_validator(mode="after")
    def _amenities_for_amenity(self) -> Self:
        if self.type == "AMENITY" and not self.amenities:
            raise ValueError("amenities is required when type is AMENITY")
        return self


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["CLEANING", "AMENITY"]},
        "amenities": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "enum": list(Amenity.__args__)},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["code", "quantity"],
                "additionalProperties": False,
            },
        },
        "preferred_time": {"type": "string", "description": "ISO-8601 hoặc 'ASAP'"},
        "note": {"type": "string", "maxLength": 300},
    },
    "required": ["type"],
    "additionalProperties": False,
}

SPEC = ToolSpec(
    name="request_housekeeping",
    description=(
        "Ask housekeeping to clean the guest's room or bring amenities (towels, water, "
        "toiletries…). Created immediately. preferred_time is ISO-8601 with the hotel's UTC "
        "offset, or 'ASAP'."
    ),
    input_schema=SCHEMA,
)


async def _run(
    backend: BackendClient, token: str, args: HousekeepingArgs, lang: str
) -> dict[str, Any]:
    body = {
        "type": args.type,
        "amenities": [a.model_dump() for a in args.amenities] if args.amenities else None,
        "preferred_time": args.preferred_time,
        "note": args.note,
        "source": "CHATBOT",
    }
    created = await backend.create_housekeeping(
        token, {k: v for k, v in body.items() if v is not None}, idempotency_key=uuid.uuid4().hex
    )
    return {
        "request_id": created.get("id"),
        "type": created.get("type"),
        "status": created.get("status"),
        "preferred_time": created.get("preferred_time") or "ASAP",
        "created_at": created.get("created_at"),
    }


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    return {"request_id": data.get("request_id"), "status": data.get("status")} if data else {}


TOOL = Tool(spec=SPEC, args_model=HousekeepingArgs, runner=_run, write=True, summarize=_summary)
