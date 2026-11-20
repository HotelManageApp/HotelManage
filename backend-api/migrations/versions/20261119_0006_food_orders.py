"""food orders

Revision ID: 0006_food_orders
Revises: 0005_menu
Create Date: 2026-11-19 16:35:57.389556
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_food_orders"
down_revision: str | None = "0005_menu"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "food_order",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stay_id", sa.UUID(), nullable=False),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CONFIRMED",
                "PREPARING",
                "DELIVERING",
                "COMPLETED",
                "CANCELLED",
                name="food_order_status",
            ),
            nullable=False,
        ),
        sa.Column("total_vnd", sa.BigInteger(), nullable=False),
        sa.Column("order_note", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("estimated_minutes", sa.SmallInteger(), nullable=True),
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
        sa.CheckConstraint("total_vnd >= 0", name=op.f("ck_food_order_total_non_negative")),
        sa.ForeignKeyConstraint(["room_id"], ["room.id"], name=op.f("fk_food_order_room_id_room")),
        sa.ForeignKeyConstraint(["stay_id"], ["stay.id"], name=op.f("fk_food_order_stay_id_stay")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_food_order")),
    )
    op.create_index(
        "ix_food_order_status_created", "food_order", ["status", "created_at"], unique=False
    )
    op.create_index(op.f("ix_food_order_stay_id"), "food_order", ["stay_id"], unique=False)
    op.create_index(
        "uq_food_order_idempotency",
        "food_order",
        ["stay_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "order_item",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("menu_item_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("name_vi", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("unit_price_vnd", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column("line_total_vnd", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("quantity BETWEEN 1 AND 20", name=op.f("ck_order_item_quantity_range")),
        sa.CheckConstraint(
            "unit_price_vnd >= 0", name=op.f("ck_order_item_unit_price_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["menu_item_id"], ["menu_item.id"], name=op.f("fk_order_item_menu_item_id_menu_item")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["food_order.id"],
            name=op.f("fk_order_item_order_id_food_order"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_item")),
    )
    op.create_index(op.f("ix_order_item_order_id"), "order_item", ["order_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_order_item_order_id"), table_name="order_item")
    op.drop_table("order_item")
    op.drop_index(
        "uq_food_order_idempotency",
        table_name="food_order",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index(op.f("ix_food_order_stay_id"), table_name="food_order")
    op.drop_index("ix_food_order_status_created", table_name="food_order")
    op.drop_table("food_order")
    sa.Enum(name="food_order_status").drop(op.get_bind(), checkfirst=True)
