"""Housekeeping requests (spec/SPEC-housekeeping.md, "Dữ liệu")."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class HkType(enum.StrEnum):
    CLEANING = "CLEANING"
    AMENITY = "AMENITY"
    TURNOVER = "TURNOVER"  # after check-out; created by the system, never by a guest


class HkStatus(enum.StrEnum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class AmenityCode(enum.StrEnum):
    TOWEL = "TOWEL"
    WATER = "WATER"
    TOILETRIES = "TOILETRIES"
    PILLOW = "PILLOW"
    BLANKET = "BLANKET"
    SLIPPERS = "SLIPPERS"
    OTHER = "OTHER"


OPEN_HK_STATUSES = (HkStatus.REQUESTED, HkStatus.ASSIGNED, HkStatus.IN_PROGRESS)
_OPEN_SQL = "status IN ('REQUESTED', 'ASSIGNED', 'IN_PROGRESS')"


class HousekeepingRequest(TimestampMixin, Base):
    __tablename__ = "housekeeping_request"
    __table_args__ = (
        # At most one open cleaning per stay, and one open turnover per room.
        Index(
            "uq_hk_open_cleaning_per_stay",
            "stay_id",
            unique=True,
            postgresql_where=text(f"type = 'CLEANING' AND {_OPEN_SQL}"),
        ),
        Index(
            "uq_hk_open_turnover_per_room",
            "room_id",
            unique=True,
            postgresql_where=text(f"type = 'TURNOVER' AND {_OPEN_SQL}"),
        ),
        Index(
            "uq_hk_idempotency",
            "stay_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_hk_status_created", "status", "created_at"),
        CheckConstraint("(type = 'TURNOVER') = (stay_id IS NULL)", name="turnover_has_no_stay"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("room.id"), nullable=False, index=True
    )
    stay_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stay.id"), index=True
    )
    type: Mapped[HkType] = mapped_column(_pg_enum(HkType, "hk_type"), nullable=False)
    status: Mapped[HkStatus] = mapped_column(_pg_enum(HkStatus, "hk_status"), nullable=False)
    preferred_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # None=ASAP
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # APP | CHATBOT | SYSTEM
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id")
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    items: Mapped[list["HousekeepingRequestItem"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", lazy="selectin"
    )


class HousekeepingRequestItem(Base):
    __tablename__ = "housekeeping_request_item"
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 5", name="quantity_range"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("housekeeping_request.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[AmenityCode] = mapped_column(_pg_enum(AmenityCode, "amenity_code"), nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    request: Mapped[HousekeepingRequest] = relationship(back_populates="items")
