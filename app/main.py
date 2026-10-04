"""Точка входа: FastAPI-приложение и фоновой матчер.

Сервис хранит заказы на обмен парами для расширения CU LMS Enhancer:
https://github.com/cu-3rd-party/lms-extension
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import switch
from app.config import get_settings
from app.db import SessionLocal
from app.matching import run_sweep
from app.routers import matches, orders, students

settings = get_settings()
logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)


def _sweep_loop(stop: threading.Event) -> None:
    """Периодически пересматривает открытые заказы.

    Основной матчинг происходит синхронно при создании заказа. Этот цикл
    подбирает то, что стало сватабельным позже: после отмен, отклонённых
    совпадений и упавших транзакций.
    """
    while not stop.wait(settings.match_interval_seconds):
        db = SessionLocal()
        try:
            created = run_sweep(db)
            if created:
                log.info("фоновой проход: найдено совпадений — %d", created)
        except Exception:
            # Цикл не должен умирать из-за одной неудачной итерации.
            log.exception("фоновой проход упал")
            with suppress(Exception):
                db.rollback()
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    thread = threading.Thread(target=_sweep_loop, args=(stop,), daemon=True, name="matcher")
    thread.start()
    log.info("матчер запущен, интервал %d с", settings.match_interval_seconds)
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


app = FastAPI(
    title="LMS Swap Backend",
    description="Биржа обмена парами для расширения CU LMS Enhancer",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Student-Id"],
)

app.include_router(students.router)
app.include_router(orders.router)
app.include_router(matches.router)


@app.get("/api/v1/health", tags=["service"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/status", tags=["service"])
def swap_status() -> dict:
    """Включена ли биржа. Без авторизации — расширение спрашивает это первым,
    ещё до того, как выяснять, кто за браузером: если биржа выключена, личность
    студента сервису не нужна вовсе."""
    enabled = switch.is_enabled()
    return {"enabled": enabled, "message": None if enabled else switch.disabled_message()}
