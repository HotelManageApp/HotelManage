"""staff auth: staff, staff_refresh_token, rate_limit_bucket

Revision ID: 0002_staff_auth
Revises: 0001_base
Create Date: 2026-11-19 15:28:30.013605
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_staff_auth"
down_revision: str | None = "0001_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_bucket",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_rate_limit_bucket")),
    )
    op.create_table(
        "staff",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("RECEPTION", "KITCHEN", "HOUSEKEEPING", name="staff_role"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff")),
        sa.UniqueConstraint("email", name=op.f("uq_staff_email")),
    )
    op.create_table(
        "staff_refresh_token",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("staff_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["staff.id"],
            name=op.f("fk_staff_refresh_token_staff_id_staff"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_refresh_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_staff_refresh_token_token_hash")),
    )
    op.create_index(
        op.f("ix_staff_refresh_token_family_id"), "staff_refresh_token", ["family_id"], unique=False
    )
    op.create_index(
        op.f("ix_staff_refresh_token_staff_id"), "staff_refresh_token", ["staff_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_staff_refresh_token_staff_id"), table_name="staff_refresh_token")
    op.drop_index(op.f("ix_staff_refresh_token_family_id"), table_name="staff_refresh_token")
    op.drop_table("staff_refresh_token")
    op.drop_table("staff")
    op.drop_table("rate_limit_bucket")
    sa.Enum(name="staff_role").drop(op.get_bind(), checkfirst=True)
