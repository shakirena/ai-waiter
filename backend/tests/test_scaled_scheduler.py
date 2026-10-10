"""ArqTaskScheduler на fakeredis (#40, spec AC-4): общие проверки enqueue, постановка в очередь
arq, дедупликация по job_id, отложенные задачи, отмена."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from arq.connections import ArqRedis
from arq.constants import default_queue_name, in_progress_key_prefix, job_key_prefix
from arq.jobs import Job, JobStatus
from fakeredis import FakeServer
from redis.exceptions import WatchError

from app.core.scaled.scheduler import ArqTaskScheduler
from app.core.scheduler import TaskPayload, TaskRegistry
from tests.fake_redis import arq_factory, redis_factory

REDIS_URL = "redis://redis:6379/0"


def _registry() -> TaskRegistry:
    registry = TaskRegistry()

    @registry.task("orders.notify")
    async def notify(payload: TaskPayload) -> None:
        return None

    return registry


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
async def scheduler(server: FakeServer) -> AsyncIterator[ArqTaskScheduler]:
    instance = ArqTaskScheduler(REDIS_URL, _registry(), pool_factory=arq_factory(server))
    await instance.start()
    yield instance
    await instance.stop()


@pytest.fixture
async def pool(server: FakeServer) -> AsyncIterator[ArqRedis]:
    client = arq_factory(server)(REDIS_URL)
    yield client
    await client.aclose(close_connection_pool=True)


async def test_enqueue_puts_job_into_arq_queue(scheduler: ArqTaskScheduler, pool: ArqRedis) -> None:
    job_id = await scheduler.enqueue("orders.notify", {"order_id": 5, "total": "12.50"})
    assert await pool.zscore(default_queue_name, job_id) is not None
    job = Job(job_id, pool, _deserializer=pool.job_deserializer)
    info = await job.info()
    assert info is not None
    assert info.function == "orders.notify"
    assert list(info.args) == [{"order_id": 5, "total": "12.50"}]
    assert await job.status() is JobStatus.queued


async def test_job_is_stored_as_json_not_pickle(scheduler: ArqTaskScheduler, server: FakeServer) -> None:
    job_id = await scheduler.enqueue("orders.notify", {"a": 1})
    raw = redis_factory(server)(REDIS_URL)
    stored = await raw.get(job_key_prefix + job_id)
    assert stored is not None and stored.startswith(b"{")
    await raw.aclose()


async def test_none_payload_becomes_empty_dict(scheduler: ArqTaskScheduler, pool: ArqRedis) -> None:
    job_id = await scheduler.enqueue("orders.notify")
    info = await Job(job_id, pool, _deserializer=pool.job_deserializer).info()
    assert info is not None
    assert list(info.args) == [{}]


async def test_unknown_task_rejected_before_redis() -> None:
    pool_mock = MagicMock()
    scheduler = ArqTaskScheduler(REDIS_URL, _registry(), pool_factory=lambda url: pool_mock)
    await scheduler.start()
    with pytest.raises(KeyError, match="не зарегистрирована"):
        await scheduler.enqueue("missing")
    pool_mock.enqueue_job.assert_not_called()


@pytest.mark.parametrize("payload", [{"price": Decimal("1.00")}, {1: "a"}, ["x"], {"x": float("nan")}])
async def test_non_json_payload_rejected(scheduler: ArqTaskScheduler, payload: Any) -> None:
    with pytest.raises(TypeError):
        await scheduler.enqueue("orders.notify", payload)


async def test_negative_delay_rejected(scheduler: ArqTaskScheduler) -> None:
    with pytest.raises(ValueError, match="delay"):
        await scheduler.enqueue("orders.notify", delay=timedelta(seconds=-1))


@pytest.mark.parametrize("job_id", ["", 5])
async def test_invalid_job_id_rejected(scheduler: ArqTaskScheduler, job_id: Any) -> None:
    with pytest.raises(ValueError, match="job_id"):
        await scheduler.enqueue("orders.notify", job_id=job_id)


async def test_validation_order_name_first() -> None:
    """validate_task вызывается первым: неизвестное имя важнее неверной задержки."""
    scheduler = ArqTaskScheduler(REDIS_URL, _registry(), pool_factory=lambda url: MagicMock())
    await scheduler.start()
    with pytest.raises(KeyError):
        await scheduler.enqueue("missing", delay=timedelta(seconds=-1))


async def test_job_id_deduplicates(scheduler: ArqTaskScheduler, pool: ArqRedis) -> None:
    first = await scheduler.enqueue("orders.notify", {"n": 1}, job_id="order-5-notify")
    second = await scheduler.enqueue("orders.notify", {"n": 2}, job_id="order-5-notify")
    assert first == second == "order-5-notify"
    assert await pool.zcard(default_queue_name) == 1
    info = await Job("order-5-notify", pool, _deserializer=pool.job_deserializer).info()
    assert info is not None
    assert list(info.args) == [{"n": 1}]


async def test_delay_defers_job(scheduler: ArqTaskScheduler, pool: ArqRedis) -> None:
    now_id = await scheduler.enqueue("orders.notify", job_id="now")
    later_id = await scheduler.enqueue("orders.notify", delay=timedelta(minutes=10), job_id="later")
    now_score = await pool.zscore(default_queue_name, now_id)
    later_score = await pool.zscore(default_queue_name, later_id)
    assert now_score is not None and later_score is not None
    assert 590_000 <= later_score - now_score <= 610_000
    assert await Job(later_id, pool).status() is JobStatus.deferred


async def test_cancel_removes_pending_job(scheduler: ArqTaskScheduler, pool: ArqRedis) -> None:
    job_id = await scheduler.enqueue("orders.notify", delay=timedelta(minutes=5), job_id="esc-1")
    assert await scheduler.cancel(job_id) is True
    assert await pool.zscore(default_queue_name, job_id) is None
    assert await pool.exists(job_key_prefix + job_id) == 0
    assert await scheduler.cancel(job_id) is False  # уже отменена
    # После отмены тот же job_id можно поставить снова.
    assert await scheduler.enqueue("orders.notify", job_id="esc-1") == "esc-1"
    assert await pool.zcard(default_queue_name) == 1


async def test_cancel_unknown_job(scheduler: ArqTaskScheduler) -> None:
    assert await scheduler.cancel("missing") is False


async def test_cancel_in_progress_job_returns_false(scheduler: ArqTaskScheduler, pool: ArqRedis) -> None:
    job_id = await scheduler.enqueue("orders.notify", job_id="busy")
    await pool.set(in_progress_key_prefix + job_id, b"1")
    assert await scheduler.cancel(job_id) is False
    assert await pool.zscore(default_queue_name, job_id) is not None


async def test_cancel_race_with_worker_returns_false() -> None:
    pipe = MagicMock()
    pipe.watch = AsyncMock()
    pipe.exists = AsyncMock(return_value=0)
    pipe.execute = AsyncMock(side_effect=WatchError("changed"))
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    pool_mock = MagicMock()
    pool_mock.pipeline.return_value = pipe
    pool_mock.default_queue_name = default_queue_name
    scheduler = ArqTaskScheduler(REDIS_URL, _registry(), pool_factory=lambda url: pool_mock)
    await scheduler.start()
    assert await scheduler.cancel("racing") is False
    pipe.watch.assert_awaited_once_with(in_progress_key_prefix + "racing", job_key_prefix + "racing")


async def test_not_started_raises() -> None:
    scheduler = ArqTaskScheduler(REDIS_URL, _registry())
    with pytest.raises(RuntimeError, match="не запущен"):
        await scheduler.enqueue("orders.notify")
    with pytest.raises(RuntimeError, match="не запущен"):
        await scheduler.cancel("x")


async def test_lifecycle_idempotent() -> None:
    created: list[MagicMock] = []

    def factory(url: str) -> Any:
        pool_mock = MagicMock()
        pool_mock.aclose = AsyncMock()
        created.append(pool_mock)
        return pool_mock

    scheduler = ArqTaskScheduler(REDIS_URL, _registry(), pool_factory=factory)
    await scheduler.start()
    await scheduler.start()
    assert len(created) == 1
    await scheduler.stop()
    await scheduler.stop()
    created[0].aclose.assert_awaited_once_with(close_connection_pool=True)
