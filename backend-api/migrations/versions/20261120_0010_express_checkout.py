"""express checkout: checkout_request and stay_charge

Revision ID: 0010_express_checkout
Revises: 0009_chat_message
Create Date: 2026-11-20 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_express_checkout"
down_revision: str | None = "0009_chat_message"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("CHECKOUT_REQUESTED", "BILLING_VERIFIED", "COMPLETED", "REJECTED")


def _staff_fk(column: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["staff.id"], name=op.f(f"fk_{table}_{column}_staff"))


def upgrade() -> None:
    op.create_table(
        "checkout_request",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stay_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Enum(*STATUSES, name="checkout_status"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("feedback_rating", sa.SmallInteger(), nullable=True),
        sa.Column("feedback_note", sa.Text(), nullable=True),
        sa.Column("bill_snapshot", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("total_vnd", sa.BigInteger(), nullable=True),
        sa.Column("payment_method", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("verified_by", sa.UUID(), nullable=True),
        sa.Column("completed_by", sa.UUID(), nullable=True),
        sa.Column("rejected_by", sa.UUID(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
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
            "feedback_rating IS NULL OR feedback_rating BETWEEN 1 AND 5",
            name=op.f("ck_checkout_request_rating_range"),
        ),
        sa.CheckConstraint(
            "source IN ('APP', 'CHATBOT')", name=op.f("ck_checkout_request_source_known")
        ),
        sa.ForeignKeyConstraint(
            ["stay_id"], ["stay.id"], name=op.f("fk_checkout_request_stay_id_stay")
        ),
        _staff_fk("verified_by", "checkout_request"),
        _staff_fk("completed_by", "checkout_request"),
        _staff_fk("rejected_by", "checkout_request"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkout_request")),
    )
    op.create_index(op.f("ix_checkout_request_stay_id"), "checkout_request", ["stay_id"])
    op.create_index(
        "uq_checkout_request_open_per_stay",
        "checkout_request",
        ["stay_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('CHECKOUT_REQUESTED', 'BILLING_VERIFIED')"),
    )

    op.create_table(
        "stay_charge",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stay_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_vnd", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_vnd > 0", name=op.f("ck_stay_charge_amount_positive")),
        sa.CheckConstraint("kind IN ('EXTRA', 'DISCOUNT')", name=op.f("ck_stay_charge_kind_known")),
        sa.ForeignKeyConstraint(["stay_id"], ["stay.id"], name=op.f("fk_stay_charge_stay_id_stay")),
        _staff_fk("created_by", "stay_charge"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stay_charge")),
    )
    op.create_index(op.f("ix_stay_charge_stay_id"), "stay_charge", ["stay_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_stay_charge_stay_id"), table_name="stay_charge")
    op.drop_table("stay_charge")
    op.drop_index("uq_checkout_request_open_per_stay", table_name="checkout_request")
    op.drop_index(op.f("ix_checkout_request_stay_id"), table_name="checkout_request")
    op.drop_table("checkout_request")
    sa.Enum(name="checkout_status").drop(op.get_bind(), checkfirst=True)
