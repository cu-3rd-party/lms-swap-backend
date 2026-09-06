"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-06

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_key_hash", sa.String(length=64), nullable=False),
        sa.Column("contact_type", sa.String(length=16), nullable=False),
        sa.Column("contact_value", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "contact_type in ('cu_email', 'telegram', 'custom')",
            name="ck_students_contact_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("student_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("event_row_number", sa.Integer(), nullable=False),
        sa.Column("offered_event_id", sa.String(length=36), nullable=False),
        sa.Column("offered_label", sa.String(length=255), nullable=False),
        sa.Column("wanted_event_id", sa.String(length=36), nullable=False),
        sa.Column("wanted_label", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("offered_event_id <> wanted_event_id", name="ck_orders_offer_ne_want"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "student_id",
            "course_id",
            "event_type",
            "event_row_number",
            "wanted_event_id",
            name="uq_orders_student_wanted",
        ),
    )
    op.create_index(
        "ix_orders_lookup",
        "orders",
        ["status", "course_id", "event_type", "event_row_number"],
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_a_id", sa.String(length=36), nullable=False),
        sa.Column("order_b_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_a_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_b_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_a_id", "order_b_id", name="uq_matches_pair"),
    )
    op.create_index("ix_matches_order_a", "matches", ["order_a_id"])
    op.create_index("ix_matches_order_b", "matches", ["order_b_id"])


def downgrade() -> None:
    op.drop_index("ix_matches_order_b", table_name="matches")
    op.drop_index("ix_matches_order_a", table_name="matches")
    op.drop_table("matches")
    op.drop_index("ix_orders_lookup", table_name="orders")
    op.drop_table("orders")
    op.drop_table("students")
