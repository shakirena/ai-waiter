"""RateLimiter на Redis (режим scaled). Заготовка; реализуется в #26/#36."""

from __future__ import annotations

from datetime import timedelta

from app.core.ratelimit import RateLimiter, RateLimitResult


class RedisRateLimiter(RateLimiter):
    """Фиксированное окно: атомарно ``INCR key`` + ``EXPIRE key window NX`` (pipeline/Lua), ``TTL`` → retry_after.
    Ключи в Redis с префиксом ``rl:``."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        raise NotImplementedError

    async def reset(self, key: str) -> None:
        raise NotImplementedError

    async def ping(self) -> bool:
        raise NotImplementedError
