"""Демо-заведение в базе при ``APP_ENV=prod`` (#71, arch ``docs/arch/feature-60-demo-data-guard.md``, ADR-60.2).

``DemoDataMonitor`` — один объект на приложение (``app.state.demo_data_monitor``, создаёт
``create_app``; зависимость ``get_demo_data_monitor`` в ``app/api/deps.py``). Его вызывают:

1. lifespan — один раз после ``start_container`` при ``APP_ENV=prod`` (чтобы предупреждение
   попало в лог и там, где ``/health/ready`` никто не опрашивает: служба Windows, ``single``);
2. ``GET /health/ready`` — на каждом запросе при ``APP_ENV=prod``, параллельно с ``database``.

Вне prod не вызывается вовсе. Результат ``FOUND`` или ``UNKNOWN`` → readiness 503 ``not_ready``;
тело ``/health/ready`` при этом не меняется (ключа для демо в ``checks`` нет, ADR-60.3).

Лог — только при смене состояния (без спама при частых опросах): → ``FOUND`` — WARNING
``DEMO_FOUND_WARNING``; → ``UNKNOWN`` — WARNING ``DEMO_CHECK_FAILED`` с ``Database.describe_error``;
``FOUND`` → ``ABSENT`` — INFO ``DEMO_GONE_INFO``. Первое ``ABSENT`` после старта — без записи.
Строки подключения в лог не попадают. Redis и интерфейсы режима не используются (одинаково в
``single``/``scaled``); в ``scaled`` с несколькими воркерами uvicorn каждый процесс пишет свой лог.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from app.db.session import Database

logger = logging.getLogger(__name__)

DEMO_FOUND_WARNING = (
    "В базе найдено демо-заведение при APP_ENV=prod: его столы открываются по QR-токенам из публичного "
    "репозитория. Приложение не готово (/health/ready — 503). Удалите демо-заведение или проверьте, "
    "к какой базе подключено приложение (DATABASE_URL)."
)
DEMO_CHECK_FAILED = "Проверка демо-данных не выполнена, приложение считается неготовым: %s"
DEMO_GONE_INFO = "Демо-заведение в базе больше не найдено"


class DemoDataState(StrEnum):
    UNKNOWN = "unknown"  # ошибка БД или таймаут: не считается «демо нет» (NFR-5 spec)
    ABSENT = "absent"
    FOUND = "found"


class DemoDataMonitor:
    """Последнее известное состояние и запись в лог при его смене."""

    def __init__(self, check_timeout: float) -> None:
        """``check_timeout`` — секунды на одну проверку; ``create_app`` передаёт ``READINESS_CHECK_TIMEOUT`` (2 с)."""
        self._check_timeout = check_timeout
        self._state: DemoDataState | None = None  # None — проверок ещё не было

    @property
    def state(self) -> DemoDataState | None:
        return self._state

    async def refresh(self, database: Database) -> DemoDataState:
        """``database.session()`` + ``app.seed.guard.demo_tenant_exists`` под ``asyncio.timeout(check_timeout)``.

        Исключение или таймаут → ``UNKNOWN`` (текст — через ``database.describe_error``);
        ``CancelledError`` не перехватывается. Никогда не бросает иное. Обновляет состояние
        через ``_transition``; возвращает новое состояние."""
        raise NotImplementedError

    def _transition(self, new: DemoDataState, error_text: str | None = None) -> None:
        """Сохранить состояние; при смене — запись в лог (см. docstring модуля), extra ``component="demo_data"``."""
        raise NotImplementedError
