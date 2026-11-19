"""Staff accounts and refresh tokens (spec/SPEC-staff-auth.md, "Dữ liệu")."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class StaffRole(enum.StrEnum):
    RECEPTION = "RECEPTION"
    KITCHEN = "KITCHEN"
    HOUSEKEEPING = "HOUSEKEEPING"


class Staff(TimestampMixin, Base):
    __tablename__ = "staff"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[StaffRole] = mapped_column(
        Enum(StaffRole, name="staff_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Bumped to invalidate every access token issued before (lock, password change).
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StaffRefreshToken(Base):
    __tablename__ = "staff_refresh_token"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # sha256 of the opaque token; the raw token is only ever in the HttpOnly cookie.
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # Rotation chain: reuse of a revoked token revokes the whole family.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
