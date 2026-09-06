"""Авторизация по ключу устройства (TOFU).

Токен LMS достать нельзя — сессия живёт в HttpOnly-куках, поэтому сервер не
может переспросить у LMS, кто пришёл. Вместо этого работает привязка при
первом обращении: кто первым зарегистрировал `student_id`, тот и владеет им.
Дальше каждый запрос подписывается ключом устройства.
"""

import hashlib
import hmac

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Student


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

    # compare_digest, чтобы сравнение не зависело от длины совпадающего префикса
    if not hmac.compare_digest(student.device_key_hash, hash_device_key(device_key)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="неверный ключ устройства"
        )

    return student
