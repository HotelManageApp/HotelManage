"""Menu (T24). Orders are added in T25 (spec/SPEC-room-service.md, "Dữ liệu")."""

import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

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
