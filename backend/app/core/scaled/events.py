"""EventBus на Redis pub/sub (режим scaled). Заготовка; реализуется в #20/#36."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager

from app.core.events import Event, EventBus


class RedisEventBus(EventBus):
    """Публикация: ``PUBLISH channel event.model_dump_json()``.
    Подписка: отдельный ``PubSub`` на подписчика, очередь ограничена как в InMemoryEventBus."""

    def __init__(self, redis_url: str, *, queue_size: int = 100) -> None:
        self._redis_url = redis_url
        self._queue_size = queue_size

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def publish(self, channel: str, event: Event) -> None:
        raise NotImplementedError

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[AsyncIterator[Event]]:
        raise NotImplementedError

    async def ping(self) -> bool:
        raise NotImplementedError
