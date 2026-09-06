"""Регистрация студента и его способ связи."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import current_student, hash_device_key
from app.config import get_settings
from app.db import get_db
from app.models import Student
from app.schemas import ContactIn, RegisterIn, StudentOut

router = APIRouter(prefix="/api/v1", tags=["students"])


def _check_contact_length(value: str) -> None:
    limit = get_settings().max_contact_length
    if len(value) > limit:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"контакт длиннее {limit} символов",
        )


@router.post("/register", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> Student:
    """Привязывает student_id к ключу устройства.

    Повторный вызов с тем же ключом — не ошибка: расширение переустановили или
    открыли вторую вкладку. Вызов с другим ключом отклоняется, иначе любой
    желающий перехватывал бы чужой идентификатор.
    """
    _check_contact_length(payload.contact_value)
    key_hash = hash_device_key(payload.device_key)

    existing = db.get(Student, payload.student_id)
    if existing is not None:
        if existing.device_key_hash != key_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="этот студент уже привязан к другому устройству",
            )
        existing.contact_type = payload.contact_type
        existing.contact_value = payload.contact_value
        db.commit()
        db.refresh(existing)
        return existing

    student = Student(
        id=payload.student_id,
        device_key_hash=key_hash,
        contact_type=payload.contact_type,
        contact_value=payload.contact_value,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


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
