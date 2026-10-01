"""RedisRateLimiter на fakeredis (#40, spec AC-4): фиксированное окно, общий счётчик для
нескольких экземпляров, retry_after из TTL, проверка аргументов, ping."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fakeredis import FakeServer
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.ratelimit import rate_key
from app.core.scaled.ratelimit import KEY_PREFIX, RedisRateLimiter
from tests.fake_redis import redis_factory

REDIS_URL = "redis://redis:6379/0"
KEY = rate_key("guest_msg", "table", 1, 42)
WINDOW = timedelta(seconds=60)


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
async def limiter(server: FakeServer) -> AsyncIterator[RedisRateLimiter]:
    instance = RedisRateLimiter(REDIS_URL, client_factory=redis_factory(server))
    await instance.start()
    yield instance
    await instance.stop()


async def test_allows_up_to_limit_then_blocks(limiter: RedisRateLimiter) -> None:
    results = [await limiter.hit(KEY, limit=3, window=WINDOW) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert [r.remaining for r in results] == [2, 1, 0, 0]
    assert all(r.limit == 3 for r in results)
    assert [r.retry_after for r in results[:3]] == [0.0, 0.0, 0.0]
    assert 59.0 < results[3].retry_after <= 60.0


async def test_counter_is_shared_between_instances(server: FakeServer) -> None:
    first = RedisRateLimiter(REDIS_URL, client_factory=redis_factory(server))
    second = RedisRateLimiter(REDIS_URL, client_factory=redis_factory(server))
    await first.start()
    await second.start()
    assert (await first.hit(KEY, limit=2, window=WINDOW)).allowed
    assert (await second.hit(KEY, limit=2, window=WINDOW)).allowed
    blocked = await first.hit(KEY, limit=2, window=WINDOW)
    assert not blocked.allowed
    assert not (await second.hit(KEY, limit=2, window=WINDOW)).allowed
    await first.stop()
    await second.stop()


async def test_keys_are_independent_and_prefixed(limiter: RedisRateLimiter, server: FakeServer) -> None:
    other = rate_key("guest_msg", "table", 2, 42)  # другой tenant — другой счётчик
    assert not (
        await limiter.hit(KEY, limit=1, window=WINDOW) and await limiter.hit(KEY, limit=1, window=WINDOW)
    ).allowed
    assert (await limiter.hit(other, limit=1, window=WINDOW)).allowed
    raw = redis_factory(server)(REDIS_URL)
    assert sorted(await raw.keys("*")) == sorted([(KEY_PREFIX + KEY).encode(), (KEY_PREFIX + other).encode()])
    await raw.aclose()


async def test_window_is_fixed_not_sliding(limiter: RedisRateLimiter, server: FakeServer) -> None:
    raw = redis_factory(server)(REDIS_URL)
    await limiter.hit(KEY, limit=5, window=WINDOW)
    await raw.pexpire(KEY_PREFIX + KEY, 1500)  # окно почти истекло
    await limiter.hit(KEY, limit=5, window=WINDOW)
    # Последующее обращение не продлевает окно (EXPIRE ... NX).
    assert 0 < await raw.pttl(KEY_PREFIX + KEY) <= 1500
    await raw.aclose()


async def test_new_window_after_expiry(limiter: RedisRateLimiter, server: FakeServer) -> None:
    raw = redis_factory(server)(REDIS_URL)
    await limiter.hit(KEY, limit=1, window=WINDOW)
    assert not (await limiter.hit(KEY, limit=1, window=WINDOW)).allowed
    await raw.delete(KEY_PREFIX + KEY)  # эквивалент истечения TTL
    assert (await limiter.hit(KEY, limit=1, window=WINDOW)).allowed
    await raw.aclose()


def _mock_client(execute_result: list[int]) -> tuple[MagicMock, MagicMock]:
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=execute_result)
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    client = MagicMock()
    client.pipeline.return_value = pipe
    return client, pipe


async def test_atomic_transaction_and_ms_rounding() -> None:
    client, pipe = _mock_client([1, 1, 1])
    limiter = RedisRateLimiter(REDIS_URL, client_factory=lambda url: client)
    await limiter.start()
    await limiter.hit(KEY, limit=1, window=timedelta(microseconds=10))
    client.pipeline.assert_called_once_with(transaction=True)  # MULTI/EXEC
    pipe.incr.assert_called_once_with(KEY_PREFIX + KEY)
    pipe.pexpire.assert_called_once_with(KEY_PREFIX + KEY, 1, nx=True)  # окно < 1 мс → 1 мс
    pipe.pttl.assert_called_once_with(KEY_PREFIX + KEY)


async def test_retry_after_falls_back_to_window_without_ttl() -> None:
    client, _ = _mock_client([5, 0, -2])
    limiter = RedisRateLimiter(REDIS_URL, client_factory=lambda url: client)
    await limiter.start()
    result = await limiter.hit(KEY, limit=1, window=timedelta(seconds=2))
    assert (result.allowed, result.remaining, result.retry_after) == (False, 0, 2.0)


async def test_reset_clears_counter(limiter: RedisRateLimiter) -> None:
    await limiter.hit(KEY, limit=1, window=WINDOW)
    await limiter.reset(KEY)
    assert (await limiter.hit(KEY, limit=1, window=WINDOW)).allowed
    await limiter.reset("missing")  # сброс несуществующего ключа — не ошибка


@pytest.mark.parametrize(
    ("limit", "window"),
    [(0, WINDOW), (-1, WINDOW), (True, WINDOW), (1.5, WINDOW), (1, timedelta(0)), (1, timedelta(seconds=-1))],
)
async def test_invalid_args_rejected_before_redis(limit: Any, window: timedelta) -> None:
    client = MagicMock()
    limiter = RedisRateLimiter(REDIS_URL, client_factory=lambda url: client)
    await limiter.start()
    with pytest.raises(ValueError):
        await limiter.hit(KEY, limit=limit, window=window)
    client.pipeline.assert_not_called()


async def test_not_started_raises() -> None:
    limiter = RedisRateLimiter(REDIS_URL)
    with pytest.raises(RuntimeError, match="не запущен"):
        await limiter.hit(KEY, limit=1, window=WINDOW)
    with pytest.raises(RuntimeError, match="не запущен"):
        await limiter.reset(KEY)


async def test_ping_and_lifecycle(server: FakeServer) -> None:
    limiter = RedisRateLimiter(REDIS_URL, client_factory=redis_factory(server))
    assert await limiter.ping() is False
    await limiter.start()
    await limiter.start()  # повторный старт не создаёт второго клиента
    assert await limiter.ping() is True
    server.connected = False
    with pytest.raises(RedisConnectionError):
        await limiter.ping()
    server.connected = True
    await limiter.stop()
    await limiter.stop()
    assert await limiter.ping() is False
