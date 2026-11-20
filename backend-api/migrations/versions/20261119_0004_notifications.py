"""notifications

Revision ID: 0004_notifications
Revises: 0003_stay_access
Create Date: 2026-11-19 16:18:41.512849
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_notifications"
down_revision: str | None = "0003_stay_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stay_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("target_tokens", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "delivery_status",
            sa.Enum("PENDING", "SENT", "FAILED", "SKIPPED", name="delivery_status"),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["stay_id"], ["stay.id"], name=op.f("fk_notification_outbox_stay_id_stay")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_outbox")),
    )
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["delivery_status", "next_attempt_at"],
        unique=False,
    )
    op.add_column("stay_session", sa.Column("fcm_token", sa.Text(), nullable=True))
    op.add_column(
        "stay_session", sa.Column("fcm_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("stay_session", "fcm_updated_at")
    op.drop_column("stay_session", "fcm_token")
    op.drop_index("ix_notification_outbox_due", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    sa.Enum(name="delivery_status").drop(op.get_bind(), checkfirst=True)
