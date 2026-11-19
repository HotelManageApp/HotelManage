"""`get_hotel_info_and_guide` (docs/chatbot-tools-spec.md §4.1): read-only knowledge-base lookup."""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.backend_client import BackendClient, BackendError, BackendUnauthorized
from app.core.logging import get_logger
from app.llm.base import ToolSpec

logger = get_logger(__name__)

Topic = Literal[
    "BREAKFAST",
    "FACILITIES",
    "SERVICES",
    "POLICIES",
    "WIFI",
    "TRANSPORT",
    "ATTRACTIONS",
    "FOOD_NEARBY",
    "OTHER",
]


class GuideArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: Topic
    query: str = Field(min_length=1, max_length=300)
    lang: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "enum": list(Topic.__args__)},
        "query": {
            "type": "string",
            "maxLength": 300,
            "description": "Câu hỏi của khách, nguyên văn hoặc tóm tắt",
        },
        "lang": {"type": "string", "description": "BCP-47, VD vi, en, ko"},
    },
    "required": ["topic", "query"],
    "additionalProperties": False,
}

SPEC = ToolSpec(
    name="get_hotel_info_and_guide",
    description=(
        "Look up the hotel's knowledge base (breakfast, Wi-Fi, facilities, services, policies, "
        "hotel transport) and nearby places (attractions, food, transport). Returns found=false "
        "when the hotel has no such information."
    ),
    input_schema=SCHEMA,
)


@dataclass
class ToolRun:
    """One executed call, kept for grounding and for the stored tool trace (no token)."""

    name: str
    args: dict[str, Any]
    output: dict[str, Any]
    rejected_args: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.output.get("ok") and self.output.get("data", {}).get("found"))

    def trace(self) -> dict[str, Any]:
        data = self.output.get("data") or {}
        return {
            "tool": self.name,
            "args": self.args,
            "found": self.found,
            "kb_ids": [e.get("id") for e in data.get("entries", []) if e.get("id")],
            "places": [p.get("name") for p in data.get("places", [])],
            **({"rejected_args": self.rejected_args} if self.rejected_args else {}),
        }


def clean_args(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop arguments the schema does not know (room_id included), log them, keep the rest."""
    known = set(SCHEMA["properties"])
    rejected = sorted(k for k in raw if k not in known)
    if rejected:
        logger.warning("tool_arg_rejected", tool=SPEC.name, args=rejected)
    return {k: v for k, v in raw.items() if k in known}, rejected


async def run(backend: BackendClient, token: str, raw_args: dict[str, Any], lang: str) -> ToolRun:
    args, rejected = clean_args(raw_args)
    try:
        parsed = GuideArgs.model_validate(args)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        return ToolRun(
            SPEC.name,
            args,
            {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": ", ".join(fields)}},
            rejected,
        )
    try:
        data = await backend.kb_search(
            token, topic=parsed.topic, query=parsed.query, lang=parsed.lang or lang
        )
    except BackendUnauthorized:
        raise  # the session ended mid-chat: the whole request answers 401
    except BackendError as exc:
        return ToolRun(
            SPEC.name,
            parsed.model_dump(exclude_none=True),
            {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": exc.code}},
            rejected,
        )
    return ToolRun(
        SPEC.name, parsed.model_dump(exclude_none=True), {"ok": True, "data": data}, rejected
    )
