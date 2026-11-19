"""menu

Revision ID: 0005_menu
Revises: 0004_notifications
Create Date: 2026-11-19 16:30:58.175648
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_menu"
down_revision: str | None = "0004_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "menu_category",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_vi", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_category")),
        sa.UniqueConstraint("code", name=op.f("uq_menu_category_code")),
    )
    op.create_table(
        "status_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_status_history")),
    )
    op.create_index(
        "ix_status_history_entity",
        "status_history",
        ["entity_type", "entity_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "menu_item",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("name_vi", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("description_vi", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("price_vnd", sa.BigInteger(), nullable=False),
        sa.Column("available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
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
        sa.CheckConstraint("price_vnd >= 0", name=op.f("ck_menu_item_price_non_negative")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["menu_category.id"],
            name=op.f("fk_menu_item_category_id_menu_category"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_item")),
    )
    op.create_index(op.f("ix_menu_item_category_id"), "menu_item", ["category_id"], unique=False)
    op.add_column(
        "hotel_settings",
        sa.Column(
            "room_service_open", sa.Time(), server_default=sa.text("'06:00'"), nullable=False
        ),
    )
    op.add_column(
        "hotel_settings",
        sa.Column(
            "room_service_close", sa.Time(), server_default=sa.text("'22:00'"), nullable=False
        ),
    )
    op.add_column(
        "hotel_settings",
        sa.Column(
            "room_service_paused", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "hotel_settings",
        sa.Column(
            "default_prep_minutes", sa.SmallInteger(), server_default=sa.text("25"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("hotel_settings", "default_prep_minutes")
    op.drop_column("hotel_settings", "room_service_paused")
    op.drop_column("hotel_settings", "room_service_close")
    op.drop_column("hotel_settings", "room_service_open")
    op.drop_index(op.f("ix_menu_item_category_id"), table_name="menu_item")
    op.drop_table("menu_item")
    op.drop_index("ix_status_history_entity", table_name="status_history")
    op.drop_table("status_history")
    op.drop_table("menu_category")
