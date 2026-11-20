"""Guest-token API used by the AI concierge (ai-service calls it with the guest's own token)."""

import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.core.db import DbSession
from app.core.hotel_settings import load_hotel_settings
from app.modules.concierge_data import chat
from app.modules.concierge_data.schemas import HotelInfo
from app.modules.concierge_data.search import SearchResult, ToolTopic, search
from app.modules.stay_access.deps import CurrentStay
from app.modules.stay_access.schemas import StrictModel

router = APIRouter(prefix="/guest", tags=["guest-concierge"])

MAX_TOOL_TRACE_BYTES = 16_000
# A trace lists tools, arguments and KB ids. Anything that looks like a credential or a room is
# refused, so a bug in ai-service cannot persist one (CONSTRAINTS C4.5).
FORBIDDEN_TRACE_KEYS = {"token", "access_token", "authorization", "room_code", "room_id", "stay_id"}


@router.get("/kb/search", response_model=SearchResult)
async def guest_search(
    ctx: CurrentStay,
    db: DbSession,
    topic: ToolTopic,
    q: Annotated[str, Query(max_length=300)] = "",
    lang: Annotated[str | None, Query(pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")] = None,
) -> SearchResult:
    """Shape of `data` in the `get_hotel_info_and_guide` tool output (chatbot-tools-spec §4.1)."""
    return await search(db, topic, q, (lang or ctx.lang).split("-")[0].lower())


@router.get("/hotel-info", response_model=HotelInfo)
async def hotel_info(_: CurrentStay, db: DbSession) -> object:
    """Hotel name, reception phone, default language and whether the chatbot is on."""
    return await load_hotel_settings(db)


# ---------- chat history ----------


class ChatLine(BaseModel):
    id: uuid.UUID
    role: Literal["GUEST", "ASSISTANT"]
    content: str
    created_at: datetime
    # Only with ?with_trace=true (ai-service reads its own pending confirmations back,
    # SPEC-concierge-actions); the app does not ask for it.
    tool_trace: dict | list | None = None


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(k).lower() for k in value} | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


class Exchange(StrictModel):
    guest_message: str = Field(min_length=1, max_length=1000)
    assistant_message: str = Field(min_length=1, max_length=4000)
    tool_trace: dict | list | None = None
    grounded: bool | None = None
    client_message_id: uuid.UUID | None = None

    @field_validator("tool_trace")
    @classmethod
    def _small_and_clean(cls, value: dict | list | None) -> dict | list | None:
        if value is None:
            return None
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_TOOL_TRACE_BYTES:
            raise ValueError(f"tool_trace is larger than {MAX_TOOL_TRACE_BYTES} bytes")
        if _keys(value) & FORBIDDEN_TRACE_KEYS:
            raise ValueError("tool_trace must not carry tokens, room codes or ids")
        return value


class ExchangeSaved(BaseModel):
    message_id: uuid.UUID  # the assistant's line
    guest_message_id: uuid.UUID


@router.get("/chat/messages", response_model=list[ChatLine], response_model_exclude_none=True)
async def chat_history(
    ctx: CurrentStay,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[AwareDatetime | None, Query()] = None,
    with_trace: bool = False,
) -> list[ChatLine]:
    """The stay's conversation, oldest first; `before` pages back in time."""
    rows = await chat.history(db, ctx.stay_id, limit=limit, before=before)
    return [
        ChatLine.model_validate(
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "tool_trace": m.tool_trace if with_trace else None,
            }
        )
        for m in rows
    ]


@router.post("/chat/messages", response_model=ExchangeSaved, status_code=status.HTTP_201_CREATED)
async def save_chat(body: Exchange, ctx: CurrentStay, db: DbSession) -> ExchangeSaved:
    guest, assistant = await chat.save_exchange(
        db,
        ctx,
        guest_message=body.guest_message,
        assistant_message=body.assistant_message,
        tool_trace=body.tool_trace,
        grounded=body.grounded,
        client_message_id=body.client_message_id,
    )
    saved = ExchangeSaved(message_id=assistant.id, guest_message_id=guest.id)
    await db.commit()
    return saved


class QuotaLeft(BaseModel):
    remaining_minute: int
    remaining_day: int


@router.post("/chat/quota", response_model=QuotaLeft)
async def take_chat_quota(ctx: CurrentStay, db: DbSession) -> QuotaLeft:
    """One message's worth of quota: 10/minute per device, 100/day per stay; over -> 429 with
    Retry-After."""
    left = await chat.take_quota(db, ctx)
    await db.commit()
    return QuotaLeft(remaining_minute=left.minute, remaining_day=left.day)
