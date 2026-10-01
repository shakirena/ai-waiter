"""Шина событий (ADR-1): интерфейс и реализация для режима single.

Контракт одинаков для single и scaled:
- доставка at-most-once, без хранения; источник истины — БД;
- канал всегда содержит tenant: ``tenant_channel(tenant_id, topic)``;
- payload JSON-сериализуем (в Redis уходит ``Event.model_dump_json()``);
- медленный подписчик не блокирует издателя: очередь ограничена, при переполнении
  отбрасывается самое старое событие (с предупреждением в лог).

Использование::

    await bus.publish(tenant_channel(tenant_id, "staff"), Event(type="order.submitted", ...))

    async with bus.subscribe(tenant_channel(tenant_id, "staff")) as events:
        async for event in events:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    """Уведомление о доменном изменении. Не несёт состояния целиком — клиент перечитывает его по REST."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(min_length=1, max_length=100)
    tenant_id: int
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def tenant_channel(tenant_id: int, topic: str) -> str:
    """Имя канала с изоляцией по заведению: ``tenant:{tenant_id}:{topic}``."""
    raise NotImplementedError


class EventBus(ABC):
    """Публикация/подписка на события внутри tenant-каналов."""

    async def start(self) -> None:  # noqa: B027 — no-op по умолчанию
        """Подготовить ресурсы (соединения). Вызывается из lifespan."""

    async def stop(self) -> None:  # noqa: B027 — no-op по умолчанию
        """Закрыть подписки и соединения. Вызывается из lifespan."""

    @abstractmethod
    async def publish(self, channel: str, event: Event) -> None:
        """Отправить событие всем текущим подписчикам канала. Не блокируется на медленных подписчиках."""

    @abstractmethod
    def subscribe(self, channel: str) -> AbstractAsyncContextManager[AsyncIterator[Event]]:
        """Подписка на канал; при выходе из контекста подписка снимается."""

    async def ping(self) -> bool:
        """Проверка доступности для /health/ready (in-memory — всегда True, Redis — PING)."""
        return True
