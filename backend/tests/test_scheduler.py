from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core.scheduler import PeriodicTask, TaskRegistry
from app.core.single import scheduler as single_scheduler
from app.core.single.scheduler import InProcessTaskScheduler

SHORT = timedelta(milliseconds=50)


def test_registry_rejects_duplicate_names(registry: TaskRegistry) -> None:
    @registry.task("demo")
    async def first(payload: dict[str, Any]) -> None: ...

    with pytest.raises(ValueError):

        @registry.task("demo")
        async def second(payload: dict[str, Any]) -> None: ...


@pytest.mark.parametrize("minutes", [1, 5, 15, 30, 60, 120, 1440])
def test_periodic_interval_valid(minutes: int) -> None:
    PeriodicTask(name="x", every_minutes=minutes)


@pytest.mark.parametrize("minutes", [0, 7, 45, 90, 2000])
def test_periodic_interval_invalid(minutes: int) -> None:
    with pytest.raises(ValueError):
        PeriodicTask(name="x", every_minutes=minutes)


# ---------------------------------------------------------------- InProcessTaskScheduler


class Recorder:
    """Обработчик, запоминающий вызовы и сигнализирующий о каждом."""

    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, Any]]] = []
        self.called = asyncio.Event()

    async def __call__(self, payload: dict[str, Any]) -> None:
        self.calls.append((time.monotonic(), payload))
        self.called.set()


@pytest.fixture
def recorder(registry: TaskRegistry) -> Recorder:
    rec = Recorder()
    registry.task("demo")(rec)
    return rec


@pytest.fixture
async def scheduler(registry: TaskRegistry) -> AsyncIterator[InProcessTaskScheduler]:
    sched = InProcessTaskScheduler(registry, shutdown_timeout=0.5)
    await sched.start()
    yield sched
    await sched.stop()


async def test_enqueue_rejects_unknown_task_and_non_json_payload(
    scheduler: InProcessTaskScheduler, recorder: Recorder
) -> None:
    with pytest.raises(KeyError):
        await scheduler.enqueue("unknown")
    with pytest.raises(TypeError):
        await scheduler.enqueue("demo", {"amount": Decimal("12.50")})
    with pytest.raises(TypeError):
        await scheduler.enqueue("demo", {"at": datetime.now(UTC)})
    with pytest.raises(ValueError, match="delay"):
        await scheduler.enqueue("demo", delay=timedelta(seconds=-1))
    with pytest.raises(ValueError, match="job_id"):
        await scheduler.enqueue("demo", job_id="")
    assert scheduler._pending == set()


async def test_validation_happens_before_running_check(registry: TaskRegistry, recorder: Recorder) -> None:
    sched = InProcessTaskScheduler(registry)
    with pytest.raises(KeyError):
        await sched.enqueue("unknown")
    with pytest.raises(RuntimeError, match="не запущен"):
        await sched.enqueue("demo")


async def test_enqueue_runs_handler_in_single_mode(scheduler: InProcessTaskScheduler, recorder: Recorder) -> None:
    job_id = await scheduler.enqueue("demo", {"order_id": 5, "total": "12.50"})
    await asyncio.wait_for(recorder.called.wait(), timeout=2)
    assert [p for _, p in recorder.calls] == [{"order_id": 5, "total": "12.50"}]
    assert isinstance(job_id, str) and job_id


async def test_none_payload_becomes_empty_dict(scheduler: InProcessTaskScheduler, recorder: Recorder) -> None:
    await scheduler.enqueue("demo")
    await asyncio.wait_for(recorder.called.wait(), timeout=2)
    assert recorder.calls[0][1] == {}


async def test_delayed_task_runs_once_after_about_one_second(
    scheduler: InProcessTaskScheduler, recorder: Recorder
) -> None:
    started = time.monotonic()
    await scheduler.enqueue("demo", {"n": 1}, delay=timedelta(seconds=1))
    await asyncio.sleep(0.5)
    assert recorder.calls == []
    await asyncio.wait_for(recorder.called.wait(), timeout=3)
    await asyncio.sleep(0.3)  # повторного запуска нет
    assert len(recorder.calls) == 1
    assert 0.9 <= recorder.calls[0][0] - started < 2.0


async def test_payload_is_copied_at_enqueue(scheduler: InProcessTaskScheduler, recorder: Recorder) -> None:
    payload: dict[str, Any] = {"items": [1, 2]}
    await scheduler.enqueue("demo", payload, delay=SHORT)
    payload["items"].append(3)
    await asyncio.wait_for(recorder.called.wait(), timeout=2)
    assert recorder.calls[0][1] == {"items": [1, 2]}


async def test_failed_add_job_does_not_leave_job_id_pending(
    scheduler: InProcessTaskScheduler, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если APScheduler отверг задачу, job_id не должен навсегда считаться поставленным."""
    inner = scheduler._scheduler
    assert inner is not None
    original = inner.add_job

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OverflowError("слишком большая задержка")

    monkeypatch.setattr(inner, "add_job", broken)
    with pytest.raises(OverflowError):
        await scheduler.enqueue("demo", {"n": 1}, job_id="retry:1")
    monkeypatch.setattr(inner, "add_job", original)
    await scheduler.enqueue("demo", {"n": 2}, job_id="retry:1")
    await asyncio.wait_for(recorder.called.wait(), timeout=2)
    assert [p for _, p in recorder.calls] == [{"n": 2}]


async def test_job_id_deduplicates_pending_task(scheduler: InProcessTaskScheduler, recorder: Recorder) -> None:
    first = await scheduler.enqueue("demo", {"n": 1}, delay=SHORT, job_id="escalate:7")
    second = await scheduler.enqueue("demo", {"n": 2}, delay=SHORT, job_id="escalate:7")
    assert first == second == "escalate:7"
    await asyncio.wait_for(recorder.called.wait(), timeout=2)
    await asyncio.sleep(0.1)
    assert [p for _, p in recorder.calls] == [{"n": 1}]


async def test_job_id_deduplicates_running_task_and_is_reusable_after(
    scheduler: InProcessTaskScheduler, registry: TaskRegistry
) -> None:
    release = asyncio.Event()
    started = asyncio.Event()
    runs: list[int] = []

    @registry.task("slow")
    async def slow(payload: dict[str, Any]) -> None:
        runs.append(payload["n"])
        started.set()
        await release.wait()

    await scheduler.enqueue("slow", {"n": 1}, job_id="same")
    await asyncio.wait_for(started.wait(), timeout=2)
    assert await scheduler.enqueue("slow", {"n": 2}, job_id="same") == "same"
    assert await scheduler.cancel("same") is False  # уже выполняется
    release.set()
    await asyncio.sleep(0.05)
    assert runs == [1]
    started.clear()
    await scheduler.enqueue("slow", {"n": 3}, job_id="same")  # после завершения id свободен
    await asyncio.wait_for(started.wait(), timeout=2)
    assert runs == [1, 3]


async def test_cancel_pending_task(scheduler: InProcessTaskScheduler, recorder: Recorder) -> None:
    job_id = await scheduler.enqueue("demo", delay=timedelta(milliseconds=200))
    assert await scheduler.cancel(job_id) is True
    assert await scheduler.cancel(job_id) is False
    assert await scheduler.cancel("never-existed") is False
    await asyncio.sleep(0.4)
    assert recorder.calls == []


async def test_cancel_after_apscheduler_handed_job_over(scheduler: InProcessTaskScheduler, recorder: Recorder) -> None:
    """Гонка: APScheduler уже удалил сработавшую задачу, но запускатель ещё не выполнился."""
    job_id = await scheduler.enqueue("demo", delay=timedelta(seconds=30))
    assert scheduler._scheduler is not None
    scheduler._scheduler.remove_job(single_scheduler._ONE_OFF_PREFIX + job_id)
    assert await scheduler.cancel(job_id) is True
    await scheduler._launch_one_off(job_id, "demo", {})  # запускатель видит отмену
    await asyncio.sleep(0.05)
    assert recorder.calls == []


async def test_handler_exception_is_logged_and_scheduler_keeps_working(
    scheduler: InProcessTaskScheduler, registry: TaskRegistry, recorder: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    failed = asyncio.Event()

    @registry.task("boom")
    async def boom(payload: dict[str, Any]) -> None:
        failed.set()
        raise RuntimeError("сбой обработчика")

    with caplog.at_level(logging.ERROR, logger=single_scheduler.__name__):
        await scheduler.enqueue("boom")
        await asyncio.wait_for(failed.wait(), timeout=2)
        await asyncio.sleep(0.05)
    errors = [r for r in caplog.records if r.name == single_scheduler.__name__ and r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].task == "boom"  # type: ignore[attr-defined]
    await scheduler.enqueue("demo")
    await asyncio.wait_for(recorder.called.wait(), timeout=2)


async def test_periodic_tasks_registered_with_interval(registry: TaskRegistry) -> None:
    runs: list[dict[str, Any]] = []

    @registry.periodic("sweep", every_minutes=5)
    async def sweep(payload: dict[str, Any]) -> None:
        runs.append(payload)

    sched = InProcessTaskScheduler(registry)
    await sched.start()
    try:
        assert sched._scheduler is not None
        job = sched._scheduler.get_job(single_scheduler._PERIODIC_PREFIX + "sweep")
        assert job is not None
        assert job.trigger.interval == timedelta(minutes=5)
        assert job.next_run_time > datetime.now(UTC) + timedelta(minutes=4)
        # Ускоряем время следующего запуска — APScheduler должен выполнить задачу сам.
        job.modify(next_run_time=datetime.now(UTC))
        sched._scheduler.wakeup()
        for _ in range(100):
            if runs:
                break
            await asyncio.sleep(0.01)
        assert runs == [{}]
        refreshed = sched._scheduler.get_job(single_scheduler._PERIODIC_PREFIX + "sweep")
        assert refreshed is not None  # периодическая задача остаётся в расписании
        assert await sched.cancel("sweep") is False  # периодические задачи через cancel не снимаются
    finally:
        await sched.stop()


async def test_periodic_run_skipped_while_previous_still_running(
    registry: TaskRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    release = asyncio.Event()
    runs = 0

    @registry.periodic("sweep", every_minutes=1)
    async def sweep(payload: dict[str, Any]) -> None:
        nonlocal runs
        runs += 1
        await release.wait()

    sched = InProcessTaskScheduler(registry)
    await sched.start()
    try:
        with caplog.at_level(logging.WARNING, logger=single_scheduler.__name__):
            await sched._launch_periodic("sweep")
            await asyncio.sleep(0.01)
            await sched._launch_periodic("sweep")
            await asyncio.sleep(0.01)
        assert runs == 1
        assert any("ещё выполняется" in r.getMessage() for r in caplog.records)
        release.set()
        await asyncio.sleep(0.01)
        await sched._launch_periodic("sweep")
        await asyncio.sleep(0.01)
        assert runs == 2
    finally:
        await sched.stop()


async def test_stop_drops_pending_and_waits_for_running(registry: TaskRegistry) -> None:
    finished = asyncio.Event()
    started = asyncio.Event()
    ran_later: list[int] = []

    @registry.task("short")
    async def short(payload: dict[str, Any]) -> None:
        started.set()
        await asyncio.sleep(0.05)
        finished.set()

    @registry.task("later")
    async def later(payload: dict[str, Any]) -> None:
        ran_later.append(1)

    sched = InProcessTaskScheduler(registry, shutdown_timeout=2)
    await sched.start()
    await sched.enqueue("later", delay=timedelta(milliseconds=200))
    await sched.enqueue("short")
    await asyncio.wait_for(started.wait(), timeout=2)
    await sched.stop()
    assert finished.is_set()  # выполнявшийся обработчик дождались
    assert sched._tasks == set() and sched._pending == set() and sched._running == set()
    await asyncio.sleep(0.3)
    assert ran_later == []  # отложенная задача потеряна при остановке (ADR-1)
    with pytest.raises(RuntimeError, match="не запущен"):
        await sched.enqueue("later")


async def test_stop_cancels_handlers_exceeding_timeout(
    registry: TaskRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    @registry.task("hang")
    async def hang(payload: dict[str, Any]) -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    sched = InProcessTaskScheduler(registry, shutdown_timeout=0.05)
    await sched.start()
    await sched.enqueue("hang")
    await asyncio.wait_for(started.wait(), timeout=2)
    with caplog.at_level(logging.WARNING, logger=single_scheduler.__name__):
        await asyncio.wait_for(sched.stop(), timeout=2)  # остановка не зависает
    assert cancelled.is_set()
    assert sched._tasks == set()
    assert any("отменены" in r.getMessage() for r in caplog.records)
    assert [t for t in asyncio.all_tasks() if t.get_name().startswith("task:hang")] == []


async def test_start_is_idempotent_and_restart_after_stop(registry: TaskRegistry, recorder: Recorder) -> None:
    sched = InProcessTaskScheduler(registry)
    await sched.stop()  # stop до start — no-op
    await sched.start()
    first = sched._scheduler
    await sched.start()
    assert sched._scheduler is first and sched.running
    await sched.stop()
    assert not sched.running
    await sched.start()
    await sched.enqueue("demo")
    await asyncio.wait_for(recorder.called.wait(), timeout=2)
    await sched.stop()


def test_shutdown_timeout_must_be_non_negative(registry: TaskRegistry) -> None:
    with pytest.raises(ValueError, match="shutdown_timeout"):
        InProcessTaskScheduler(registry, shutdown_timeout=-1)
