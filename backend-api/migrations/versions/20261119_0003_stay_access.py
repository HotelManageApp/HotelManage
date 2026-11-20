"""stay access: room, stay, stay_session

Revision ID: 0003_stay_access
Revises: 0002_staff_auth
Create Date: 2026-11-19 15:49:24.452811
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_stay_access"
down_revision: str | None = "0002_staff_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "room",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("floor", sa.SmallInteger(), nullable=True),
        sa.Column("room_type", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("VACANT", "OCCUPIED", "CLEANING", name="room_status"),
            server_default="VACANT",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_room")),
        sa.UniqueConstraint("number", name=op.f("uq_room_number")),
    )
    op.create_table(
        "stay",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column("guest_name", sa.Text(), nullable=True),
        sa.Column("guest_count", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("checkin_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_checkout_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("room_charge_vnd", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "CHECKOUT_PENDING", "CLOSED", name="stay_status"),
            nullable=False,
        ),
        sa.Column("room_code_lookup", sa.Text(), nullable=True),
        sa.Column("code_issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_in_by", sa.UUID(), nullable=False),
        sa.Column("closed_by", sa.UUID(), nullable=True),
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
        sa.CheckConstraint("guest_count BETWEEN 1 AND 20", name=op.f("ck_stay_guest_count_range")),
        sa.CheckConstraint("room_charge_vnd >= 0", name=op.f("ck_stay_room_charge_non_negative")),
        sa.ForeignKeyConstraint(
            ["checked_in_by"], ["staff.id"], name=op.f("fk_stay_checked_in_by_staff")
        ),
        sa.ForeignKeyConstraint(["closed_by"], ["staff.id"], name=op.f("fk_stay_closed_by_staff")),
        sa.ForeignKeyConstraint(["room_id"], ["room.id"], name=op.f("fk_stay_room_id_room")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stay")),
    )
    op.create_index(op.f("ix_stay_room_id"), "stay", ["room_id"], unique=False)
    op.create_index(
        "uq_stay_open_room",
        "stay",
        ["room_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'CLOSED'"),
    )
    op.create_index(
        "uq_stay_room_code_lookup",
        "stay",
        ["room_code_lookup"],
        unique=True,
        postgresql_where=sa.text("room_code_lookup IS NOT NULL"),
    )
    op.create_table(
        "stay_session",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stay_id", sa.UUID(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("lang", sa.Text(), server_default="vi", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoke_reason",
            sa.Enum("CHECKOUT", "REISSUE", "LOGOUT", "EXPIRED", name="revoke_reason"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["stay_id"], ["stay.id"], name=op.f("fk_stay_session_stay_id_stay")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stay_session")),
    )
    op.create_index(op.f("ix_stay_session_stay_id"), "stay_session", ["stay_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stay_session_stay_id"), table_name="stay_session")
    op.drop_table("stay_session")
    op.drop_index(
        "uq_stay_room_code_lookup",
        table_name="stay",
        postgresql_where=sa.text("room_code_lookup IS NOT NULL"),
    )
    op.drop_index(
        "uq_stay_open_room", table_name="stay", postgresql_where=sa.text("status <> 'CLOSED'")
    )
    op.drop_index(op.f("ix_stay_room_id"), table_name="stay")
    op.drop_table("stay")
    op.drop_table("room")
    for enum_name in ("revoke_reason", "stay_status", "room_status"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
