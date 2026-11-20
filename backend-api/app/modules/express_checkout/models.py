"""Express checkout requests and the charges reception adds to a stay (SPEC-express-checkout)."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class CheckoutStatus(enum.StrEnum):
    CHECKOUT_REQUESTED = "CHECKOUT_REQUESTED"
    BILLING_VERIFIED = "BILLING_VERIFIED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


OPEN_CHECKOUT_STATUSES = (CheckoutStatus.CHECKOUT_REQUESTED, CheckoutStatus.BILLING_VERIFIED)
_OPEN_SQL = "status IN ('CHECKOUT_REQUESTED', 'BILLING_VERIFIED')"


class ChargeKind(enum.StrEnum):
    EXTRA = "EXTRA"
    DISCOUNT = "DISCOUNT"


class PaymentMethod(enum.StrEnum):
    """Recorded only: money is handled outside the system (SPEC assumption 2)."""

    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    CARD = "CARD"
    OTHER = "OTHER"


class CheckoutRequest(TimestampMixin, Base):
    __tablename__ = "checkout_request"
    __table_args__ = (
        CheckConstraint(
            "feedback_rating IS NULL OR feedback_rating BETWEEN 1 AND 5", name="rating_range"
        ),
        CheckConstraint("source IN ('APP', 'CHATBOT')", name="source_known"),
        # At most one open request per stay.
        Index(
            "uq_checkout_request_open_per_stay",
            "stay_id",
            unique=True,
            postgresql_where=text(_OPEN_SQL),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    stay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stay.id"), nullable=False, index=True
    )
    status: Mapped[CheckoutStatus] = mapped_column(
        Enum(
            CheckoutStatus,
            name="checkout_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    feedback_rating: Mapped[int | None] = mapped_column(SmallInteger)
    feedback_note: Mapped[str | None] = mapped_column(Text)
    # Frozen at BILLING_VERIFIED and never changed afterwards.
    bill_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    total_vnd: Mapped[int | None] = mapped_column(BigInteger)
    payment_method: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id")
    )
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id")
    )
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class StayCharge(Base):
    """An extra (minibar, late check-out) or a discount on a stay. Tied to the stay, not to a
    request, so it also works for check-out at the desk."""

    __tablename__ = "stay_charge"
    __table_args__ = (
        CheckConstraint("amount_vnd > 0", name="amount_positive"),
        CheckConstraint("kind IN ('EXTRA', 'DISCOUNT')", name="kind_known"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    stay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stay.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Soft delete, allowed only before the bill is locked.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
