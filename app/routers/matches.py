"""Подтверждение и отклонение совпадений."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_student
from app.db import get_db
from app.models import (
    MATCH_COMPLETED,
    MATCH_DECLINED,
    MATCH_PENDING,
    ORDER_COMPLETED,
    ORDER_OPEN,
    Match,
    Order,
    Student,
)

router = APIRouter(prefix="/api/v1", tags=["matches"])


def _load_own_match(db: Session, match_id: str, student: Student) -> tuple[Match, Order, Order]:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="совпадение не найдено")

    orders = list(
        db.scalars(select(Order).where(Order.id.in_([match.order_a_id, match.order_b_id])))
    )
    mine = next((o for o in orders if o.student_id == student.id), None)
    other = next((o for o in orders if o.student_id != student.id), None)
    if mine is None or other is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="совпадение не найдено")

    return match, mine, other


@router.post("/matches/{match_id}/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm(
    match_id: str,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
) -> None:
    """Обмен состоялся — закрываем оба заказа.

    Пересаживает студентов сама LMS, сервис только перестаёт их сватать.
    Достаточно подтверждения одной стороны: если обмен не состоялся, вторая
    сторона нажмёт «не получилось» и вернётся в поиск.
    """
    match, mine, other = _load_own_match(db, match_id, student)
    if match.status != MATCH_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="совпадение уже закрыто")

    match.status = MATCH_COMPLETED
    mine.status = ORDER_COMPLETED
    other.status = ORDER_COMPLETED
    db.commit()


@router.post("/matches/{match_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
def decline(
    match_id: str,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
) -> None:
    """Не договорились. Оба заказа возвращаются в поиск.

    Match остаётся в базе со статусом declined, чтобы матчер не свёл ту же
    пару снова на следующем же проходе.
    """
    match, mine, other = _load_own_match(db, match_id, student)
    if match.status != MATCH_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="совпадение уже закрыто")

    match.status = MATCH_DECLINED
    mine.status = ORDER_OPEN
    other.status = ORDER_OPEN
    db.commit()
