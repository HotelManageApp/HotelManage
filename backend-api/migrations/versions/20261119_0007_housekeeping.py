"""housekeeping

Revision ID: 0007_housekeeping
Revises: 0006_food_orders
Create Date: 2026-11-19 16:52:58.401695
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_housekeeping"
down_revision: str | None = "0006_food_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "housekeeping_request",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column("stay_id", sa.UUID(), nullable=True),
        sa.Column(
            "type", sa.Enum("CLEANING", "AMENITY", "TURNOVER", name="hk_type"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("REQUESTED", "ASSIGNED", "IN_PROGRESS", "DONE", "CANCELLED", name="hk_status"),
            nullable=False,
        ),
        sa.Column("preferred_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("assigned_to", sa.UUID(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("overdue_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
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
        sa.CheckConstraint(
            "(type = 'TURNOVER') = (stay_id IS NULL)",
            name=op.f("ck_housekeeping_request_turnover_has_no_stay"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"], ["staff.id"], name=op.f("fk_housekeeping_request_assigned_to_staff")
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["room.id"], name=op.f("fk_housekeeping_request_room_id_room")
        ),
        sa.ForeignKeyConstraint(
            ["stay_id"], ["stay.id"], name=op.f("fk_housekeeping_request_stay_id_stay")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_housekeeping_request")),
    )
    op.create_index(
        "ix_hk_status_created", "housekeeping_request", ["status", "created_at"], unique=False
    )
    op.create_index(
        op.f("ix_housekeeping_request_room_id"), "housekeeping_request", ["room_id"], unique=False
    )
    op.create_index(
        op.f("ix_housekeeping_request_stay_id"), "housekeeping_request", ["stay_id"], unique=False
    )
    op.create_index(
        "uq_hk_idempotency",
        "housekeeping_request",
        ["stay_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_hk_open_cleaning_per_stay",
        "housekeeping_request",
        ["stay_id"],
        unique=True,
        postgresql_where=sa.text(
            "type = 'CLEANING' AND status IN ('REQUESTED', 'ASSIGNED', 'IN_PROGRESS')"
        ),
    )
    op.create_index(
        "uq_hk_open_turnover_per_room",
        "housekeeping_request",
        ["room_id"],
        unique=True,
        postgresql_where=sa.text(
            "type = 'TURNOVER' AND status IN ('REQUESTED', 'ASSIGNED', 'IN_PROGRESS')"
        ),
    )
    op.create_table(
        "housekeeping_request_item",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column(
            "code",
            sa.Enum(
                "TOWEL",
                "WATER",
                "TOILETRIES",
                "PILLOW",
                "BLANKET",
                "SLIPPERS",
                "OTHER",
                name="amenity_code",
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 5", name=op.f("ck_housekeeping_request_item_quantity_range")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["housekeeping_request.id"],
            name=op.f("fk_housekeeping_request_item_request_id_housekeeping_request"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_housekeeping_request_item")),
    )
    op.create_index(
        op.f("ix_housekeeping_request_item_request_id"),
        "housekeeping_request_item",
        ["request_id"],
        unique=False,
    )
    op.add_column(
        "stay",
        sa.Column("do_not_disturb", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("stay", sa.Column("dnd_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("stay", "dnd_updated_at")
    op.drop_column("stay", "do_not_disturb")
    op.drop_index(
        op.f("ix_housekeeping_request_item_request_id"), table_name="housekeeping_request_item"
    )
    op.drop_table("housekeeping_request_item")
    op.drop_index(
        "uq_hk_open_turnover_per_room",
        table_name="housekeeping_request",
        postgresql_where=sa.text(
            "type = 'TURNOVER' AND status IN ('REQUESTED', 'ASSIGNED', 'IN_PROGRESS')"
        ),
    )
    op.drop_index(
        "uq_hk_open_cleaning_per_stay",
        table_name="housekeeping_request",
        postgresql_where=sa.text(
            "type = 'CLEANING' AND status IN ('REQUESTED', 'ASSIGNED', 'IN_PROGRESS')"
        ),
    )
    op.drop_index(
        "uq_hk_idempotency",
        table_name="housekeeping_request",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index(op.f("ix_housekeeping_request_stay_id"), table_name="housekeeping_request")
    op.drop_index(op.f("ix_housekeeping_request_room_id"), table_name="housekeeping_request")
    op.drop_index("ix_hk_status_created", table_name="housekeeping_request")
    op.drop_table("housekeeping_request")
    for enum_name in ("amenity_code", "hk_status", "hk_type"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
