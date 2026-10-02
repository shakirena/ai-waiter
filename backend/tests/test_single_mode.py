"""AC-3 (story #39): приложение в режиме single без Redis — событие, задача через ~1 с, лимит, остановка."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

import pytest

from app.core.container import Container
from app.core.events import Event, tenant_channel
from app.core.ratelimit import rate_key
from app.core.scheduler import TaskRegistry
from app.core.single.events import InMemoryEventBus
from app.core.single.ratelimit import InMemoryRateLimiter
from app.core.single.scheduler import InProcessTaskScheduler
from app.main import create_app
from tests.conftest import make_settings


async def test_single_mode_end_to_end_without_redis(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    registry = TaskRegistry()
    runs: list[tuple[float, dict[str, Any]]] = []
    ran = asyncio.Event()

    @registry.task("demo.delayed")
    async def delayed(payload: dict[str, Any]) -> None:
        runs.append((time.monotonic(), payload))
        ran.set()

    app = create_app(make_settings(), registry=registry)
    caplog.set_level(logging.WARNING)
    async with app.router.lifespan_context(app):
        container: Container = app.state.container
        assert isinstance(container.event_bus, InMemoryEventBus)
        assert isinstance(container.scheduler, InProcessTaskScheduler)
        assert isinstance(container.rate_limiter, InMemoryRateLimiter)

        # Событие доходит до подписчика.
        channel = tenant_channel(1, "staff")
        listener_entered = asyncio.Event()
        received: list[Event] = []

        async def listen() -> None:
            async with container.event_bus.subscribe(channel) as events:
                listener_entered.set()
                async for event in events:
                    received.append(event)

        listener = asyncio.create_task(listen())
        await listener_entered.wait()
        await container.event_bus.publish(channel, Event(type="order.submitted", tenant_id=1, payload={"id": 1}))

        # Задача через 1 секунду выполняется один раз.
        started = time.monotonic()
        await container.scheduler.enqueue("demo.delayed", {"order_id": 1}, delay=timedelta(seconds=1))

        # Запрос сверх лимита получает отказ со временем до сброса окна.
        key = rate_key("guest_msg", "table", 1, 42)
        results = [await container.rate_limiter.hit(key, limit=2, window=timedelta(minutes=1)) for _ in range(3)]
        assert [r.allowed for r in results] == [True, True, False]
        assert 0 < results[-1].retry_after <= 60

        await asyncio.wait_for(ran.wait(), timeout=3)
        await asyncio.sleep(0.3)
        assert len(runs) == 1
        assert 0.9 <= runs[0][0] - started < 2.0
        assert [e.type for e in received] == ["order.submitted"]

        # Отложенная задача, которая не успеет выполниться до остановки.
        await container.scheduler.enqueue("demo.delayed", {"order_id": 2}, delay=timedelta(minutes=5))

    # После остановки: подписка закрыта, задача слушателя завершилась сама, планировщик остановлен.
    await asyncio.wait_for(listener, timeout=1)
    assert not container.scheduler.running  # type: ignore[attr-defined]
    assert len(runs) == 1
    assert [t for t in asyncio.all_tasks() if t.get_name().startswith("task:")] == []
    # Заглушек больше нет: lifespan не пишет NotImplementedError и ошибок компонентов.
    assert not [r for r in caplog.records if r.exc_info and r.exc_info[0] is NotImplementedError]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
