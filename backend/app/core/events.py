"""Шина событий (ADR-1): интерфейс и общие типы. Реализации — ``app/core/single/events.py``,
``app/core/scaled/events.py``.

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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.payload import ensure_json_object


class Event(BaseModel):
    """Уведомление о доменном изменении. Не несёт состояния целиком — клиент перечитывает его по REST.

    ``payload`` проверяется на JSON-сериализуемость при создании (одинаково в single и scaled),
    ``occurred_at`` — только aware-datetime (timestamptz).
    """

    model_config = ConfigDict(frozen=True)

    type: str = Field(min_length=1, max_length=100)
    tenant_id: int = Field(gt=0, strict=True)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("payload")
    @classmethod
    def _payload_is_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            return ensure_json_object(value, what="payload события")
        except TypeError as exc:
            raise ValueError(str(exc)) from None

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at должен содержать часовой пояс (aware-datetime)")
        return value


def tenant_channel(tenant_id: int, topic: str) -> str:
    """Имя канала с изоляцией по заведению: ``tenant:{tenant_id}:{topic}``.

    ``tenant_id`` — положительное целое (не ``bool``), ``topic`` — непустая строка без пробельных
    символов; иначе ``ValueError``. Канал без tenant собрать нельзя — это и есть изоляция по заведению.
    """
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
        raise ValueError("tenant_id должен быть положительным целым числом")
    if not isinstance(topic, str) or not topic or any(ch.isspace() for ch in topic):
        raise ValueError("topic должен быть непустой строкой без пробельных символов")
    return f"tenant:{tenant_id}:{topic}"


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
