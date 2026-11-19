"""Who moved which request from which status to which, and why (food orders, housekeeping,
checkout). Written by each module's `transition` function, never edited afterwards."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Text, func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StatusHistory(Base):
    __tablename__ = "status_history"
    __table_args__ = (Index("ix_status_history_entity", "entity_type", "entity_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)  # GUEST | STAFF:<id> | SYSTEM
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


def record(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    from_status: str | None,
    to_status: str,
    actor: str,
    reason: str | None = None,
) -> StatusHistory:
    entry = StatusHistory(
        entity_type=entity_type,
        entity_id=entity_id,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
    )
    db.add(entry)
    return entry


async def history_of(
    db: AsyncSession, entity_type: str, entity_id: uuid.UUID
) -> list[StatusHistory]:
    rows = await db.scalars(
        select(StatusHistory)
        .where(StatusHistory.entity_type == entity_type, StatusHistory.entity_id == entity_id)
        .order_by(StatusHistory.created_at)
    )
    return list(rows)
