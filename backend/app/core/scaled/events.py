"""EventBus на Redis pub/sub (режим scaled). Контракт — ``app/core/events.py``.

- Публикация: ``PUBLISH channel event.model_dump_json()``; канал собирается ``tenant_channel()``.
- Подписка: отдельный ``PubSub`` (своё соединение) на каждого подписчика и фоновая задача,
  перекладывающая сообщения в ограниченную очередь. При переполнении очереди отбрасывается
  самое старое событие с предупреждением в лог — медленный подписчик не тормозит остальных.
- Доставка at-most-once, без хранения: если соединение с Redis оборвалось, итератор подписки
  завершается, клиент переподписывается и перечитывает состояние через REST (источник истины — БД).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from app.core.events import Event, EventBus
from app.core.scaled.connection import RedisFactory, redis_from_url

logger = logging.getLogger(__name__)

# Сколько ждать подтверждения SUBSCRIBE от Redis: после выхода из ``subscribe()`` подписка
# уже действует, и событие, опубликованное следом, не теряется.
SUBSCRIBE_TIMEOUT_SECONDS = 5.0

_CONNECTION_ERRORS = (RedisError, OSError)


class _Subscription:
    """Одна подписка: ограниченная очередь событий и признак завершения (``None`` в очереди)."""

    def __init__(self, channel: str, pubsub: PubSub, queue_size: int) -> None:
        self.channel = channel
        self.pubsub = pubsub
        self.queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=queue_size)
        self.reader: asyncio.Task[None] | None = None
        self.closed = False

    def put(self, event: Event) -> None:
        if self.queue.full():
            self.queue.get_nowait()
            logger.warning(
                "Очередь подписчика переполнена: самое старое событие отброшено",
                extra={"channel": self.channel},
            )
        self.queue.put_nowait(event)

    def finish(self) -> None:
        """Поставить признак конца; при полной очереди место освобождается за счёт старого события."""
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(None)

    async def events(self) -> AsyncIterator[Event]:
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item


class RedisEventBus(EventBus):
    """Шина событий между процессами api через Redis pub/sub."""

    def __init__(
        self,
        redis_url: str,
        *,
        queue_size: int = 100,
        client_factory: RedisFactory = redis_from_url,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size должен быть не меньше 1")
        self._redis_url = redis_url
        self._queue_size = queue_size
        self._client_factory = client_factory
        self._client: Redis | None = None
        self._subscriptions: set[_Subscription] = set()

    async def start(self) -> None:
        """Создать клиента. Соединение откроется при первой команде — старт не зависит от Redis."""
        if self._client is None:
            self._client = self._client_factory(self._redis_url)

    async def stop(self) -> None:
        """Завершить все подписки (их итераторы заканчиваются) и закрыть соединения."""
        for subscription in list(self._subscriptions):
            await self._close_subscription(subscription)
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.aclose()
            except _CONNECTION_ERRORS:
                logger.warning("Ошибка при закрытии соединения с Redis (шина событий)", exc_info=True)

    async def publish(self, channel: str, event: Event) -> None:
        await self._require_client().publish(channel, event.model_dump_json())

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[AsyncIterator[Event]]:
        return self._subscribe(channel)

    async def ping(self) -> bool:
        if self._client is None:
            return False
        return bool(await self._client.ping())

    def _require_client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("RedisEventBus не запущен: сначала вызовите start()")
        return self._client

    @asynccontextmanager
    async def _subscribe(self, channel: str) -> AsyncIterator[AsyncIterator[Event]]:
        pubsub = self._require_client().pubsub()
        subscription = _Subscription(channel, pubsub, self._queue_size)
        try:
            await pubsub.subscribe(channel)
            await _wait_subscribed(pubsub)
            subscription.reader = asyncio.create_task(self._read(subscription))
            self._subscriptions.add(subscription)
            yield subscription.events()
        finally:
            await self._close_subscription(subscription)

    async def _read(self, subscription: _Subscription) -> None:
        """Перекладывать сообщения канала в очередь подписчика, пока подписка жива."""
        try:
            async for message in subscription.pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    event = Event.model_validate_json(message["data"])
                except ValidationError:
                    logger.warning("Отброшено некорректное событие", extra={"channel": subscription.channel})
                    continue
                subscription.put(event)
        except _CONNECTION_ERRORS:
            logger.warning(
                "Подписка прервана: потеряно соединение с Redis",
                extra={"channel": subscription.channel},
                exc_info=True,
            )
        finally:
            subscription.finish()

    async def _close_subscription(self, subscription: _Subscription) -> None:
        """Снять подписку. Идемпотентно: вызывается и при выходе из контекста, и из ``stop()``."""
        self._subscriptions.discard(subscription)
        if subscription.closed:
            return
        subscription.closed = True
        reader = subscription.reader
        if reader is not None and not reader.done():
            reader.cancel()
            # asyncio.wait не пробрасывает CancelledError задачи-читателя, но отмену самого
            # вызывающего кода не глотает.
            await asyncio.wait([reader])
        if reader is None:
            subscription.finish()
        try:
            # Явный UNSUBSCRIBE: не полагаемся на то, что сервер снимет подписку при разрыве соединения.
            await subscription.pubsub.unsubscribe()
        except _CONNECTION_ERRORS:
            logger.warning(
                "Ошибка при закрытии подписки Redis",
                extra={"channel": subscription.channel},
                exc_info=True,
            )
        finally:
            # aclose() только сбрасывает соединение подписки и возвращает его в пул.
            await subscription.pubsub.aclose()


async def _wait_subscribed(pubsub: PubSub) -> None:
    """Дождаться подтверждения SUBSCRIBE; без него — ``TimeoutError``.

    Срок проверяется явно: ``get_message`` может вернуть ``None`` сразу, не уступив event loop."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SUBSCRIBE_TIMEOUT_SECONDS
    while (remaining := deadline - loop.time()) > 0:
        message = await asyncio.wait_for(pubsub.get_message(timeout=remaining), remaining)
        if message is not None and message.get("type") == "subscribe":
            return
        await asyncio.sleep(0)
    raise TimeoutError("Redis не подтвердил подписку на канал")
