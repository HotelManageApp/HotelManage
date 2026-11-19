"""Menu and food orders (spec/SPEC-room-service.md, "Dữ liệu")."""

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
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


class MenuCategory(TimestampMixin, Base):
    __tablename__ = "menu_category"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # BREAKFAST, MAIN, ...
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class MenuItem(TimestampMixin, Base):
    __tablename__ = "menu_item"
    __table_args__ = (CheckConstraint("price_vnd >= 0", name="price_non_negative"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_category.id"), nullable=False, index=True
    )
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    description_vi: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    price_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Kitchen toggles this when a dish runs out.
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Soft delete: past orders keep pointing at the item.
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")

    def name(self, lang: str) -> str:
        return self.name_en if lang == "en" else self.name_vi

    def description(self, lang: str) -> str | None:
        return (self.description_en if lang == "en" else self.description_vi) or None


class OrderStatus(enum.StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PREPARING = "PREPARING"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


OPEN_ORDER_STATUSES = (
    OrderStatus.PENDING,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.DELIVERING,
)


class FoodOrder(TimestampMixin, Base):
    __tablename__ = "food_order"
    __table_args__ = (
        CheckConstraint("total_vnd >= 0", name="total_non_negative"),
        Index("ix_food_order_status_created", "status", "created_at"),
        Index(
            "uq_food_order_idempotency",
            "stay_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    stay_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stay.id"), nullable=False, index=True
    )
    # Copied from the guest's token context for display/filtering; never taken from a request.
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("room.id"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="food_order_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    total_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # APP | CHATBOT
    estimated_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderItem.position",
    )


class OrderItem(Base):
    __tablename__ = "order_item"
    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 20", name="quantity_range"),
        CheckConstraint("unit_price_vnd >= 0", name="unit_price_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("food_order.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_item.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    # Name and price as they were when the guest ordered.
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    line_total_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    order: Mapped[FoodOrder] = relationship(back_populates="items")

    def name(self, lang: str) -> str:
        return self.name_en if lang == "en" else self.name_vi
