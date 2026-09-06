"""Авторизация по ключу устройства.

Токен LMS достать нельзя — сессия живёт в HttpOnly-куках, поэтому сервер не
может переспросить у LMS, кто пришёл. Вместо этого студент при первом
обращении регистрирует ключ, сгенерированный расширением, и дальше подписывает
им каждый запрос.

Ключей у студента может быть несколько — по одному на браузер. Добавить ключ
может любой, кто знает `student_id`; перечислить чужие идентификаторы через
API LMS нельзя, а строгая привязка к одному устройству ломала биржу у всех,
кто открыл LMS во втором браузере.
"""

import hashlib

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DeviceKey, Student


def hash_device_key(device_key: str) -> str:
    return hashlib.sha256(device_key.encode("utf-8")).hexdigest()


def current_student(
    authorization: str = Header(default=""),
    x_student_id: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Student:
    if not authorization.startswith("Bearer ") or not x_student_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="нужны заголовки Authorization: Bearer <device_key> и X-Student-Id",
        )

    device_key = authorization.removeprefix("Bearer ").strip()
    student = db.get(Student, x_student_id)
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="студент не зарегистрирован"
        )

    known = db.scalar(
        select(DeviceKey).where(
            DeviceKey.student_id == student.id,
            DeviceKey.key_hash == hash_device_key(device_key),
        )
    )
    if known is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="это устройство не зарегистрировано"
        )

    return student
