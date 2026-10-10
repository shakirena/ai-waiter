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

from app.core.payload import ensure_json_object

TaskPayload = dict[str, Any]
TaskHandler = Callable[[TaskPayload], Awaitable[None]]

MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1440


@dataclass(frozen=True, slots=True)
class PeriodicTask:
    """Периодическая задача. ``every_minutes`` делит 60 либо кратно 60 и делит 1440,
    чтобы интервал однозначно выражался и в APScheduler, и в arq cron."""

    name: str
    every_minutes: int

    def __post_init__(self) -> None:
        _check_task_name(self.name)
        if not is_valid_interval(self.every_minutes):
            raise ValueError(
                f"every_minutes={self.every_minutes!r}: интервал должен делить 60 (1, 2, 3, 4, 5, 6, 10, 12, 15, "
                "20, 30, 60) либо быть кратным 60 и делить 1440 (120, 180, 240, 360, 480, 720, 1440)"
            )


def is_valid_interval(every_minutes: int) -> bool:
    """Интервал выражается и в APScheduler (``interval``), и в arq (``cron`` с набором минут/часов)."""
    if isinstance(every_minutes, bool) or not isinstance(every_minutes, int) or every_minutes <= 0:
        return False
    if MINUTES_PER_HOUR % every_minutes == 0:
        return True
    return every_minutes % MINUTES_PER_HOUR == 0 and MINUTES_PER_DAY % every_minutes == 0


def _check_task_name(name: str) -> None:
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise ValueError("имя задачи должно быть непустой строкой без пробелов по краям")


class TaskRegistry:
    """Единый реестр задач; из него строятся и APScheduler (single), и arq WorkerSettings (scaled)."""

    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        self._periodic: dict[str, PeriodicTask] = {}

    def task(self, name: str) -> Callable[[TaskHandler], TaskHandler]:
        """Декоратор: зарегистрировать обработчик задачи. Повторное имя — ValueError."""
        _check_task_name(name)
        self._ensure_unique(name)

        def decorator(handler: TaskHandler) -> TaskHandler:
            self._ensure_unique(name)
            self._handlers[name] = handler
            return handler

        return decorator

    def periodic(self, name: str, *, every_minutes: int) -> Callable[[TaskHandler], TaskHandler]:
        """Декоратор: зарегистрировать обработчик и расписание. Обработчик получает пустой payload.

        Некорректный интервал или повторное имя — ValueError (ещё при объявлении, до запуска)."""
        periodic_task = PeriodicTask(name=name, every_minutes=every_minutes)
        self._ensure_unique(name)

        def decorator(handler: TaskHandler) -> TaskHandler:
            self._ensure_unique(name)
            self._handlers[name] = handler
            self._periodic[name] = periodic_task
            return handler

        return decorator

    def get(self, name: str) -> TaskHandler:
        """Обработчик по имени; неизвестное имя — KeyError."""
        try:
            return self._handlers[name]
        except KeyError:
            raise KeyError(f"задача {name!r} не зарегистрирована в TaskRegistry") from None

    def _ensure_unique(self, name: str) -> None:
        if name in self._handlers:
            raise ValueError(f"задача {name!r} уже зарегистрирована")

    @property
    def handlers(self) -> dict[str, TaskHandler]:
        return dict(self._handlers)

    @property
    def periodic_tasks(self) -> list[PeriodicTask]:
        return list(self._periodic.values())


def validate_task(registry: TaskRegistry, name: str, payload: TaskPayload | None) -> TaskPayload:
    """Общая проверка ``enqueue`` для всех реализаций: имя есть в реестре (иначе KeyError),
    payload — JSON-объект (иначе TypeError). ``None`` → пустой словарь."""
    registry.get(name)
    return ensure_json_object({} if payload is None else payload, what=f"payload задачи {name!r}")


def validate_delay(delay: timedelta | None) -> None:
    """Задержка не может быть отрицательной (ValueError)."""
    if delay is not None and delay < timedelta(0):
        raise ValueError("delay не может быть отрицательной")


class TaskScheduler(ABC):
    """Постановка фоновых задач в очередь / по таймеру.

    Реализации вызывают ``validate_task`` и ``validate_delay`` в начале ``enqueue`` — так
    проверки одинаковы в single и scaled."""

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
