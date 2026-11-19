"""Chat history and message quota for the concierge (SPEC-concierge-guide, T38).

ai-service has no database: it reads and writes history here with the guest's own token, and
asks for one unit of quota before every LLM call.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.errors import RateLimited
from app.modules.concierge_data.models import ChatMessage
from app.modules.stay_access.deps import StayContext


@dataclass(frozen=True)
class Quota:
    limit: int
    seconds: int
    message: str


PER_MINUTE = Quota(10, 60, "Quý khách gửi tin hơi nhanh, vui lòng chờ một chút")
PER_DAY = Quota(100, 86_400, "Quý khách đã dùng hết lượt hỏi trợ lý hôm nay")


@dataclass(frozen=True)
class QuotaLeft:
    minute: int
    day: int


async def _take(db: AsyncSession, key: str, quota: Quota, now: datetime) -> int:
    """Count one message in a fixed window; 429 with the time left in the window when over."""
    count = await rate_limit.register(db, key, window_seconds=quota.seconds, now=now)
    if count > quota.limit:
        started = await db.scalar(
            select(rate_limit.RateLimitBucket.window_start).where(
                rate_limit.RateLimitBucket.key == key
            )
        )
        ends = (started or now) + timedelta(seconds=quota.seconds)
        raise RateLimited(quota.message, retry_after_seconds=int((ends - now).total_seconds()) + 1)
    return quota.limit - count


async def take_quota(db: AsyncSession, ctx: StayContext, now: datetime | None = None) -> QuotaLeft:
    """10 messages a minute per device session, 100 a day per stay. The caller commits; a 429
    rolls the count back, so refused attempts do not use up the day."""
    current = now or datetime.now(UTC)
    minute = await _take(db, f"chat:session:{ctx.session_id}", PER_MINUTE, current)
    day = await _take(db, f"chat:stay:{ctx.stay_id}", PER_DAY, current)
    return QuotaLeft(minute=minute, day=day)


async def history(
    db: AsyncSession, stay_id: uuid.UUID, *, limit: int, before: datetime | None
) -> list[ChatMessage]:
    """The latest `limit` messages of the stay (before `before`), oldest first."""
    stmt = select(ChatMessage).where(ChatMessage.stay_id == stay_id)
    if before is not None:
        stmt = stmt.where(ChatMessage.created_at < before)
    newest = list(
        await db.scalars(stmt.order_by(ChatMessage.created_at.desc(), ChatMessage.id).limit(limit))
    )
    return list(reversed(newest))


async def save_exchange(
    db: AsyncSession,
    ctx: StayContext,
    *,
    guest_message: str,
    assistant_message: str,
    tool_trace: object | None,
    grounded: bool | None,
    client_message_id: uuid.UUID | None,
) -> tuple[ChatMessage, ChatMessage]:
    """Store the guest's message and the answer. With a client_message_id already stored for
    this stay, returns the stored pair instead (a retried send, even a concurrent one)."""
    if client_message_id is not None:
        stored = await _pair(db, ctx.stay_id, client_message_id)
        if stored is not None:
            return stored

    def message(role: str, content: str, **extra: object) -> ChatMessage:
        return ChatMessage(
            stay_id=ctx.stay_id,
            session_id=ctx.session_id,
            client_message_id=client_message_id,
            role=role,
            content=content,
            **extra,
        )

    guest = message("GUEST", guest_message)
    assistant = message("ASSISTANT", assistant_message, tool_trace=tool_trace, grounded=grounded)
    try:
        async with db.begin_nested():
            db.add(guest)
            await db.flush()  # separately, so the guest line is always the earlier one
            db.add(assistant)
            await db.flush()
    except IntegrityError:
        if client_message_id is None:
            raise
        stored = await _pair(db, ctx.stay_id, client_message_id)
        if stored is None:
            raise
        return stored
    return guest, assistant


async def _pair(
    db: AsyncSession, stay_id: uuid.UUID, client_message_id: uuid.UUID
) -> tuple[ChatMessage, ChatMessage] | None:
    rows = {
        m.role: m
        for m in await db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.stay_id == stay_id,
                ChatMessage.client_message_id == client_message_id,
            )
            .execution_options(populate_existing=True)
        )
    }
    if "GUEST" in rows and "ASSISTANT" in rows:
        return rows["GUEST"], rows["ASSISTANT"]
    return None


async def forget_stay(db: AsyncSession, stay_id: uuid.UUID) -> None:
    """Stay closed: its chat is personal data and is not kept (chatbot-tools-spec §1)."""
    await db.execute(delete(ChatMessage).where(ChatMessage.stay_id == stay_id))
