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

import asyncio
import logging
from enum import StrEnum

from app.db.session import Database
from app.seed.guard import demo_tenant_exists

logger = logging.getLogger(__name__)

DEMO_FOUND_WARNING = (
    "В базе найдено демо-заведение при APP_ENV=prod: его столы открываются по QR-токенам из публичного "
    "репозитория. Приложение не готово (/health/ready — 503). Удалите демо-заведение или проверьте, "
    "к какой базе подключено приложение (DATABASE_URL)."
)
DEMO_CHECK_FAILED = "Проверка демо-данных не выполнена, приложение считается неготовым: %s"
DEMO_GONE_INFO = "Демо-заведение в базе больше не найдено"
DEMO_CHECK_TIMEOUT_TEXT = "превышен таймаут проверки ({timeout:g} с)"

_EXTRA = {"component": "demo_data"}


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

        Исключение или таймаут → ``UNKNOWN`` (текст — через ``database.describe_error``, для
        таймаута — ``DEMO_CHECK_TIMEOUT_TEXT``); ``CancelledError`` не перехватывается. Никогда
        не бросает иное. Обновляет состояние через ``_transition``; возвращает новое состояние."""
        deadline = asyncio.timeout(self._check_timeout)
        try:
            async with deadline:
                async with database.session() as session:
                    found = await demo_tenant_exists(session)
        except TimeoutError as exc:
            # TimeoutError мог прийти и от драйвера (не наш таймаут) — тогда текст драйвера, замаскированный.
            if deadline.expired():
                error_text = DEMO_CHECK_TIMEOUT_TEXT.format(timeout=self._check_timeout)
            else:
                error_text = database.describe_error(exc)
            return self._transition(DemoDataState.UNKNOWN, error_text)
        except Exception as exc:
            return self._transition(DemoDataState.UNKNOWN, database.describe_error(exc))
        return self._transition(DemoDataState.FOUND if found else DemoDataState.ABSENT)

    def _transition(self, new: DemoDataState, error_text: str | None = None) -> DemoDataState:
        """Сохранить состояние; при смене — запись в лог (см. docstring модуля), extra ``component="demo_data"``.

        Без ``exc_info``: traceback драйвера может содержать строку подключения. Возвращает ``new``."""
        old, self._state = self._state, new
        if old is new:
            return new
        if new is DemoDataState.FOUND:
            logger.warning(DEMO_FOUND_WARNING, extra=_EXTRA)
        elif new is DemoDataState.UNKNOWN:
            logger.warning(DEMO_CHECK_FAILED, error_text or "причина неизвестна", extra=_EXTRA)
        elif old is DemoDataState.FOUND:
            logger.info(DEMO_GONE_INFO, extra=_EXTRA)
        return new
