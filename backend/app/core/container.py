"""Сборка зависимостей по режиму (ADR-1). Единственное место, где выбирается реализация
EventBus/TaskScheduler/RateLimiter по ``settings.app_mode``.

Пакеты реализаций ``app.core.single`` и ``app.core.scaled`` импортируются лениво, только
в своей ветке: в single не импортируются redis/arq, в scaled — apscheduler.
``Database`` (движок PostgreSQL и фабрика сессий, ADR-7.9) одинаков в обоих режимах.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import AppMode, ConfigError, Settings
from app.core.events import EventBus
from app.core.ratelimit import RateLimiter
from app.core.scheduler import TaskRegistry, TaskScheduler
from app.db.session import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    database: Database
    event_bus: EventBus
    scheduler: TaskScheduler
    rate_limiter: RateLimiter


def build_container(settings: Settings, registry: TaskRegistry) -> Container:
    """single → InMemoryEventBus, InProcessTaskScheduler(registry), InMemoryRateLimiter;
    scaled → RedisEventBus, ArqTaskScheduler(registry), RedisRateLimiter.
    ``Database(settings)`` — в обоих режимах.
    Импорт пакета реализаций — внутри ветки ``match settings.app_mode``.
    Ничего не подключает к сети — только создаёт объекты.

    Неизвестный режим или scaled без REDIS_URL → ``ConfigError``: приложение не стартует."""
    match settings.app_mode:
        case AppMode.SINGLE:
            from app.core.single.events import InMemoryEventBus
            from app.core.single.ratelimit import InMemoryRateLimiter
            from app.core.single.scheduler import InProcessTaskScheduler

            return Container(
                settings=settings,
                database=Database(settings),
                event_bus=InMemoryEventBus(),
                scheduler=InProcessTaskScheduler(registry),
                rate_limiter=InMemoryRateLimiter(),
            )
        case AppMode.SCALED:
            if settings.redis_url is None:
                raise ConfigError("Ошибка конфигурации: REDIS_URL обязателен при APP_MODE=scaled")
            redis_url = settings.redis_url.get_secret_value()

            from app.core.scaled.events import RedisEventBus
            from app.core.scaled.ratelimit import RedisRateLimiter
            from app.core.scaled.scheduler import ArqTaskScheduler

            return Container(
                settings=settings,
                database=Database(settings),
                event_bus=RedisEventBus(redis_url),
                scheduler=ArqTaskScheduler(redis_url, registry),
                rate_limiter=RedisRateLimiter(redis_url),
            )
        case _:
            raise ConfigError(
                f"Ошибка конфигурации: APP_MODE: неизвестный режим {str(settings.app_mode)!r}; "
                f"допустимо: {', '.join(mode.value for mode in AppMode)}"
            )


async def start_container(container: Container) -> None:
    """Порядок: database → event_bus → rate_limiter → scheduler.

    Ошибка запуска компонента (например, Redis недоступен при старте в scaled) логируется и
    не роняет процесс: /health остаётся доступным, а /health/ready сообщает о неготовности,
    пока зависимость не восстановится. Остальные компоненты всё равно запускаются."""
    for name, component in _components(container):
        try:
            await component.start()
        except Exception:
            logger.exception("Компонент не запущен; приложение продолжает работу", extra={"component": name})


async def stop_container(container: Container) -> None:
    """Обратный порядок: scheduler → rate_limiter → event_bus → database (задачи планировщика
    могут писать в БД до своей остановки).
    Ошибка остановки одного компонента логируется и не мешает остановить остальные."""
    for name, component in reversed(_components(container)):
        try:
            await component.stop()
        except Exception:
            logger.exception("Ошибка при остановке компонента", extra={"component": name})


def _components(container: Container) -> list[tuple[str, Database | EventBus | RateLimiter | TaskScheduler]]:
    """Компоненты в порядке запуска."""
    return [
        ("database", container.database),
        ("event_bus", container.event_bus),
        ("rate_limiter", container.rate_limiter),
        ("scheduler", container.scheduler),
    ]
