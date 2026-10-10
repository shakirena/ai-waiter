"""Тестовые двойники EventBus/TaskScheduler/RateLimiter (#38).

Нужны, чтобы проверять контейнер, lifespan и /health/ready независимо от реализаций
single (#39) и scaled (#40). Каждый двойник пишет вызовы в общий журнал ``calls``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from typing import Any

from app.core.config import Settings
from app.core.container import Container
from app.core.events import Event, EventBus
from app.core.ratelimit import RateLimiter, RateLimitResult, validate_hit_args
from app.core.scheduler import TaskPayload, TaskRegistry, TaskScheduler, validate_delay, validate_task


class _Lifecycle:
    """Общая часть двойников: журнал start/stop, управляемые ошибки и результат ping()."""

    name = "component"

    def __init__(
        self,
        calls: list[str] | None = None,
        *,
        start_error: Exception | None = None,
        stop_error: Exception | None = None,
        ping_result: bool = True,
        ping_error: Exception | None = None,
        ping_delay: float = 0.0,
    ) -> None:
        self.calls = calls if calls is not None else []
        self.start_error = start_error
        self.stop_error = stop_error
        self.ping_result = ping_result
        self.ping_error = ping_error
        self.ping_delay = ping_delay

    async def start(self) -> None:
        self.calls.append(f"{self.name}.start")
        if self.start_error is not None:
            raise self.start_error

    async def stop(self) -> None:
        self.calls.append(f"{self.name}.stop")
        if self.stop_error is not None:
            raise self.stop_error

    async def ping(self) -> bool:
        if self.ping_delay:
            await asyncio.sleep(self.ping_delay)
        if self.ping_error is not None:
            raise self.ping_error
        return self.ping_result


class FakeEventBus(_Lifecycle, EventBus):
    name = "event_bus"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.published: list[tuple[str, Event]] = []

    async def publish(self, channel: str, event: Event) -> None:
        self.published.append((channel, event))

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[AsyncIterator[Event]]:
        @asynccontextmanager
        async def _subscription() -> AsyncIterator[AsyncIterator[Event]]:
            async def _events() -> AsyncIterator[Event]:
                for published_channel, event in list(self.published):
                    if published_channel == channel:
                        yield event

            yield _events()

        return _subscription()


class FakeRateLimiter(_Lifecycle, RateLimiter):
    name = "rate_limiter"

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        validate_hit_args(limit, window)
        return RateLimitResult(allowed=True, limit=limit, remaining=limit - 1, retry_after=0.0)

    async def reset(self, key: str) -> None:
        return None


class FakeTaskScheduler(_Lifecycle, TaskScheduler):
    """Двойник с проверками enqueue, общими для всех реализаций (``validate_task``/``validate_delay``)."""

    name = "scheduler"

    def __init__(self, registry: TaskRegistry, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.registry = registry
        self.jobs: dict[str, tuple[str, TaskPayload]] = {}

    async def enqueue(
        self,
        name: str,
        payload: TaskPayload | None = None,
        *,
        delay: timedelta | None = None,
        job_id: str | None = None,
    ) -> str:
        checked = validate_task(self.registry, name, payload)
        validate_delay(delay)
        job_id = job_id or f"job-{len(self.jobs) + 1}"
        self.jobs.setdefault(job_id, (name, checked))
        return job_id

    async def cancel(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None


def make_fake_container(
    settings: Settings,
    calls: list[str] | None = None,
    *,
    bus: FakeEventBus | None = None,
    rate_limiter: FakeRateLimiter | None = None,
    scheduler: FakeTaskScheduler | None = None,
) -> Container:
    calls = calls if calls is not None else []
    return Container(
        settings=settings,
        event_bus=bus or FakeEventBus(calls),
        scheduler=scheduler or FakeTaskScheduler(TaskRegistry(), calls),
        rate_limiter=rate_limiter or FakeRateLimiter(calls),
    )
