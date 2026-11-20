"""Rooms, stays and guest device sessions (spec/SPEC-stay-access.md, "Dữ liệu")."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class RoomStatus(enum.StrEnum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    CLEANING = "CLEANING"


class StayStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    CHECKOUT_PENDING = "CHECKOUT_PENDING"
    CLOSED = "CLOSED"


class RevokeReason(enum.StrEnum):
    CHECKOUT = "CHECKOUT"
    REISSUE = "REISSUE"
    LOGOUT = "LOGOUT"
    EXPIRED = "EXPIRED"


class Room(TimestampMixin, Base):
    __tablename__ = "room"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    floor: Mapped[int | None] = mapped_column(SmallInteger)
    room_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RoomStatus] = mapped_column(
        _pg_enum(RoomStatus, "room_status"),
        nullable=False,
        server_default=RoomStatus.VACANT.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Stay(TimestampMixin, Base):
    __tablename__ = "stay"
    __table_args__ = (
        CheckConstraint("room_charge_vnd >= 0", name="room_charge_non_negative"),
        CheckConstraint("guest_count BETWEEN 1 AND 20", name="guest_count_range"),
        # Lookup of a live room code; NULL once the stay is closed.
        Index(
            "uq_stay_room_code_lookup",
            "room_code_lookup",
            unique=True,
            postgresql_where=text("room_code_lookup IS NOT NULL"),
        ),
        # A room has at most one stay that is not closed.
        Index(
            "uq_stay_open_room",
            "room_id",
            unique=True,
            postgresql_where=text("status <> 'CLOSED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("room.id"), nullable=False, index=True
    )
    guest_name: Mapped[str | None] = mapped_column(Text)
    guest_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    checkin_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_checkout_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    room_charge_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[StayStatus] = mapped_column(_pg_enum(StayStatus, "stay_status"), nullable=False)
    # HMAC-SHA256(code, ROOM_CODE_PEPPER). The raw code is never stored.
    room_code_lookup: Mapped[str | None] = mapped_column(Text)
    code_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff.id"))
    # Guest asked housekeeping not to knock (SPEC-housekeeping).
    do_not_disturb: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    dnd_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StaySession(Base):
    __tablename__ = "stay_session"

    # Doubles as the `jti` of the guest token.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    stay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stay.id"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(Text, nullable=False, server_default="vi")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Firebase Cloud Messaging token of this device (SPEC-notifications); never logged.
    fcm_token: Mapped[str | None] = mapped_column(Text)
    fcm_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[RevokeReason | None] = mapped_column(
        _pg_enum(RevokeReason, "revoke_reason")
    )
