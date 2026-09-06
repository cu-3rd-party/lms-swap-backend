"""Модели: студент, заказ на обмен, найденное совпадение."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# Статусы заказа
ORDER_OPEN = "open"
ORDER_MATCHED = "matched"
ORDER_COMPLETED = "completed"
ORDER_CANCELLED = "cancelled"

# Статусы совпадения
MATCH_PENDING = "pending"
MATCH_COMPLETED = "completed"
MATCH_DECLINED = "declined"

# Способы связи
CONTACT_CU_EMAIL = "cu_email"
CONTACT_TELEGRAM = "telegram"
CONTACT_CUSTOM = "custom"
CONTACT_TYPES = (CONTACT_CU_EMAIL, CONTACT_TELEGRAM, CONTACT_CUSTOM)


class Student(Base):
    """Студент. `id` — тот же UUID, что LMS отдаёт в /api/student-hub/students/me.

    Персональные данные из LMS сюда не переносятся: сервису достаточно
    идентификатора и одного контакта, который студент выбрал сам.
    """

    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    contact_type: Mapped[str] = mapped_column(String(16), nullable=False)
    contact_value: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )

    orders: Mapped[list[Order]] = relationship(back_populates="student")
    device_keys: Mapped[list[DeviceKey]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "contact_type in ('cu_email', 'telegram', 'custom')",
            name="ck_students_contact_type",
        ),
    )


class DeviceKey(Base):
    """Ключ устройства, через который студент ходит на биржу.

    Ключей у студента несколько: браузеры не делят `storage.local`, поэтому
    Chrome и Firefox генерируют разные, а переустановка расширения даёт ещё
    один. Хранится только sha256 — сам ключ живёт лишь в браузере.

    Добавить ключ может любой, кто знает `student_id`. Это осознанный размен:
    перечислить чужие идентификаторы через API LMS нельзя (все списочные
    ручки закрыты), а без этого биржа ломалась у каждого, кто открыл LMS во
    втором браузере.
    """

    __tablename__ = "device_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    student: Mapped[Student] = relationship(back_populates="device_keys")

    __table_args__ = (
        UniqueConstraint("student_id", "key_hash", name="uq_device_keys_student_key"),
        Index("ix_device_keys_lookup", "student_id", "key_hash"),
    )


class Order(Base):
    """Заказ: «отдаю слот `offered_event_id`, хочу `wanted_event_id`».

    Оба слота относятся к одной и той же строке расписания
    (course_id + event_type + event_row_number) — иначе обмен невозможен:
    LMS позволяет пересесть только внутри одной строки.
    """

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )

    course_id: Mapped[int] = mapped_column(Integer, nullable=False)
    course_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_row_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    offered_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    offered_label: Mapped[str] = mapped_column(String(255), nullable=False)
    wanted_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    wanted_label: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ORDER_OPEN)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )

    student: Mapped[Student] = relationship(back_populates="orders")

    __table_args__ = (
        # Один и тот же желаемый слот нельзя заказать дважды.
        UniqueConstraint(
            "student_id",
            "course_id",
            "event_type",
            "event_row_number",
            "wanted_event_id",
            name="uq_orders_student_wanted",
        ),
        CheckConstraint(
            "offered_event_id <> wanted_event_id", name="ck_orders_offer_ne_want"
        ),
        # Матчер ищет встречный заказ по этой четвёрке.
        Index(
            "ix_orders_lookup",
            "status",
            "course_id",
            "event_type",
            "event_row_number",
        ),
    )


class Match(Base):
    """Найденная взаимная пара заказов (2-цикл).

    Контакты сторон раскрываются только через этот объект: пока совпадения
    нет, чужой контакт не отдаётся никому.
    """

    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_a_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    order_b_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=MATCH_PENDING)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )

    order_a: Mapped[Order] = relationship(foreign_keys=[order_a_id])
    order_b: Mapped[Order] = relationship(foreign_keys=[order_b_id])

    __table_args__ = (
        UniqueConstraint("order_a_id", "order_b_id", name="uq_matches_pair"),
        Index("ix_matches_order_a", "order_a_id"),
        Index("ix_matches_order_b", "order_b_id"),
    )
