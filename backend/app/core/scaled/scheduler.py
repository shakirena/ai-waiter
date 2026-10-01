"""TaskScheduler на arq (режим scaled). Заготовка; реализуется в #23/#36.

В api-процессах работает только как издатель (enqueue/cancel); задачи и периодические
задания выполняет отдельный процесс ``arq app.core.scaled.worker.WorkerSettings``.
"""

from __future__ import annotations

from datetime import timedelta

from app.core.scheduler import TaskPayload, TaskRegistry, TaskScheduler


class ArqTaskScheduler(TaskScheduler):
    def __init__(self, redis_url: str, registry: TaskRegistry) -> None:
        self._redis_url = redis_url
        self._registry = registry  # для проверки имени задачи до постановки в очередь

    async def start(self) -> None:
        """Создать ``ArqRedis`` пул (``arq.create_pool``)."""
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def enqueue(
        self,
        name: str,
        payload: TaskPayload | None = None,
        *,
        delay: timedelta | None = None,
        job_id: str | None = None,
    ) -> str:
        """``enqueue_job(name, payload, _job_id=job_id, _defer_by=delay)``;
        та же проверка имени и payload, что в single."""
        raise NotImplementedError

    async def cancel(self, job_id: str) -> bool:
        raise NotImplementedError
