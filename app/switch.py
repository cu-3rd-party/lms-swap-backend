"""Рубильник биржи.

Обмен имеет смысл только пока в LMS открыто окно записи на пары: если
пересесть нельзя, заказы бессмысленны и только вводят людей в заблуждение.
Поэтому сервис умеет полностью выключаться — одним флагом в окружении.

Выключенная биржа не принимает изменений (регистрация, контакт, заказы,
закрытие совпадений отвечают 503), но продолжает отдавать данные на чтение:
так старые заказы можно посмотреть и выгрузить, пока окно закрыто.
"""

from fastapi import HTTPException, status

from app.config import get_settings


def is_enabled() -> bool:
    return get_settings().swap_enabled


def disabled_message() -> str:
    return get_settings().swap_disabled_message


def require_enabled() -> None:
    """Зависимость для всех ручек, которые что-то меняют."""
    if not is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=disabled_message(),
        )
