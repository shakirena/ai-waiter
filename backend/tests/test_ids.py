"""UUIDv7 (ADR-7.1, RFC 9562): версия, вариант, метка времени, строгая монотонность."""

from __future__ import annotations

import itertools
import threading
import time
import uuid

import pytest

from app.db import ids
from app.db.ids import build_uuid7, new_id


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Управляемые часы: ``new_id`` читает ``clock[0]``; состояние генератора сброшено."""
    current = [1_700_000_000_000]
    monkeypatch.setattr(ids, "_now_ms", lambda: current[0])
    monkeypatch.setattr(ids, "_last_ms", 0)
    monkeypatch.setattr(ids, "_last_counter", 0)
    return current


def _unix_ms(value: uuid.UUID) -> int:
    return value.int >> 80


def test_version_and_variant() -> None:
    value = new_id()
    assert isinstance(value, uuid.UUID)
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_timestamp_is_current_unix_milliseconds() -> None:
    before = time.time_ns() // 1_000_000
    value = new_id()
    after = time.time_ns() // 1_000_000
    assert before <= _unix_ms(value) <= after + 1


def test_ids_are_strictly_increasing_and_unique() -> None:
    values = [new_id() for _ in range(10_000)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert all(a.int < b.int for a, b in itertools.pairwise(values))


def test_same_millisecond_increments_counter(clock: list[int]) -> None:
    first, second = new_id(), new_id()
    assert _unix_ms(first) == _unix_ms(second) == clock[0]
    assert first < second


def test_clock_going_backwards_keeps_order(clock: list[int]) -> None:
    first = new_id()
    clock[0] -= 5_000
    second = new_id()
    assert second > first
    assert _unix_ms(second) == _unix_ms(first)


def test_counter_overflow_moves_to_next_millisecond(clock: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    first = new_id()
    monkeypatch.setattr(ids, "_last_counter", ids._COUNTER_MAX)
    second = new_id()
    assert _unix_ms(second) == _unix_ms(first) + 1
    assert second > first


def test_new_millisecond_starts_random_counter(clock: list[int]) -> None:
    first = new_id()
    clock[0] += 1
    second = new_id()
    assert _unix_ms(second) == _unix_ms(first) + 1
    assert second > first


def test_build_uuid7_layout() -> None:
    value = build_uuid7(0x0123_4567_89AB, (1 << 42) - 1, 0xFFFF_FFFF)
    assert value.version == 7
    assert value.variant == uuid.RFC_4122
    assert _unix_ms(value) == 0x0123_4567_89AB
    assert str(value).startswith("01234567-89ab-7fff-bfff-ffff")


def test_thread_safe_uniqueness() -> None:
    results: list[uuid.UUID] = []
    lock = threading.Lock()

    def worker() -> None:
        local = [new_id() for _ in range(2_000)]
        with lock:
            results.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(results)) == len(results) == 8_000
