"""Фоновые задачи (ADR-1): реестр и интерфейс.

Контракт одинаков для single и scaled:
- задача = имя из ``TaskRegistry`` + JSON-сериализуемый ``dict`` (проверяется в ``enqueue``);
- обработчики идемпотентны (в scaled возможен повтор);
- отложенные задачи в single живут в памяти и теряются при перезапуске, поэтому
  бизнес-критичные таймеры делаются периодическим «подметанием» по БД (``@registry.periodic``);
- периодические задачи в scaled выполняет только worker, в single — единственный процесс.

Реализации: ``app/core/single/scheduler.py`` (APScheduler), ``app/core/scaled/scheduler.py`` (arq).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

TaskPayload = dict[str, Any]
TaskHandler = Callable[[TaskPayload], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PeriodicTask:
    """Периодическая задача. ``every_minutes`` делит 60 либо кратно 60 и делит 1440,
    чтобы интервал однозначно выражался и в APScheduler, и в arq cron."""

    name: str
    every_minutes: int

    def __post_init__(self) -> None:
        raise NotImplementedError


class TaskRegistry:
    """Единый реестр задач; из него строятся и APScheduler (single), и arq WorkerSettings (scaled)."""

    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        self._periodic: dict[str, PeriodicTask] = {}

    def task(self, name: str) -> Callable[[TaskHandler], TaskHandler]:
        """Декоратор: зарегистрировать обработчик задачи. Повторное имя — ValueError."""
        raise NotImplementedError

    def periodic(self, name: str, *, every_minutes: int) -> Callable[[TaskHandler], TaskHandler]:
        """Декоратор: зарегистрировать обработчик и расписание. Обработчик получает пустой payload."""
        raise NotImplementedError

    def get(self, name: str) -> TaskHandler:
        """Обработчик по имени; неизвестное имя — KeyError."""
        raise NotImplementedError

    @property
    def handlers(self) -> dict[str, TaskHandler]:
        return dict(self._handlers)

    @property
    def periodic_tasks(self) -> list[PeriodicTask]:
        return list(self._periodic.values())


class TaskScheduler(ABC):
    """Постановка фоновых задач в очередь / по таймеру."""

    async def start(self) -> None:  # noqa: B027 — no-op по умолчанию
        """Запуск (single: старт APScheduler и периодических задач; scaled: пул соединений)."""

    async def stop(self) -> None:  # noqa: B027 — no-op по умолчанию
        """Остановка; незавершённые задачи single не переживают остановку."""

    @abstractmethod
    async def enqueue(
        self,
        name: str,
        payload: TaskPayload | None = None,
        *,
        delay: timedelta | None = None,
        job_id: str | None = None,
    ) -> str:
        """Поставить задачу. ``job_id`` — ключ дедупликации (повтор с тем же id не создаёт вторую задачу).

        Возвращает id задачи. Неизвестное имя → KeyError; несериализуемый payload → TypeError.
        """

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Отменить ещё не начатую задачу. True — отменена, False — не найдена/уже выполняется."""
