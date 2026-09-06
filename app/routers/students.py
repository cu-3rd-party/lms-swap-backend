"""Регистрация студента и его способ связи."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_student, hash_device_key
from app.config import get_settings
from app.db import get_db
from app.models import DeviceKey, Student
from app.schemas import ContactIn, RegisterIn, StudentOut

router = APIRouter(prefix="/api/v1", tags=["students"])


def _check_contact_length(value: str) -> None:
    limit = get_settings().max_contact_length
    if len(value) > limit:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"контакт длиннее {limit} символов",
        )


def _register_device_key(db: Session, student_id: str, key_hash: str) -> None:
    """Запоминает ключ устройства, если его ещё нет.

    Старые ключи вытесняются: иначе таблица росла бы от каждой переустановки
    расширения, а живой браузер у студента всё равно один-два.
    """
    already_known = db.scalar(
        select(DeviceKey).where(
            DeviceKey.student_id == student_id, DeviceKey.key_hash == key_hash
        )
    )
    if already_known is not None:
        return

    limit = get_settings().max_device_keys_per_student
    keys = list(
        db.scalars(
            select(DeviceKey)
            .where(DeviceKey.student_id == student_id)
            .order_by(DeviceKey.created_at.asc())
        )
    )
    for stale in keys[: max(0, len(keys) - limit + 1)]:
        db.delete(stale)

    db.add(DeviceKey(student_id=student_id, key_hash=key_hash))


@router.post("/register", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> Student:
    """Регистрирует студента и запоминает ключ устройства, с которого пришли.

    Вызов с новым ключом добавляет ещё одно устройство, а не отклоняется:
    Chrome и Firefox не делят `storage.local`, и строгая привязка к одному
    браузеру ломала биржу у всех, кто открыл LMS во втором. Заодно метод
    обновляет способ связи, так что расширению не нужен отдельный запрос.
    """
    _check_contact_length(payload.contact_value)

    student = db.get(Student, payload.student_id)
    if student is None:
        student = Student(id=payload.student_id)
        db.add(student)

    student.contact_type = payload.contact_type
    student.contact_value = payload.contact_value

    db.flush()
    _register_device_key(db, student.id, hash_device_key(payload.device_key))

    db.commit()
    db.refresh(student)
    return student


@router.get("/me/devices", tags=["students"])
def devices(
    student: Student = Depends(current_student), db: Session = Depends(get_db)
) -> dict[str, int]:
    """Сколько браузеров сейчас помнит биржу. Полезно для отладки."""
    count = db.scalar(
        select(func.count()).select_from(DeviceKey).where(DeviceKey.student_id == student.id)
    )
    return {"devices": count or 0}


@router.get("/me", response_model=StudentOut)
def me(student: Student = Depends(current_student)) -> Student:
    return student


@router.put("/me/contact", response_model=StudentOut)
def update_contact(
    payload: ContactIn,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
) -> Student:
    _check_contact_length(payload.contact_value)
    student.contact_type = payload.contact_type
    student.contact_value = payload.contact_value
    db.add(student)
    db.commit()
    db.refresh(student)
    return student
