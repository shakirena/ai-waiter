"""Rate-limit (ADR-1): интерфейс. Реализации — app/core/single/ratelimit.py, app/core/scaled/ratelimit.py.

Алгоритм в обоих режимах — фиксированное окно (Redis: INCR + EXPIRE атомарно;
память: словарь с ленивой очисткой). Ключ собирается ``rate_key``; для лимитов
по столу в ключ входит tenant_id. Применение к эндпоинтам — #22, #26.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta

KEY_SEPARATOR = ":"


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: float  # секунды до конца окна; 0.0, если allowed


def rate_key(scope: str, *parts: str | int) -> str:
    """Ключ лимита: ``rate_key("guest_msg", "table", tenant_id, table_id)`` → ``"guest_msg:table:1:42"``.

    Части не должны содержать ``:`` (ValueError) — иначе возможны коллизии ключей.
    Пустые части и пробельные символы тоже запрещены; ``bool`` — не число (ValueError).
    """
    pieces = [scope, *parts]
    for piece in pieces:
        if isinstance(piece, bool) or not isinstance(piece, str | int):
            raise ValueError(f"часть ключа лимита должна быть строкой или целым числом: {piece!r}")
        text = str(piece)
        if not text or KEY_SEPARATOR in text or any(ch.isspace() for ch in text):
            raise ValueError(f"часть ключа лимита пуста или содержит {KEY_SEPARATOR!r}/пробел: {piece!r}")
    return KEY_SEPARATOR.join(str(piece) for piece in pieces)


def validate_hit_args(limit: int, window: timedelta) -> None:
    """Общая проверка аргументов ``hit`` для всех реализаций: ``limit >= 1``, ``window > 0`` (ValueError)."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit должен быть целым числом не меньше 1")
    if window <= timedelta(0):
        raise ValueError("window должно быть больше нуля")


class RateLimiter(ABC):
    """Счётчик обращений по ключу. Реализации вызывают ``validate_hit_args`` в начале ``hit``."""

    async def start(self) -> None:  # noqa: B027 — no-op по умолчанию
        """Подготовить ресурсы."""

    async def stop(self) -> None:  # noqa: B027 — no-op по умолчанию
        """Освободить ресурсы."""

    @abstractmethod
    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        """Засчитать одно обращение и вернуть, разрешено ли оно. ``limit >= 1``, ``window > 0``."""

    @abstractmethod
    async def reset(self, key: str) -> None:
        """Сбросить счётчик ключа (например, после ручной разблокировки админом)."""

    async def ping(self) -> bool:
        """Проверка доступности для /health/ready."""
        return True
