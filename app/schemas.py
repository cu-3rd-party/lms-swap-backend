"""Pydantic-схемы запросов и ответов."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ContactType = Literal["cu_email", "telegram", "custom"]
EventType = Literal["lecture", "seminar"]


class ContactIn(BaseModel):
    contact_type: ContactType
    contact_value: str = Field(min_length=1, max_length=200)

    @field_validator("contact_value")
    @classmethod
    def strip_value(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("контакт не может быть пустым")
        return v


class RegisterIn(ContactIn):
    """Первичная привязка студента к устройству.

    `device_key` расширение генерирует само и хранит в browser.storage.local.
    Сервер держит только его sha256.
    """

    student_id: str = Field(min_length=36, max_length=36)
    device_key: str = Field(min_length=32, max_length=128)


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    contact_type: ContactType
    contact_value: str
    created_at: datetime


class OrderIn(BaseModel):
    course_id: int
    course_name: str = Field(min_length=1, max_length=255)
    event_type: EventType
    event_row_number: int = Field(default=1, ge=1)

    offered_event_id: str = Field(min_length=36, max_length=36)
    offered_label: str = Field(min_length=1, max_length=255)
    wanted_event_id: str = Field(min_length=36, max_length=36)
    wanted_label: str = Field(min_length=1, max_length=255)


class MatchOut(BaseModel):
    """То, что видит одна из сторон совпадения.

    `counterpart_contact_*` заполняются только при status == 'pending' или
    'completed' — то есть когда обе стороны действительно совпали.
    """

    id: str
    status: str
    counterpart_contact_type: ContactType
    counterpart_contact_value: str
    counterpart_gives_label: str
    counterpart_wants_label: str
    created_at: datetime


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: int
    course_name: str
    event_type: EventType
    event_row_number: int
    offered_event_id: str
    offered_label: str
    wanted_event_id: str
    wanted_label: str
    status: str
    created_at: datetime
    match: MatchOut | None = None


class OrdersOut(BaseModel):
    student: StudentOut
    orders: list[OrderOut]


class DemandOut(BaseModel):
    """Сколько людей готовы отдать конкретный слот — подсказка в интерфейсе
    ещё до того, как заказ создан."""

    wanted_event_id: str
    offers: int
