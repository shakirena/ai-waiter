"""arq worker для режима scaled: ``arq app.core.scaled.worker.WorkerSettings``.

Функции и ``cron_jobs`` строятся из единого реестра ``app.tasks.registry`` — набор задач
совпадает с режимом single. Настройки берутся из тех же переменных окружения.
"""

from __future__ import annotations

from typing import Any

from app.core.scheduler import TaskRegistry


def build_functions(registry: TaskRegistry) -> list[Any]:
    """Обернуть обработчики реестра в arq-функции ``async def f(ctx, payload)`` с именем задачи."""
    raise NotImplementedError


def build_cron_jobs(registry: TaskRegistry) -> list[Any]:
    """``PeriodicTask.every_minutes`` → ``arq.cron(..., minute={...}, hour={...})``; ``unique=True``."""
    raise NotImplementedError


async def on_startup(ctx: dict[str, Any]) -> None:
    """Логирование, движок БД, Container без scheduler-а (worker сам не ставит задачи в свою очередь напрямую)."""
    raise NotImplementedError


async def on_shutdown(ctx: dict[str, Any]) -> None:
    raise NotImplementedError


class WorkerSettings:
    """Заполняется при реализации: functions, cron_jobs, redis_settings (из REDIS_URL),
    on_startup/on_shutdown, max_tries, job_timeout."""

    # functions = build_functions(registry)
    # cron_jobs = build_cron_jobs(registry)
    # redis_settings = RedisSettings.from_dsn(get_settings().redis_url.get_secret_value())
    on_startup = on_startup
    on_shutdown = on_shutdown
