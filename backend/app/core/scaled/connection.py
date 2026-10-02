"""Подключения к Redis для режима scaled (ADR-1).

Клиенты создаются лениво: конструктор не открывает соединений, первое соединение
устанавливается при первой команде. Поэтому сборка ``Container`` не ходит в сеть, а
недоступный при старте Redis не роняет процесс — его видно в ``/health/ready``.

Строка подключения (``REDIS_URL``) — секрет: в логи и тексты ошибок не попадает.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool, Redis

# Таймаут установки соединения: зависший Redis не должен держать запросы api до таймаута ОС.
# socket_timeout намеренно не задан: pub/sub-читатель легально простаивает без сообщений.
CONNECT_TIMEOUT_SECONDS = 3.0
HEALTH_CHECK_INTERVAL_SECONDS = 30

RedisFactory = Callable[[str], Redis]
ArqRedisFactory = Callable[[str], ArqRedis]


def serialize_job(data: dict[str, Any]) -> bytes:
    """Сериализатор arq: JSON вместо pickle по умолчанию.

    Payload задач и так обязан быть JSON-объектом (``validate_task``); JSON исключает
    выполнение произвольного кода при чтении данных из Redis. Несериализуемое в служебных
    полях arq (например, исключение в результате задачи) превращается в строку."""
    return json.dumps(data, default=str, allow_nan=False).encode("utf-8")


def deserialize_job(raw: bytes) -> dict[str, Any]:
    """Десериализатор arq, парный ``serialize_job``."""
    value: dict[str, Any] = json.loads(raw)
    return value


def redis_from_url(url: str) -> Redis:
    """Клиент Redis для шины событий и rate-limiter-а (без сетевых вызовов при создании)."""
    return Redis.from_url(
        url,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        health_check_interval=HEALTH_CHECK_INTERVAL_SECONDS,
    )


def arq_redis_from_url(url: str) -> ArqRedis:
    """Клиент arq для постановки задач; сериализация совпадает с ``WorkerSettings``."""
    return ArqRedis(
        pool_or_conn=ConnectionPool.from_url(
            url,
            socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
            health_check_interval=HEALTH_CHECK_INTERVAL_SECONDS,
        ),
        job_serializer=serialize_job,
        job_deserializer=deserialize_job,
    )
