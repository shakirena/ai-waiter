from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.ratelimit import rate_key
from app.core.single.ratelimit import InMemoryRateLimiter


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
