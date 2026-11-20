"""chat history of the concierge

Revision ID: 0009_chat_message
Revises: 0008_concierge_data
Create Date: 2026-11-20 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_chat_message"
down_revision: str | None = "0008_concierge_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_message",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stay_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("client_message_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_trace", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("grounded", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('GUEST', 'ASSISTANT')", name=op.f("ck_chat_message_role_known")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["stay_session.id"],
            name=op.f("fk_chat_message_session_id_stay_session"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stay_id"], ["stay.id"], name=op.f("fk_chat_message_stay_id_stay"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_message")),
        sa.UniqueConstraint(
            "stay_id", "client_message_id", "role", name="uq_chat_message_client_id"
        ),
    )
    op.create_index("ix_chat_message_stay_created", "chat_message", ["stay_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_message_stay_created", table_name="chat_message")
    op.drop_table("chat_message")
