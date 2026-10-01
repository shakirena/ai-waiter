"""Сборка зависимостей по режиму (ADR-1). Единственное место, где выбирается реализация
EventBus/TaskScheduler/RateLimiter по ``settings.app_mode``.

Пакеты реализаций ``app.core.single`` и ``app.core.scaled`` импортируются лениво, только
в своей ветке: в single не импортируются redis/arq, в scaled — apscheduler.
Движок БД и фабрика сессий добавляются в Container в #7.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.events import EventBus
from app.core.ratelimit import RateLimiter
from app.core.scheduler import TaskRegistry, TaskScheduler


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    event_bus: EventBus
    scheduler: TaskScheduler
    rate_limiter: RateLimiter


def build_container(settings: Settings, registry: TaskRegistry) -> Container:
    """single → InMemoryEventBus, InProcessTaskScheduler(registry), InMemoryRateLimiter;
    scaled → RedisEventBus, ArqTaskScheduler(registry), RedisRateLimiter.
    Импорт пакета реализаций — внутри ветки ``match settings.app_mode``.
    Ничего не подключает к сети — только создаёт объекты."""
    raise NotImplementedError


async def start_container(container: Container) -> None:
    """Порядок: event_bus → rate_limiter → scheduler."""
    raise NotImplementedError


async def stop_container(container: Container) -> None:
    """Обратный порядок: scheduler → rate_limiter → event_bus.
    Ошибка остановки одного компонента логируется и не мешает остановить остальные."""
    raise NotImplementedError
