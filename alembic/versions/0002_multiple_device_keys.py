"""несколько ключей устройства на студента

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06

Ключ переезжает из students.device_key_hash в отдельную таблицу: Chrome и
Firefox не делят storage.local, поэтому у одного студента ключей несколько.
Существующие ключи переносятся, никто не теряет доступ.
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("student_id", sa.String(length=36), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "key_hash", name="uq_device_keys_student_key"),
    )
    op.create_index("ix_device_keys_lookup", "device_keys", ["student_id", "key_hash"])

    # Перенос делаем на стороне Python, а не SQL: генерация UUID в Postgres и
    # SQLite выглядит по-разному, а строк тут единицы.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, device_key_hash, created_at FROM students")
    ).fetchall()
    for student_id, key_hash, created_at in rows:
        conn.execute(
            sa.text(
                "INSERT INTO device_keys (id, student_id, key_hash, created_at)"
                " VALUES (:id, :student_id, :key_hash, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "student_id": student_id,
                "key_hash": key_hash,
                "created_at": created_at,
            },
        )

    op.drop_column("students", "device_key_hash")


def downgrade() -> None:
    op.add_column("students", sa.Column("device_key_hash", sa.String(length=64), nullable=True))

    conn = op.get_bind()
    # Возвращаем самый свежий ключ каждого студента — остальные при откате
    # теряются, схема на один ключ их вместить не может.
    rows = conn.execute(
        sa.text(
            "SELECT student_id, key_hash FROM device_keys"
            " ORDER BY student_id, created_at ASC"
        )
    ).fetchall()
    for student_id, key_hash in rows:
        conn.execute(
            sa.text("UPDATE students SET device_key_hash = :key_hash WHERE id = :student_id"),
            {"key_hash": key_hash, "student_id": student_id},
        )

    conn.execute(sa.text("DELETE FROM students WHERE device_key_hash IS NULL"))

    op.drop_index("ix_device_keys_lookup", table_name="device_keys")
    op.drop_table("device_keys")
