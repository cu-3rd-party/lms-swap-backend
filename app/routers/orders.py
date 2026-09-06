"""Заказы на обмен."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_student
from app.config import get_settings
from app.db import get_db
from app.matching import try_match_order
from app.models import (
    MATCH_PENDING,
    ORDER_CANCELLED,
    ORDER_MATCHED,
    ORDER_OPEN,
    Match,
    Order,
    Student,
)
from app.schemas import DemandOut, OrderIn, OrderOut, OrdersOut, StudentOut
from app.serializers import build_orders_out

router = APIRouter(prefix="/api/v1", tags=["orders"])


@router.get("/orders", response_model=OrdersOut)
def list_orders(
    student: Student = Depends(current_student), db: Session = Depends(get_db)
) -> OrdersOut:
    """Все незакрытые заказы студента вместе с найденными совпадениями.

    Расширение опрашивает этот метод, пока страница открыта, — отсюда и
    появляется «нашлось совпадение» в меню «Мои запросы».
    """
    orders = list(
        db.scalars(
            select(Order)
            .where(Order.student_id == student.id, Order.status != ORDER_CANCELLED)
            .order_by(Order.created_at.desc())
        )
    )
    return OrdersOut(
        student=StudentOut.model_validate(student),
        orders=build_orders_out(db, orders),
    )


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderIn,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
) -> OrderOut:
    if payload.offered_event_id == payload.wanted_event_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="нельзя обменять слот сам на себя",
        )

    open_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.student_id == student.id, Order.status == ORDER_OPEN)
    )
    limit = get_settings().max_open_orders_per_student
    if (open_count or 0) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"уже открыто {limit} заказов, отмени лишние",
        )

    # Уникальный индекс не смотрит на статус, поэтому отменённый или закрытый
    # заказ навсегда занимал бы место и мешал заказать тот же слот повторно.
    # Такой заказ воскрешаем вместо создания нового.
    order = db.scalar(
        select(Order).where(
            Order.student_id == student.id,
            Order.course_id == payload.course_id,
            Order.event_type == payload.event_type,
            Order.event_row_number == payload.event_row_number,
            Order.wanted_event_id == payload.wanted_event_id,
        )
    )

    if order is not None:
        if order.status in (ORDER_OPEN, ORDER_MATCHED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="такой заказ уже есть",
            )
        # Слот, который студент отдаёт, за это время мог поменяться.
        order.offered_event_id = payload.offered_event_id
        order.offered_label = payload.offered_label
        order.wanted_label = payload.wanted_label
        order.status = ORDER_OPEN
        db.commit()
    else:
        order = Order(student_id=student.id, **payload.model_dump())
        db.add(order)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="такой заказ уже есть",
            ) from None

    db.refresh(order)

    # Пытаемся сосватать сразу: если встречный заказ уже лежит, студент увидит
    # совпадение тем же ответом, без ожидания фонового прохода.
    try_match_order(db, order)
    db.refresh(order)

    return build_orders_out(db, [order])[0]


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_order(
    order_id: str,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
) -> None:
    order = db.get(Order, order_id)
    if order is None or order.student_id != student.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="заказ не найден")

    if order.status == ORDER_MATCHED:
        # Отменяя сосватанный заказ, освобождаем и вторую сторону — иначе её
        # заказ навсегда завис бы в matched без пары.
        match = db.scalar(
            select(Match).where(
                (Match.order_a_id == order.id) | (Match.order_b_id == order.id),
                Match.status == MATCH_PENDING,
            )
        )
        if match is not None:
            other_id = match.order_b_id if match.order_a_id == order.id else match.order_a_id
            other = db.get(Order, other_id)
            if other is not None and other.status == ORDER_MATCHED:
                other.status = ORDER_OPEN
            db.delete(match)

    order.status = ORDER_CANCELLED
    db.commit()


@router.get("/demand", response_model=list[DemandOut])
def demand(
    wanted_event_id: list[str] = Query(default=[], max_length=50),
    _: Student = Depends(current_student),
    db: Session = Depends(get_db),
) -> list[DemandOut]:
    """Сколько открытых заказов готовы отдать каждый из указанных слотов.

    Показывает шансы ещё до создания заказа. Ничего личного не раскрывает —
    только счётчик.
    """
    if not wanted_event_id:
        return []

    rows = db.execute(
        select(Order.offered_event_id, func.count())
        .where(Order.status == ORDER_OPEN, Order.offered_event_id.in_(wanted_event_id))
        .group_by(Order.offered_event_id)
    ).all()
    counts = {event_id: count for event_id, count in rows}
    return [DemandOut(wanted_event_id=e, offers=counts.get(e, 0)) for e in wanted_event_id]
