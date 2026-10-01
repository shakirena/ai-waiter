"""RateLimiter на Redis (режим scaled). Контракт — ``app/core/ratelimit.py``.

Фиксированное окно: в одной транзакции MULTI/EXEC выполняются ``INCR key``,
``PEXPIRE key window NX`` и ``PTTL key``. Срок жизни ставится только первым обращением
окна (NX, Redis 7+), поэтому окно не продлевается последующими запросами. Счётчик живёт
в Redis и общий для всех процессов api. Ключи в Redis — с префиксом ``rl:``.
"""

from __future__ import annotations

import math
from datetime import timedelta

from redis.asyncio import Redis

from app.core.ratelimit import RateLimiter, RateLimitResult, validate_hit_args
from app.core.scaled.connection import RedisFactory, redis_from_url

KEY_PREFIX = "rl:"


class RedisRateLimiter(RateLimiter):
    """Общий для всех экземпляров счётчик обращений по ключу."""

    def __init__(self, redis_url: str, *, client_factory: RedisFactory = redis_from_url) -> None:
        self._redis_url = redis_url
        self._client_factory = client_factory
        self._client: Redis | None = None

    async def start(self) -> None:
        """Создать клиента. Соединение откроется при первой команде — старт не зависит от Redis."""
        if self._client is None:
            self._client = self._client_factory(self._redis_url)

    async def stop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        validate_hit_args(limit, window)
        client = self._require_client()
        window_ms = max(1, math.ceil(window / timedelta(milliseconds=1)))
        redis_key = KEY_PREFIX + key
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.pexpire(redis_key, window_ms, nx=True)
            pipe.pttl(redis_key)
            count, _, ttl_ms = await pipe.execute()
        allowed = count <= limit
        retry_after = 0.0 if allowed else (ttl_ms if ttl_ms > 0 else window_ms) / 1000
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - count),
            retry_after=retry_after,
        )

    async def reset(self, key: str) -> None:
        await self._require_client().delete(KEY_PREFIX + key)

    async def ping(self) -> bool:
        if self._client is None:
            return False
        return bool(await self._client.ping())

    def _require_client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("RedisRateLimiter не запущен: сначала вызовите start()")
        return self._client
