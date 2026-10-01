"""TaskScheduler для режима single: APScheduler 3.x внутри процесса. Контракт — app/core/scheduler.py.

Импорт apscheduler разрешён только в этом пакете (ruff TID251, ADR-1).
"""

from __future__ import annotations

from datetime import timedelta

from app.core.scheduler import TaskPayload, TaskRegistry, TaskScheduler


class InProcessTaskScheduler(TaskScheduler):
    """Режим single: ``apscheduler.schedulers.asyncio.AsyncIOScheduler`` с in-memory jobstore.

    Выполняет и разовые задачи из ``enqueue``, и периодические задачи реестра.
    Исключения обработчиков логируются и не роняют планировщик.
    """

    def __init__(self, registry: TaskRegistry) -> None:
        self._registry = registry

    async def start(self) -> None:
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
        raise NotImplementedError

    async def cancel(self, job_id: str) -> bool:
        raise NotImplementedError
