"""Первичные ключи — UUIDv7 (ADR-7.1).

В Python 3.12 нет ``uuid.uuid7`` (появится в 3.14), в PostgreSQL 16 нет ``uuidv7()``
(появится в 18), поэтому ключ генерирует приложение по RFC 9562 без внешних зависимостей.

Раскладка 128 бит (RFC 9562, раздел 5.7; метод 2 раздела 6.2 — счётчик в случайной части):

- 48 бит — миллисекунды Unix-времени;
- 4 бита — версия 7;
- 12 бит ``rand_a`` — старшие биты 42-битного счётчика;
- 2 бита — вариант RFC 4122 (``10``);
- 30 бит — младшие биты счётчика и 32 случайных бита (``secrets``).

В новой миллисекунде счётчик начинается со случайного значения (старший бит — 0, запас на
приращения), в той же миллисекунде увеличивается на 1. Если часы пошли назад, используется
последняя выданная миллисекунда; при переполнении счётчика метка времени сдвигается на 1 мс.
Поэтому ключи одного процесса строго возрастают — хорошая локальность B-tree и порядок
выдачи заказов коннектору.

В БД у колонок ``id`` есть запасной ``server_default gen_random_uuid()`` (v4, встроен в
PostgreSQL 13+, расширение не нужно) — для ручных INSERT; приложение всегда передаёт v7.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

_COUNTER_BITS = 42
_COUNTER_MAX = (1 << _COUNTER_BITS) - 1
_COUNTER_LOW_BITS = 30
_TIMESTAMP_MASK = (1 << 48) - 1

_lock = threading.Lock()
_last_ms = 0
_last_counter = 0


def _now_ms() -> int:
    """Текущее Unix-время в миллисекундах (отдельная функция — тесты подменяют часы)."""
    return time.time_ns() // 1_000_000


def _random_counter() -> int:
    """Случайное начальное значение счётчика: старший бит — 0, чтобы приращения не переполняли его."""
    return secrets.randbits(_COUNTER_BITS - 1)


def build_uuid7(unix_ms: int, counter: int, tail: int) -> uuid.UUID:
    """Собрать UUIDv7 из метки времени, 42-битного счётчика и 32 случайных бит."""
    value = (unix_ms & _TIMESTAMP_MASK) << 80
    value |= 0x7 << 76
    value |= (counter >> _COUNTER_LOW_BITS) << 64
    value |= 0b10 << 62
    value |= (counter & ((1 << _COUNTER_LOW_BITS) - 1)) << 32
    value |= tail & 0xFFFF_FFFF
    return uuid.UUID(int=value)


def new_id() -> uuid.UUID:
    """Новый UUIDv7. Используется как ``default=new_id`` в ``mapped_column`` первичных ключей."""
    global _last_ms, _last_counter
    with _lock:
        now = _now_ms()
        if now > _last_ms:
            unix_ms, counter = now, _random_counter()
        else:
            unix_ms, counter = _last_ms, _last_counter + 1
            if counter > _COUNTER_MAX:
                unix_ms, counter = unix_ms + 1, _random_counter()
        _last_ms, _last_counter = unix_ms, counter
    return build_uuid7(unix_ms, counter, secrets.randbits(32))
