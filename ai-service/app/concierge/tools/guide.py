"""`get_hotel_info_and_guide` (docs/chatbot-tools-spec.md §4.1): read-only knowledge-base lookup."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.concierge.tools.base import Tool
from app.core.backend_client import BackendClient
from app.llm.base import ToolSpec

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


async def _run(backend: BackendClient, token: str, args: GuideArgs, lang: str) -> dict[str, Any]:
    return await backend.kb_search(
        token, topic=args.topic, query=args.query, lang=args.lang or lang
    )


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "found": bool(data.get("found")),
        "kb_ids": [e.get("id") for e in data.get("entries", []) if e.get("id")],
        "places": [p.get("name") for p in data.get("places", [])],
    }


def found(output: dict[str, Any]) -> bool:
    return bool(output.get("ok") and (output.get("data") or {}).get("found"))


TOOL = Tool(spec=SPEC, args_model=GuideArgs, runner=_run, summarize=_summary)
