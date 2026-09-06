"""Поиск взаимных пар (2-цикл).

Совпадение — это два открытых заказа A и B в одной строке расписания
(course_id + event_type + event_row_number), где

    A.offered_event_id == B.wanted_event_id
    A.wanted_event_id  == B.offered_event_id

то есть каждый хочет ровно то, что отдаёт другой.

Гонок нет без явных блокировок: переход open -> matched делается одним
UPDATE ... WHERE status = 'open'. Если параллельный процесс успел раньше,
затронутых строк окажется меньше двух, транзакция откатывается и пара
пропускается.
"""

from __future__ import annotations

import logging

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.models import ORDER_MATCHED, ORDER_OPEN, Match, Order

log = logging.getLogger(__name__)


def find_counterparts(db: Session, order: Order) -> list[Order]:
    """Открытые заказы, зеркальные к `order`, от других студентов."""
    stmt = (
        select(Order)
        .where(
            Order.status == ORDER_OPEN,
            Order.student_id != order.student_id,
            Order.course_id == order.course_id,
            Order.event_type == order.event_type,
            Order.event_row_number == order.event_row_number,
            Order.offered_event_id == order.wanted_event_id,
            Order.wanted_event_id == order.offered_event_id,
        )
        # Самый давний заказ получает совпадение первым — иначе те, кто
        # заказал раньше, ждали бы бесконечно.
        .order_by(Order.created_at.asc())
    )
    return list(db.scalars(stmt))


def try_match_order(db: Session, order: Order) -> Match | None:
    """Пытается сосватать конкретный заказ. Коммитит сам."""
    for counterpart in find_counterparts(db, order):
        match = _commit_pair(db, order, counterpart)
        if match is not None:
            return match
    return None


def _commit_pair(db: Session, a: Order, b: Order) -> Match | None:
    """Переводит оба заказа в matched и создаёт Match. None — если не вышло."""
    # Пара всегда хранится в одном порядке (меньший id первым), иначе одна и та
    # же пара легла бы в базу дважды — как (A, B) и как (B, A) — и уникальный
    # индекс не поймал бы повторное сватовство уже отклонённой пары.
    if a.id > b.id:
        a, b = b, a

    if db.scalar(
        select(Match).where(Match.order_a_id == a.id, Match.order_b_id == b.id)
    ) is not None:
        # Эти двое уже сводились и разошлись — второй раз не предлагаем.
        return None

    result = db.execute(
        update(Order)
        .where(Order.id.in_([a.id, b.id]), Order.status == ORDER_OPEN)
        .values(status=ORDER_MATCHED)
    )
    if result.rowcount != 2:
        # Кто-то из двоих уже занят или отменён — откатываемся и пробуем дальше.
        db.rollback()
        return None

    match = Match(order_a_id=a.id, order_b_id=b.id)
    db.add(match)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None

    db.refresh(match)
    log.info(
        "match %s: %s <-> %s (курс %s, %s %s)",
        match.id,
        a.id,
        b.id,
        a.course_id,
        a.event_type,
        a.event_row_number,
    )
    return match


def run_sweep(db: Session) -> int:
    """Полный проход по открытым заказам. Возвращает число созданных пар.

    Нужен потому, что заказ мог стать сватабельным не в момент создания:
    встречная сторона отменила совпадение, студент поменял слот и так далее.
    """
    a = aliased(Order)
    b = aliased(Order)
    stmt = (
        select(a, b)
        .join(
            b,
            and_(
                b.status == ORDER_OPEN,
                b.course_id == a.course_id,
                b.event_type == a.event_type,
                b.event_row_number == a.event_row_number,
                b.offered_event_id == a.wanted_event_id,
                b.wanted_event_id == a.offered_event_id,
                b.student_id != a.student_id,
                # Каждую пару берём один раз, а не дважды в обе стороны.
                b.id > a.id,
            ),
        )
        .where(a.status == ORDER_OPEN)
        .order_by(a.created_at.asc())
    )

    created = 0
    # Список материализуем целиком: внутри цикла статусы меняются, и ленивый
    # курсор по изменяемой таблице повёл бы себя по-разному в PG и SQLite.
    for order_a, order_b in list(db.execute(stmt).all()):
        if _commit_pair(db, order_a, order_b) is not None:
            created += 1
    return created


def matches_for_orders(db: Session, order_ids: list[str]) -> dict[str, Match]:
    """Актуальное совпадение для каждого из заказов (если есть)."""
    if not order_ids:
        return {}
    stmt = select(Match).where(
        or_(Match.order_a_id.in_(order_ids), Match.order_b_id.in_(order_ids))
    )
    found: dict[str, Match] = {}
    for match in db.scalars(stmt):
        found[match.order_a_id] = match
        found[match.order_b_id] = match
    return found
