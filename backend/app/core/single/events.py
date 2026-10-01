"""EventBus в памяти процесса (режим single). Контракт — app/core/events.py."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager

from app.core.events import Event, EventBus


class InMemoryEventBus(EventBus):
    """Шина в памяти процесса (режим single, один процесс uvicorn)."""

    def __init__(self, *, queue_size: int = 100) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = {}

    async def stop(self) -> None:
        raise NotImplementedError

    async def publish(self, channel: str, event: Event) -> None:
        raise NotImplementedError

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[AsyncIterator[Event]]:
        raise NotImplementedError
