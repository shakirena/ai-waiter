"""arq worker для режима scaled: ``arq app.core.scaled.worker.WorkerSettings``.

Функции и ``cron_jobs`` строятся из единого реестра ``app.tasks.registry`` — набор задач
совпадает с режимом single. Настройки берутся из тех же переменных окружения.

Импорт модуля ничего не выполняет: класс ``WorkerSettings`` собирается при первом обращении
к атрибуту (``__getattr__`` модуля, PEP 562) — именно так его получает CLI arq. Тогда же
проверяется конфигурация: без ``APP_MODE=scaled`` и ``REDIS_URL`` — ``ConfigError``
с понятным текстом. Для тестов и встраивания — ``build_worker_settings(settings, registry)``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.worker import Function, func

from app.core.config import AppMode, ConfigError, Settings
from app.core.log import configure_logging
from app.core.payload import ensure_json_object
from app.core.scaled.connection import deserialize_job, serialize_job
from app.core.scheduler import MINUTES_PER_HOUR, PeriodicTask, TaskHandler, TaskRegistry

logger = logging.getLogger(__name__)

# Префикс имён cron-заданий: в arq функции и cron-задания живут в одном словаре имён.
CRON_NAME_PREFIX = "cron:"

# Служебная функция: arq не запускается без единой функции, а в каркасе реестр пуст.
# В реестре её нет, поэтому поставить её через TaskScheduler нельзя.
NOOP_FUNCTION_NAME = "worker:noop"

# Обработчики идемпотентны (ADR-1), поэтому повтор после сбоя допустим.
MAX_TRIES = 3
JOB_TIMEOUT = timedelta(minutes=5)
# Результаты не храним: дедупликация по job_id действует, пока задача в очереди или выполняется.
KEEP_RESULT_SECONDS = 0
# Как часто worker обновляет ключ здоровья в Redis (TTL ключа — интервал + 1 с). По нему
# работает ``arq --check`` — healthcheck контейнера worker в deploy/docker-compose.yml.
# Значение arq по умолчанию (1 час) не позволило бы заметить зависший worker.
HEALTH_CHECK_INTERVAL = timedelta(seconds=60)


def _wrap_task(name: str, handler: TaskHandler) -> Any:
    async def run_task(ctx: dict[str, Any], payload: dict[str, Any] | None = None) -> None:
        await handler(ensure_json_object({} if payload is None else payload, what=f"payload задачи {name!r}"))

    run_task.__qualname__ = run_task.__name__ = f"task_{name}"
    return run_task


def _wrap_periodic(name: str, handler: TaskHandler) -> Any:
    async def run_periodic(ctx: dict[str, Any]) -> None:
        await handler({})

    run_periodic.__qualname__ = run_periodic.__name__ = f"periodic_{name}"
    return run_periodic


async def _noop(ctx: dict[str, Any]) -> None:
    """Ничего не делает; нужна только для запуска worker-а при пустом реестре."""


def build_functions(registry: TaskRegistry) -> list[Function]:
    """Обернуть обработчики реестра в arq-функции ``async def f(ctx, payload)`` с именем задачи."""
    functions = [func(_wrap_task(name, handler), name=name) for name, handler in registry.handlers.items()]
    functions.append(func(_noop, name=NOOP_FUNCTION_NAME))
    return functions


def cron_schedule(every_minutes: int) -> tuple[set[int] | None, set[int]]:
    """``every_minutes`` → ``(hour, minute)`` для ``arq.cron``.

    Делитель 60 → каждый час, минуты ``0, n, 2n, …``; кратное 60 (и делитель 1440) → минута 0,
    часы ``0, n/60, …``. Другие интервалы ``PeriodicTask`` не допускает."""
    if MINUTES_PER_HOUR % every_minutes == 0:
        return None, set(range(0, MINUTES_PER_HOUR, every_minutes))
    return set(range(0, 24, every_minutes // MINUTES_PER_HOUR)), {0}


def build_cron_jobs(registry: TaskRegistry) -> list[CronJob]:
    """``PeriodicTask.every_minutes`` → ``arq.cron(..., minute={...}, hour={...})``; ``unique=True``:
    при нескольких worker-ах задание в каждый момент выполняется один раз."""
    handlers = registry.handlers
    return [_cron_job(task, handlers[task.name]) for task in registry.periodic_tasks]


def _cron_job(task: PeriodicTask, handler: TaskHandler) -> CronJob:
    hour, minute = cron_schedule(task.every_minutes)
    return cron(
        _wrap_periodic(task.name, handler),
        name=CRON_NAME_PREFIX + task.name,
        hour=hour,
        minute=minute,
        unique=True,
        run_at_startup=False,
    )


async def on_startup(ctx: dict[str, Any]) -> None:
    """Логирование в том же формате, что у api. Движок БД добавляется в #7.
    Container со scheduler-ом worker-у не нужен: он только выполняет задачи."""
    settings: Settings = ctx["settings"]
    configure_logging(settings)
    logger.info("arq worker запущен", extra={"mode": str(settings.app_mode)})


async def on_shutdown(ctx: dict[str, Any]) -> None:
    logger.info("arq worker остановлен")


def build_worker_settings(settings: Settings, registry: TaskRegistry) -> type:
    """Собрать класс настроек arq. Все атрибуты — в ``__dict__`` класса (так их читает arq).

    Без ``APP_MODE=scaled`` или ``REDIS_URL`` — ``ConfigError``; строка подключения в текст
    ошибки и в логи не попадает."""
    if settings.app_mode is not AppMode.SCALED:
        raise ConfigError("Ошибка конфигурации: arq worker запускается только при APP_MODE=scaled")
    if settings.redis_url is None:
        raise ConfigError("Ошибка конфигурации: REDIS_URL обязателен для arq worker (APP_MODE=scaled)")
    try:
        redis_settings = RedisSettings.from_dsn(settings.redis_url.get_secret_value())
    except (RuntimeError, ValueError):
        # Текст исходной ошибки не выводим: он может содержать часть строки подключения.
        raise ConfigError("Ошибка конфигурации: REDIS_URL: некорректный адрес Redis (redis://, rediss://)") from None
    attrs: dict[str, Any] = {
        "__doc__": "Настройки arq worker-а, собранные из реестра задач и переменных окружения.",
        "functions": build_functions(registry),
        "cron_jobs": build_cron_jobs(registry),
        "redis_settings": redis_settings,
        "job_serializer": serialize_job,
        "job_deserializer": deserialize_job,
        "on_startup": on_startup,
        "on_shutdown": on_shutdown,
        "ctx": {"settings": settings},
        "max_tries": MAX_TRIES,
        "job_timeout": JOB_TIMEOUT,
        "keep_result": KEEP_RESULT_SECONDS,
        "health_check_interval": HEALTH_CHECK_INTERVAL,
    }
    return type("WorkerSettings", (), attrs)


def __getattr__(name: str) -> Any:
    """Ленивое ``WorkerSettings`` для ``arq app.core.scaled.worker.WorkerSettings``."""
    if name == "WorkerSettings":
        from app.core.config import get_settings
        from app.tasks import registry

        return build_worker_settings(get_settings(), registry)
    raise AttributeError(f"модуль {__name__!r} не содержит атрибута {name!r}")
