"""Закрытие совпадения."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_student
from app.db import get_db
from app.models import (
    MATCH_COMPLETED,
    ORDER_COMPLETED,
    ORDER_MATCHED,
    Match,
    Order,
    Student,
)
from app.switch import require_enabled

router = APIRouter(prefix="/api/v1", tags=["matches"])


@router.post("/matches/{match_id}/close", status_code=status.HTTP_204_NO_CONTENT)
def close(
    match_id: str,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
    _: None = Depends(require_enabled),
) -> None:
    """Убирает совпадение у того, кто нажал, — вторая сторона своё ещё видит.

    Дальше сервису делать нечего: договорились студенты или нет, местами их
    меняет куратор. Закрытый заказ пропадает из выдачи, чтобы в интерфейсе не
    висела карточка, с которой уже нечего делать.
    """
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="совпадение не найдено")

    orders = list(
        db.scalars(select(Order).where(Order.id.in_([match.order_a_id, match.order_b_id])))
    )
    mine = next((o for o in orders if o.student_id == student.id), None)
    if mine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="совпадение не найдено")

    mine.status = ORDER_COMPLETED

    # Когда обе стороны нажали ОК, закрываем и само совпадение.
    if all(o.status != ORDER_MATCHED for o in orders):
        match.status = MATCH_COMPLETED

    db.commit()
