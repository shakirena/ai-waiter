"""TaskScheduler на arq (режим scaled). Контракт — ``app/core/scheduler.py``.

В api-процессах работает только как издатель (enqueue/cancel); задачи и периодические
задания выполняет отдельный процесс ``arq app.core.scaled.worker.WorkerSettings``.
"""

from __future__ import annotations

from datetime import timedelta

from arq.connections import ArqRedis
from arq.constants import in_progress_key_prefix, job_key_prefix
from redis.exceptions import WatchError

from app.core.scaled.connection import ArqRedisFactory, arq_redis_from_url
from app.core.scheduler import TaskPayload, TaskRegistry, TaskScheduler, validate_delay, validate_task


class ArqTaskScheduler(TaskScheduler):
    """Постановка задач в очередь arq в Redis."""

    def __init__(
        self,
        redis_url: str,
        registry: TaskRegistry,
        *,
        pool_factory: ArqRedisFactory = arq_redis_from_url,
    ) -> None:
        self._redis_url = redis_url
        self._registry = registry  # для проверки имени задачи до постановки в очередь
        self._pool_factory = pool_factory
        self._pool: ArqRedis | None = None

    async def start(self) -> None:
        """Создать клиента arq. Соединение откроется при первой постановке задачи."""
        if self._pool is None:
            self._pool = self._pool_factory(self._redis_url)

    async def stop(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.aclose(close_connection_pool=True)

    async def enqueue(
        self,
        name: str,
        payload: TaskPayload | None = None,
        *,
        delay: timedelta | None = None,
        job_id: str | None = None,
    ) -> str:
        """``enqueue_job(name, payload, _job_id=job_id, _defer_by=delay)``.

        Если задача с таким ``job_id`` уже стоит в очереди или выполняется, arq не создаёт
        вторую — возвращается тот же ``job_id``."""
        checked = validate_task(self._registry, name, payload)
        validate_delay(delay)
        if job_id is not None and (not isinstance(job_id, str) or not job_id):
            raise ValueError("job_id должен быть непустой строкой")
        job = await self._require_pool().enqueue_job(name, checked, _job_id=job_id, _defer_by=delay)
        if job is None:
            # Дубликат по job_id: arq вернул None, только когда job_id задан явно.
            return str(job_id)
        return job.job_id

    async def cancel(self, job_id: str) -> bool:
        """Убрать ещё не начатую задачу из очереди.

        Под WATCH проверяется, что worker не взял задачу; если взял (или успел взять за
        время проверки) — ``False``. Worker перед запуском сверяется с очередью, поэтому
        удалённая отсюда задача не выполнится."""
        pool = self._require_pool()
        job_key = job_key_prefix + job_id
        in_progress_key = in_progress_key_prefix + job_id
        try:
            async with pool.pipeline(transaction=True) as pipe:
                await pipe.watch(in_progress_key, job_key)
                if await pipe.exists(in_progress_key):
                    return False
                pipe.multi()
                pipe.zrem(pool.default_queue_name, job_id)
                pipe.delete(job_key)
                removed, _ = await pipe.execute()
        except WatchError:
            return False
        return bool(removed)

    def _require_pool(self) -> ArqRedis:
        if self._pool is None:
            raise RuntimeError("ArqTaskScheduler не запущен: сначала вызовите start()")
        return self._pool
