from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.ratelimit import rate_key
from app.core.single import ratelimit as single_ratelimit
from app.core.single.ratelimit import InMemoryRateLimiter


class ManualClock:
    """Управляемые монотонные часы для детерминированных тестов окна."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


MINUTE = timedelta(minutes=1)


def test_rate_key_format() -> None:
    assert rate_key("guest_msg", "table", 1, 42) == "guest_msg:table:1:42"


def test_rate_key_rejects_separator_in_parts() -> None:
    with pytest.raises(ValueError):
        rate_key("guest_msg", "a:b")


async def test_limit_exceeded_within_window() -> None:
    rl = InMemoryRateLimiter()
    window = timedelta(minutes=1)
    results = [await rl.hit("k", limit=2, window=window) for _ in range(3)]
    assert [r.allowed for r in results] == [True, True, False]
    assert results[-1].remaining == 0
    assert results[-1].retry_after > 0


async def test_reset_clears_counter() -> None:
    rl = InMemoryRateLimiter()
    window = timedelta(minutes=1)
    await rl.hit("k", limit=1, window=window)
    await rl.reset("k")
    assert (await rl.hit("k", limit=1, window=window)).allowed


async def test_reset_of_unknown_key_is_noop() -> None:
    await InMemoryRateLimiter().reset("missing")


async def test_remaining_and_retry_after_follow_window() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(clock=clock)
    first = await rl.hit("k", limit=3, window=MINUTE)
    assert (first.allowed, first.limit, first.remaining, first.retry_after) == (True, 3, 2, 0.0)
    clock.advance(10)
    assert (await rl.hit("k", limit=3, window=MINUTE)).remaining == 1
    assert (await rl.hit("k", limit=3, window=MINUTE)).remaining == 0
    clock.advance(5)
    denied = await rl.hit("k", limit=3, window=MINUTE)
    assert not denied.allowed
    assert denied.retry_after == pytest.approx(45.0)  # окно началось с первого обращения


async def test_window_expiry_starts_new_window() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(clock=clock)
    await rl.hit("k", limit=1, window=MINUTE)
    assert not (await rl.hit("k", limit=1, window=MINUTE)).allowed
    clock.advance(60)  # ровно граница окна — окно истекло
    renewed = await rl.hit("k", limit=1, window=MINUTE)
    assert renewed.allowed and renewed.remaining == 0


async def test_denied_hits_are_counted_and_window_is_not_extended() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(clock=clock)
    await rl.hit("k", limit=1, window=MINUTE)
    for _ in range(5):
        clock.advance(10)
        assert not (await rl.hit("k", limit=1, window=MINUTE)).allowed
    assert rl._windows["k"].count == 6
    clock.advance(10)
    assert (await rl.hit("k", limit=1, window=MINUTE)).allowed  # 60 с с начала окна


async def test_window_duration_fixed_by_first_hit() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(clock=clock)
    await rl.hit("k", limit=1, window=timedelta(seconds=10))
    denied = await rl.hit("k", limit=1, window=timedelta(hours=1))
    assert denied.retry_after == pytest.approx(10.0)


async def test_keys_are_independent() -> None:
    rl = InMemoryRateLimiter(clock=ManualClock())
    k1, k2 = rate_key("guest_msg", "table", 1, 42), rate_key("guest_msg", "table", 2, 42)
    assert (await rl.hit(k1, limit=1, window=MINUTE)).allowed
    assert not (await rl.hit(k1, limit=1, window=MINUTE)).allowed
    assert (await rl.hit(k2, limit=1, window=MINUTE)).allowed  # другой tenant — свой счётчик


async def test_max_keys_purges_expired_windows_first() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(max_keys=3, clock=clock)
    await rl.hit("short", limit=1, window=timedelta(seconds=1))
    await rl.hit("long-a", limit=1, window=MINUTE)
    await rl.hit("long-b", limit=1, window=MINUTE)
    clock.advance(2)
    await rl.hit("new", limit=1, window=MINUTE)
    assert set(rl._windows) == {"long-a", "long-b", "new"}
    assert not (await rl.hit("long-a", limit=1, window=MINUTE)).allowed  # активное окно сохранено


async def test_max_keys_evicts_oldest_when_nothing_expired() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(max_keys=2, clock=clock)
    await rl.hit("a", limit=1, window=MINUTE)
    clock.advance(1)
    await rl.hit("b", limit=1, window=MINUTE)
    clock.advance(1)
    await rl.hit("c", limit=1, window=MINUTE)
    assert list(rl._windows) == ["b", "c"]
    assert len(rl._windows) <= 2


async def test_renewed_window_moves_key_to_newest() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(max_keys=2, clock=clock)
    await rl.hit("a", limit=1, window=timedelta(seconds=5))
    await rl.hit("b", limit=1, window=MINUTE)
    clock.advance(6)
    await rl.hit("a", limit=1, window=MINUTE)  # новое окно для «a» — теперь «b» самый старый
    await rl.hit("c", limit=1, window=MINUTE)
    assert list(rl._windows) == ["a", "c"]


async def test_purge_scan_is_throttled() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(max_keys=2, clock=clock)
    await rl.hit("a", limit=1, window=MINUTE)
    await rl.hit("b", limit=1, window=MINUTE)
    await rl.hit("c", limit=1, window=MINUTE)  # полный проход + вытеснение «a»
    first_purge = rl._last_purge
    clock.advance(single_ratelimit.PURGE_MIN_INTERVAL / 2)
    await rl.hit("d", limit=1, window=MINUTE)  # без полного прохода, только вытеснение
    assert rl._last_purge == first_purge
    assert list(rl._windows) == ["c", "d"]


async def test_memory_stays_bounded_under_many_keys() -> None:
    clock = ManualClock()
    rl = InMemoryRateLimiter(max_keys=50, clock=clock)
    for i in range(1000):
        clock.advance(0.01)
        await rl.hit(f"ip:{i}", limit=5, window=MINUTE)
    assert len(rl._windows) == 50


async def test_hit_validates_args_like_scaled() -> None:
    rl = InMemoryRateLimiter()
    with pytest.raises(ValueError, match="limit"):
        await rl.hit("k", limit=0, window=MINUTE)
    with pytest.raises(ValueError, match="window"):
        await rl.hit("k", limit=1, window=timedelta(0))
    with pytest.raises(ValueError, match="ключ"):
        await rl.hit("", limit=1, window=MINUTE)
    assert rl._windows == {}


@pytest.mark.parametrize("max_keys", [0, -5, True, 2.0])
def test_max_keys_must_be_positive_int(max_keys: object) -> None:
    with pytest.raises(ValueError, match="max_keys"):
        InMemoryRateLimiter(max_keys=max_keys)  # type: ignore[arg-type]


async def test_lifecycle_and_ping_are_noops() -> None:
    rl = InMemoryRateLimiter()
    await rl.start()
    assert await rl.ping() is True
    await rl.stop()
