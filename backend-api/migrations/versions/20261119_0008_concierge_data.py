"""concierge data: knowledge base, nearby places, hotel info settings

Revision ID: 0008_concierge_data
Revises: 0007_housekeeping
Create Date: 2026-11-19 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copies of the generated-column expressions in concierge_data/models.py.
KB_TSV = (
    "setweight(to_tsvector('simple', f_unaccent("
    "coalesce(title_vi, '') || ' ' || coalesce(title_en, ''))), 'A') || "
    "setweight(to_tsvector('simple', f_unaccent("
    "coalesce(content_vi, '') || ' ' || coalesce(content_en, ''))), 'B')"
)
PLACE_TSV = (
    "setweight(to_tsvector('simple', f_unaccent(coalesce(name, ''))), 'A') || "
    "setweight(to_tsvector('simple', f_unaccent("
    "coalesce(description_vi, '') || ' ' || coalesce(description_en, ''))), 'B')"
)

revision: str = "0008_concierge_data"
down_revision: str | None = "0007_housekeeping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KB_TOPICS = ("BREAKFAST", "FACILITIES", "SERVICES", "POLICIES", "WIFI", "TRANSPORT", "OTHER")
PLACE_CATEGORIES = ("ATTRACTION", "FOOD_NEARBY", "TRANSPORT", "SHOPPING", "HEALTH")

# unaccent() is only STABLE, so it cannot feed a generated column; this wrapper pins the
# dictionary and is safe to declare IMMUTABLE (the usual PostgreSQL recipe).
F_UNACCENT = """
CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
"""


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.execute(F_UNACCENT)

    op.create_table(
        "kb_entry",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("topic", sa.Enum(*KB_TOPICS, name="kb_topic"), nullable=False),
        sa.Column("title_vi", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("content_vi", sa.Text(), nullable=False),
        sa.Column("content_en", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(KB_TSV, persisted=True),
            nullable=True,
        ),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["staff.id"],
            name=op.f("fk_kb_entry_updated_by_staff"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_entry")),
    )
    op.create_index(op.f("ix_kb_entry_topic"), "kb_entry", ["topic"])
    op.create_index("ix_kb_entry_search_tsv", "kb_entry", ["search_tsv"], postgresql_using="gin")

    op.create_table(
        "nearby_place",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("category", sa.Enum(*PLACE_CATEGORIES, name="place_category"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description_vi", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("distance_km", sa.Numeric(5, 2), nullable=True),
        sa.Column("open_hours", sa.Text(), nullable=True),
        sa.Column("map_url", sa.Text(), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(PLACE_TSV, persisted=True),
            nullable=True,
        ),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["staff.id"],
            name=op.f("fk_nearby_place_updated_by_staff"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nearby_place")),
    )
    op.create_index(op.f("ix_nearby_place_category"), "nearby_place", ["category"])
    op.create_index(
        "ix_nearby_place_search_tsv", "nearby_place", ["search_tsv"], postgresql_using="gin"
    )

    op.add_column(
        "hotel_settings",
        sa.Column("hotel_name", sa.Text(), server_default=sa.text("'Hotel'"), nullable=False),
    )
    op.add_column(
        "hotel_settings",
        sa.Column("reception_phone", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "hotel_settings",
        sa.Column("default_lang", sa.Text(), server_default=sa.text("'vi'"), nullable=False),
    )
    op.add_column(
        "hotel_settings",
        sa.Column("chat_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    for column in ("chat_enabled", "default_lang", "reception_phone", "hotel_name"):
        op.drop_column("hotel_settings", column)
    op.drop_index("ix_nearby_place_search_tsv", table_name="nearby_place")
    op.drop_index(op.f("ix_nearby_place_category"), table_name="nearby_place")
    op.drop_table("nearby_place")
    op.drop_index("ix_kb_entry_search_tsv", table_name="kb_entry")
    op.drop_index(op.f("ix_kb_entry_topic"), table_name="kb_entry")
    op.drop_table("kb_entry")
    sa.Enum(name="place_category").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="kb_topic").drop(op.get_bind(), checkfirst=True)
    op.execute("DROP FUNCTION IF EXISTS f_unaccent(text)")
