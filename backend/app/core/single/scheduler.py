"""TaskScheduler для режима single: APScheduler 3.x внутри процесса. Контракт — app/core/scheduler.py.

Импорт apscheduler разрешён только в этом пакете (ruff TID251, ADR-1).

APScheduler отвечает только за время запуска: его задача — короткий «запускатель», который
создаёт собственную asyncio-задачу обработчика. Поэтому состояние задач (ожидает / выполняется)
ведётся здесь, а не в хранилище APScheduler: ``job_id``-дедупликация и ``cancel`` не зависят от
момента, когда APScheduler удаляет сработавшую задачу, а ``stop`` дожидается или отменяет
обработчики сам.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from apscheduler.events import EVENT_SCHEDULER_SHUTDOWN
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.scheduler import TaskPayload, TaskRegistry, TaskScheduler, validate_delay, validate_task

logger = logging.getLogger(__name__)

DEFAULT_SHUTDOWN_TIMEOUT = 5.0
_ONE_OFF_PREFIX = "task:"
_PERIODIC_PREFIX = "periodic:"


class InProcessTaskScheduler(TaskScheduler):
    """Режим single: ``apscheduler.schedulers.asyncio.AsyncIOScheduler`` с in-memory jobstore.

    Выполняет и разовые задачи из ``enqueue``, и периодические задачи реестра.
    Исключения обработчиков логируются и не роняют планировщик. Периодическая задача не
    запускается повторно, пока не завершился её предыдущий запуск.

    ``stop`` ждёт выполняющиеся обработчики не дольше ``shutdown_timeout`` секунд, затем отменяет
    их; отложенные задачи, которые ещё не начались, теряются (ADR-1)."""

    def __init__(self, registry: TaskRegistry, *, shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
        if shutdown_timeout < 0:
            raise ValueError("shutdown_timeout не может быть отрицательным")
        self._registry = registry
        self._shutdown_timeout = shutdown_timeout
        self._scheduler: AsyncIOScheduler | None = None
        self._pending: set[str] = set()
        self._running: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def running(self) -> bool:
        return self._scheduler is not None

    async def start(self) -> None:
        """Запустить APScheduler в текущем event loop и поставить периодические задачи реестра."""
        if self._scheduler is not None:
            return
        scheduler = AsyncIOScheduler(
            event_loop=asyncio.get_running_loop(),
            timezone=UTC,
            # Задача, опоздавшая из-за занятого event loop, всё равно выполняется (а не пропускается),
            # пропущенные запуски периодической задачи сливаются в один.
            job_defaults={"misfire_grace_time": None, "coalesce": True, "max_instances": 1},
        )
        for periodic in self._registry.periodic_tasks:
            scheduler.add_job(
                self._launch_periodic,
                trigger=IntervalTrigger(minutes=periodic.every_minutes, timezone=UTC),
                args=[periodic.name],
                id=_PERIODIC_PREFIX + periodic.name,
                name=periodic.name,
            )
        scheduler.start()
        self._scheduler = scheduler
        logger.info("Планировщик задач запущен", extra={"periodic_tasks": len(self._registry.periodic_tasks)})

    async def stop(self) -> None:
        """Остановить APScheduler, дождаться обработчиков (не дольше ``shutdown_timeout``), остальные отменить."""
        scheduler = self._scheduler
        if scheduler is None:
            return
        self._scheduler = None
        self._pending.clear()
        # AsyncIOScheduler выполняет shutdown через call_soon — ждём события о завершении остановки.
        shut_down = asyncio.Event()
        scheduler.add_listener(lambda _event: shut_down.set(), EVENT_SCHEDULER_SHUTDOWN)
        scheduler.shutdown(wait=False)
        await shut_down.wait()

        tasks = set(self._tasks)
        if tasks:
            _, still_running = await asyncio.wait(tasks, timeout=self._shutdown_timeout)
            if still_running:
                logger.warning(
                    "Обработчики задач не завершились за отведённое время и отменены",
                    extra={"cancelled": len(still_running), "timeout": self._shutdown_timeout},
                )
                for task in still_running:
                    task.cancel()
                await asyncio.gather(*still_running, return_exceptions=True)
        logger.info("Планировщик задач остановлен")

    async def enqueue(
        self,
        name: str,
        payload: TaskPayload | None = None,
        *,
        delay: timedelta | None = None,
        job_id: str | None = None,
    ) -> str:
        payload = validate_task(self._registry, name, payload)
        validate_delay(delay)
        if job_id is not None and (not isinstance(job_id, str) or not job_id):
            raise ValueError("job_id должен быть непустой строкой")
        scheduler = self._scheduler
        if scheduler is None:
            raise RuntimeError("планировщик задач не запущен")

        if job_id is None:
            job_id = uuid.uuid4().hex
        elif job_id in self._pending or _ONE_OFF_PREFIX + job_id in self._running:
            return job_id

        # Копия через JSON — как в scaled: изменения словаря после enqueue не влияют на задачу.
        payload_copy = json.loads(json.dumps(payload))
        run_date = datetime.now(UTC) + (delay or timedelta(0))
        self._pending.add(job_id)
        scheduler.add_job(
            self._launch_one_off,
            trigger=DateTrigger(run_date=run_date, timezone=UTC),
            args=[job_id, name, payload_copy],
            id=_ONE_OFF_PREFIX + job_id,
            name=name,
        )
        return job_id

    async def cancel(self, job_id: str) -> bool:
        if job_id not in self._pending:
            return False
        self._pending.discard(job_id)
        if self._scheduler is not None:
            try:
                self._scheduler.remove_job(_ONE_OFF_PREFIX + job_id)
            except JobLookupError:
                # APScheduler уже передал задачу исполнителю; запускатель увидит отмену и не запустит её.
                pass
        return True

    async def _launch_one_off(self, job_id: str, name: str, payload: TaskPayload) -> None:
        if job_id not in self._pending:
            return
        self._pending.discard(job_id)
        self._spawn(_ONE_OFF_PREFIX + job_id, name, payload)

    async def _launch_periodic(self, name: str) -> None:
        run_id = _PERIODIC_PREFIX + name
        if run_id in self._running:
            logger.warning("Предыдущий запуск периодической задачи ещё выполняется — пропуск", extra={"task": name})
            return
        self._spawn(run_id, name, {})

    def _spawn(self, run_id: str, name: str, payload: TaskPayload) -> None:
        self._running.add(run_id)
        task = asyncio.get_running_loop().create_task(self._execute(name, payload), name=f"task:{name}:{run_id}")
        self._tasks.add(task)

        def _done(finished: asyncio.Task[None]) -> None:
            self._tasks.discard(finished)
            self._running.discard(run_id)

        task.add_done_callback(_done)

    async def _execute(self, name: str, payload: TaskPayload) -> None:
        try:
            handler = self._registry.get(name)
            await handler(payload)
        except Exception:
            logger.exception("Ошибка выполнения фоновой задачи", extra={"task": name})
