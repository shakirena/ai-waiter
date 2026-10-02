"""Фабрики клиентов на fakeredis для unit-тестов режима scaled (#40, spec AC-4).

Все клиенты, созданные из одного ``FakeServer``, видят общие данные — так моделируются
несколько процессов api, работающих с одним Redis. Настоящий Redis не нужен (Windows/Linux).
"""

from __future__ import annotations

from arq.connections import ArqRedis
from fakeredis import FakeAsyncRedis, FakeServer
from redis.asyncio import Redis

from app.core.scaled.connection import ArqRedisFactory, RedisFactory, deserialize_job, serialize_job


def redis_factory(server: FakeServer) -> RedisFactory:
    """Фабрика для ``client_factory`` RedisEventBus/RedisRateLimiter."""

    def make(url: str) -> Redis:
        return FakeAsyncRedis(server=server)

    return make


def arq_factory(server: FakeServer) -> ArqRedisFactory:
    """Фабрика для ``pool_factory`` ArqTaskScheduler."""

    def make(url: str) -> ArqRedis:
        return ArqRedis(
            pool_or_conn=FakeAsyncRedis(server=server).connection_pool,
            job_serializer=serialize_job,
            job_deserializer=deserialize_job,
        )

    return make
