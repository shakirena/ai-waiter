"""EventBus в памяти процесса (режим single). Контракт — app/core/events.py.

Каждая подписка — собственный ограниченный буфер. ``publish`` никогда не ждёт подписчиков:
при переполнении буфера отбрасывается самое старое событие и пишется предупреждение в лог.
Доставка at-most-once: событие получают только подписчики, активные в момент публикации.

Подписчик получает копию события, прошедшую сериализацию в JSON и обратно, — ровно то, что
пришло бы через Redis в режиме scaled. Так single не скрывает ошибок сериализации и не даёт
подписчикам делить один изменяемый ``payload``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from app.core.events import Event, EventBus

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 100
# Предупреждение пишется при первом отброшенном событии подписки и далее каждые N отброшенных,
# чтобы зависший подписчик не засыпал лог одинаковыми строками.
DROP_WARNING_EVERY = 100


class _Subscription:
    """Ограниченный буфер одной подписки и асинхронный итератор по нему."""

    def __init__(self, channel: str, maxsize: int) -> None:
        self.channel = channel
        self._maxsize = maxsize
        self._buffer: deque[Event] = deque()
        self._wakeup = asyncio.Event()
        self._closed = False
        self.dropped = 0

    def push(self, event: Event) -> None:
        """Положить событие в буфер, не ожидая. Переполнение — отбросить самое старое."""
        if self._closed:
            return
        if len(self._buffer) >= self._maxsize:
            self._buffer.popleft()
            self.dropped += 1
            if self.dropped % DROP_WARNING_EVERY == 1:
                logger.warning(
                    "Подписчик не успевает читать события: самое старое событие отброшено",
                    extra={"channel": self.channel, "dropped_total": self.dropped, "queue_size": self._maxsize},
                )
        self._buffer.append(event)
        self._wakeup.set()

    def close(self) -> None:
        """Закрыть подписку: итерация завершается, недоставленные события отбрасываются."""
        self._closed = True
        self._buffer.clear()
        self._wakeup.set()

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        while True:
            if self._closed:
                raise StopAsyncIteration
            if self._buffer:
                return self._buffer.popleft()
            self._wakeup.clear()
            await self._wakeup.wait()


class InMemoryEventBus(EventBus):
    """Шина в памяти процесса (режим single, один процесс uvicorn)."""

    def __init__(self, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        if isinstance(queue_size, bool) or not isinstance(queue_size, int) or queue_size < 1:
            raise ValueError("queue_size должен быть целым числом не меньше 1")
        self._queue_size = queue_size
        self._subscribers: dict[str, set[_Subscription]] = {}
        self._stopped = False

    async def start(self) -> None:
        """Разрешить подписки (в том числе после ``stop``)."""
        self._stopped = False

    async def stop(self) -> None:
        """Закрыть все подписки: их итераторы завершаются, новые подписки запрещены до ``start``."""
        self._stopped = True
        subscriptions = [sub for subs in self._subscribers.values() for sub in subs]
        self._subscribers.clear()
        for sub in subscriptions:
            sub.close()

    async def publish(self, channel: str, event: Event) -> None:
        """Разослать событие текущим подписчикам канала. Не ждёт подписчиков; после ``stop`` — no-op."""
        if not isinstance(event, Event):
            raise TypeError(f"ожидался Event, получен {type(event).__name__}")
        subscriptions = self._subscribers.get(channel)
        if not subscriptions:
            return
        raw = event.model_dump_json()
        for sub in list(subscriptions):
            sub.push(Event.model_validate_json(raw))

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[AsyncIterator[Event]]:
        """Подписка на канал; при выходе из контекста подписка снимается.

        Подписка регистрируется при входе в контекст: события, опубликованные раньше, не приходят.
        После ``stop`` вход в контекст — RuntimeError."""
        return self._subscription(channel)

    @asynccontextmanager
    async def _subscription(self, channel: str) -> AsyncIterator[AsyncIterator[Event]]:
        if self._stopped:
            raise RuntimeError("шина событий остановлена: подписка невозможна")
        sub = _Subscription(channel, self._queue_size)
        self._subscribers.setdefault(channel, set()).add(sub)
        try:
            yield sub
        finally:
            sub.close()
            subs = self._subscribers.get(channel)
            if subs is not None:
                subs.discard(sub)
                if not subs:
                    del self._subscribers[channel]

    async def ping(self) -> bool:
        """True, пока шина не остановлена."""
        return not self._stopped
