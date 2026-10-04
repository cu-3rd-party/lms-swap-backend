"""Настройки сервиса. Всё читается из окружения, значения по умолчанию рассчитаны
на локальный запуск через docker compose."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # postgresql+psycopg://user:pass@host:5432/db — в тестах подменяется на sqlite
    database_url: str = "postgresql+psycopg://swap:swap@db:5432/swap"

    # Как часто фоновой матчер пересматривает открытые заказы. Матчинг также
    # запускается синхронно при создании каждого заказа, так что цикл нужен
    # только чтобы подобрать пары, оставшиеся после отмен и ошибок.
    match_interval_seconds: int = 30

    # Сколько одновременно открытых заказов может держать один студент.
    max_open_orders_per_student: int = 20

    # Рубильник биржи. Пока выключена, сервис не принимает ни регистраций, ни
    # заказов, а расширение по /status понимает это и не рисует свои кнопки.
    # Смысл в том, что обмен привязан к окну записи на пары в LMS: когда окно
    # закрыто, пересесть всё равно нельзя, и заказы только путали бы людей.
    swap_enabled: bool = True
    swap_disabled_message: str = (
        "Биржа обмена парами сейчас закрыта: в LMS нет окна записи на пары, "
        "пересесть всё равно не выйдет. Как только запись откроется снова, "
        "заказы заработают — и этот блок сам об этом узнает."
    )

    # Сколько браузеров может помнить один студент. Больше — самый старый
    # ключ вытесняется, чтобы таблица не росла от повторных регистраций.
    max_device_keys_per_student: int = 10

    # Максимальная длина произвольного контакта (вариант «указать иное»).
    max_contact_length: int = 200

    # CORS: расширение ходит из background-скрипта, origin у него
    # chrome-extension://<id> / moz-extension://<uuid> и заранее неизвестен.
    # Куки не используются, авторизация — заголовком, поэтому «*» безопасно.
    cors_origins: list[str] = ["*"]

    log_level: str = "INFO"


    @field_validator("swap_disabled_message")
    @classmethod
    def keep_default_when_blank(cls, value: str) -> str:
        """docker compose подставляет пустую строку, если переменной нет в .env.
        Пустое сообщение показывать нечего, поэтому возвращаем текст по умолчанию."""
        return value.strip() or cls.model_fields["swap_disabled_message"].default


@lru_cache
def get_settings() -> Settings:
    return Settings()
