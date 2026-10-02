"""Фабрики подключений режима scaled (#40): ленивые клиенты и JSON-сериализация задач arq."""

from __future__ import annotations

import pytest
from arq.connections import ArqRedis
from redis.asyncio import Redis

from app.core.scaled.connection import (
    CONNECT_TIMEOUT_SECONDS,
    arq_redis_from_url,
    deserialize_job,
    redis_from_url,
    serialize_job,
)

REDIS_URL = "redis://:s3cret@redis:6379/3"


async def test_redis_from_url_does_not_connect() -> None:
    client = redis_from_url(REDIS_URL)
    assert isinstance(client, Redis)
    kwargs = client.connection_pool.connection_kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["db"]) == ("redis", 6379, 3)
    assert not client.connection_pool._available_connections  # конструктор не открывает соединений
    await client.aclose()


async def test_clients_have_connect_timeout() -> None:
    """Зависший Redis не должен держать запросы api до таймаута ОС."""
    client = redis_from_url(REDIS_URL)
    assert client.connection_pool.connection_kwargs["socket_connect_timeout"] == CONNECT_TIMEOUT_SECONDS
    await client.aclose()
    pool = arq_redis_from_url(REDIS_URL)
    assert pool.connection_pool.connection_kwargs["socket_connect_timeout"] == CONNECT_TIMEOUT_SECONDS
    await pool.aclose(close_connection_pool=True)


async def test_arq_redis_from_url_uses_json_serializer() -> None:
    pool = arq_redis_from_url(REDIS_URL)
    assert isinstance(pool, ArqRedis)
    assert pool.job_serializer is serialize_job
    assert pool.job_deserializer is deserialize_job
    assert not pool.connection_pool._available_connections
    await pool.aclose(close_connection_pool=True)


def test_serializer_round_trip_and_str_fallback() -> None:
    data = {"t": 1, "f": "orders.notify", "a": [{"total": "12.50"}], "k": {}, "et": 1}
    assert deserialize_job(serialize_job(data)) == data
    assert deserialize_job(serialize_job({"r": ValueError("boom")})) == {"r": "boom"}


def test_serializer_rejects_nan() -> None:
    with pytest.raises(ValueError):
        serialize_job({"x": float("nan")})
