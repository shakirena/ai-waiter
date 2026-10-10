"""RateLimiter в памяти процесса (режим single). Контракт — app/core/ratelimit.py.

Фиксированное окно, как в scaled (``INCR`` + ``EXPIRE``): окно ключа начинается с первого
обращения и длится ``window``; каждое обращение увеличивает счётчик, в том числе отклонённое.
Длительность окна задаётся первым обращением и не меняется до его истечения (как TTL в Redis).
Истёкшие окна удаляются лениво: при следующем обращении к ключу и при переполнении словаря.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from app.core.ratelimit import RateLimiter, RateLimitResult, validate_hit_args

DEFAULT_MAX_KEYS = 100_000
# Полный проход по словарю в поисках истёкших окон — не чаще раза в секунду, чтобы поток новых
# ключей при заполненном словаре не превращал каждый ``hit`` в O(n).
PURGE_MIN_INTERVAL = 1.0


@dataclass(slots=True)
class _Window:
    expires_at: float
    count: int


class InMemoryRateLimiter(RateLimiter):
    """Режим single. Память ограничена ``max_keys``: при превышении удаляются истёкшие окна,
    затем самые старые ключи (для вытесненного ключа окно начинается заново).

    ``clock`` — монотонные часы в секундах; подменяется в тестах."""

    def __init__(self, *, max_keys: int = DEFAULT_MAX_KEYS, clock: Callable[[], float] = time.monotonic) -> None:
        if isinstance(max_keys, bool) or not isinstance(max_keys, int) or max_keys < 1:
            raise ValueError("max_keys должен быть целым числом не меньше 1")
        self._max_keys = max_keys
        self._clock = clock
        self._windows: OrderedDict[str, _Window] = OrderedDict()
        self._last_purge: float | None = None

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        validate_hit_args(limit, window)
        if not isinstance(key, str) or not key:
            raise ValueError("ключ лимита должен быть непустой строкой")

        now = self._clock()
        current = self._windows.get(key)
        if current is None or now >= current.expires_at:
            if current is None:
                self._make_room(now)
            current = _Window(expires_at=now + window.total_seconds(), count=0)
            self._windows[key] = current
            # Порядок словаря — порядок начала окон: в начале самые старые.
            self._windows.move_to_end(key)

        current.count += 1
        if current.count <= limit:
            return RateLimitResult(allowed=True, limit=limit, remaining=limit - current.count, retry_after=0.0)
        return RateLimitResult(allowed=False, limit=limit, remaining=0, retry_after=max(current.expires_at - now, 0.0))

    async def reset(self, key: str) -> None:
        self._windows.pop(key, None)

    def _make_room(self, now: float) -> None:
        """Освободить место под новый ключ: сначала истёкшие окна, затем самые старые ключи."""
        if len(self._windows) < self._max_keys:
            return
        if self._last_purge is None or now - self._last_purge >= PURGE_MIN_INTERVAL:
            self._last_purge = now
            for expired in [k for k, w in self._windows.items() if now >= w.expires_at]:
                del self._windows[expired]
        while len(self._windows) >= self._max_keys:
            self._windows.popitem(last=False)
