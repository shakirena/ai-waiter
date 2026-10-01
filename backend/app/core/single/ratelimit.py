"""RateLimiter в памяти процесса (режим single). Контракт — app/core/ratelimit.py."""

from __future__ import annotations

from datetime import timedelta

from app.core.ratelimit import RateLimiter, RateLimitResult


class InMemoryRateLimiter(RateLimiter):
    """Режим single. Память ограничена ``max_keys``: при превышении удаляются истёкшие окна,
    затем самые старые ключи."""

    def __init__(self, *, max_keys: int = 100_000) -> None:
        self._max_keys = max_keys

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        raise NotImplementedError

    async def reset(self, key: str) -> None:
        raise NotImplementedError
