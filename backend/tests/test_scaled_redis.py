"""Проверки режима scaled на настоящем Redis (#40, spec AC-4).

Маркер ``scaled``: запускаются только в Linux-джобе CI с сервисом Redis (``pytest -m scaled``),
адрес — из ``REDIS_URL``; без него тесты пропускаются. Unit-тесты на fakeredis — в
``test_scaled_events.py``, ``test_scaled_ratelimit.py``, ``test_scaled_scheduler.py``, ``test_scaled_worker.py``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from arq.worker import create_worker

from app.core.config import AppMode
from app.core.events import Event, tenant_channel
from app.core.ratelimit import rate_key
from app.core.scaled.events import RedisEventBus
from app.core.scaled.ratelimit import RedisRateLimiter
from app.core.scaled.scheduler import ArqTaskScheduler
from app.core.scaled.worker import build_worker_settings
from app.core.scheduler import TaskPayload, TaskRegistry
from tests.conftest import make_settings

pytestmark = [
    pytest.mark.scaled,
    pytest.mark.skipif(not os.environ.get("REDIS_URL"), reason="REDIS_URL не задан: нужен настоящий Redis"),
]


def _redis_url() -> str:
    return os.environ["REDIS_URL"]


async def test_event_between_instances() -> None:
    first, second = RedisEventBus(_redis_url()), RedisEventBus(_redis_url())
    await first.start()
    await second.start()
    channel = tenant_channel(1, f"it-{uuid.uuid4().hex}")
    event = Event(type="it.ping", tenant_id=1, payload={"n": 1})
    async with second.subscribe(channel) as events:
        await first.publish(channel, event)
        assert await asyncio.wait_for(anext(events), 5) == event
    assert await first.ping() is True
    await first.stop()
    await second.stop()


async def test_rate_limit_shared_between_instances() -> None:
    first, second = RedisRateLimiter(_redis_url()), RedisRateLimiter(_redis_url())
    await first.start()
    await second.start()
    key = rate_key("it", uuid.uuid4().hex)
    window = timedelta(seconds=30)
    assert (await first.hit(key, limit=1, window=window)).allowed
    blocked = await second.hit(key, limit=1, window=window)
    assert not blocked.allowed
    assert 0 < blocked.retry_after <= 30
    await first.reset(key)
    await first.stop()
    await second.stop()


async def test_task_processed_by_worker() -> None:
    calls: list[TaskPayload] = []
    registry = TaskRegistry()

    @registry.task("it.record")
    async def record(payload: TaskPayload) -> None:
        calls.append(payload)

    scheduler = ArqTaskScheduler(_redis_url(), registry)
    await scheduler.start()
    await scheduler.enqueue("it.record", {"n": 1}, job_id=f"it-{uuid.uuid4().hex}")
    settings = make_settings(app_mode=AppMode.SCALED, redis_url=_redis_url())
    worker = create_worker(build_worker_settings(settings, registry), burst=True, poll_delay=0.05)
    try:
        await worker.main()
    finally:
        await worker.close()
        await scheduler.stop()
    assert calls == [{"n": 1}]
