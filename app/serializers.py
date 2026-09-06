"""Сборка ответов: заказ + совпадение с точки зрения конкретного студента."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.matching import matches_for_orders
from app.models import Match, Order, Student
from app.schemas import MatchOut, OrderOut


def _counterpart_order(match: Match, order: Order) -> Order:
    return match.order_b if match.order_a_id == order.id else match.order_a


def build_match_out(db: Session, match: Match, order: Order) -> MatchOut | None:
    other = _counterpart_order(match, order)
    other_student = db.get(Student, other.student_id)
    if other_student is None:
        return None

    return MatchOut(
        id=match.id,
        status=match.status,
        counterpart_contact_type=other_student.contact_type,
        counterpart_contact_value=other_student.contact_value,
        # Что вторая сторона отдаёт — это ровно то, что получит первая.
        counterpart_gives_label=other.offered_label,
        counterpart_wants_label=other.wanted_label,
        created_at=match.created_at,
    )


def build_orders_out(db: Session, orders: list[Order]) -> list[OrderOut]:
    found = matches_for_orders(db, [o.id for o in orders])
    result: list[OrderOut] = []
    for order in orders:
        out = OrderOut.model_validate(order)
        match = found.get(order.id)
        if match is not None:
            out.match = build_match_out(db, match, order)
        result.append(out)
    return result
