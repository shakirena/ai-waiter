"""arq worker (#40, spec AC-4): WorkerSettings из реестра, cron из every_minutes, ленивая сборка
при импорте и выполнение поставленной задачи worker-ом (fakeredis, без настоящего Redis)."""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from arq import worker as arq_worker
from arq.connections import RedisSettings
from arq.constants import default_queue_name
from arq.worker import Worker, create_worker
from fakeredis import FakeServer

from app.core.config import AppMode, ConfigError
from app.core.scaled import worker as worker_module
from app.core.scaled.connection import deserialize_job, serialize_job
from app.core.scaled.scheduler import ArqTaskScheduler
from app.core.scaled.worker import (
    CRON_NAME_PREFIX,
    NOOP_FUNCTION_NAME,
    build_cron_jobs,
    build_functions,
    build_worker_settings,
    cron_schedule,
)
from app.core.scheduler import TaskPayload, TaskRegistry
from tests.conftest import make_settings
from tests.fake_redis import arq_factory

REDIS_URL = "redis://:s3cret@redis:6379/2"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _scaled_settings(**overrides: Any) -> Any:
    values: dict[str, Any] = {"app_mode": AppMode.SCALED, "redis_url": REDIS_URL, **overrides}
    return make_settings(**values)


def _registry(calls: list[tuple[str, TaskPayload]]) -> TaskRegistry:
    registry = TaskRegistry()

    @registry.task("orders.notify")
    async def notify(payload: TaskPayload) -> None:
        calls.append(("orders.notify", payload))

    @registry.periodic("escalations.sweep", every_minutes=5)
    async def sweep(payload: TaskPayload) -> None:
        calls.append(("escalations.sweep", payload))

    @registry.periodic("cleanup.daily", every_minutes=1440)
    async def cleanup(payload: TaskPayload) -> None:
        calls.append(("cleanup.daily", payload))

    return registry


@pytest.mark.parametrize(
    ("every_minutes", "hour", "minute"),
    [
        (1, None, set(range(60))),
        (5, None, {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        (15, None, {0, 15, 30, 45}),
        (30, None, {0, 30}),
        (60, None, {0}),
        (120, set(range(0, 24, 2)), {0}),
        (180, {0, 3, 6, 9, 12, 15, 18, 21}, {0}),
        (360, {0, 6, 12, 18}, {0}),
        (720, {0, 12}, {0}),
        (1440, {0}, {0}),
    ],
)
def test_cron_schedule(every_minutes: int, hour: set[int] | None, minute: set[int]) -> None:
    assert cron_schedule(every_minutes) == (hour, minute)


def test_functions_built_from_registry() -> None:
    functions = build_functions(_registry([]))
    names = [f.name for f in functions]
    # Периодические задачи тоже можно поставить вручную, как и в single.
    assert names == ["orders.notify", "escalations.sweep", "cleanup.daily", NOOP_FUNCTION_NAME]


def test_empty_registry_still_has_noop_function() -> None:
    assert [f.name for f in build_functions(TaskRegistry())] == [NOOP_FUNCTION_NAME]
    assert build_cron_jobs(TaskRegistry()) == []


def test_cron_jobs_built_from_periodic_tasks() -> None:
    jobs = {job.name: job for job in build_cron_jobs(_registry([]))}
    assert set(jobs) == {CRON_NAME_PREFIX + "escalations.sweep", CRON_NAME_PREFIX + "cleanup.daily"}
    sweep = jobs[CRON_NAME_PREFIX + "escalations.sweep"]
    assert sweep.minute == set(range(0, 60, 5))
    assert sweep.hour is None
    assert sweep.unique is True
    assert sweep.run_at_startup is False
    daily = jobs[CRON_NAME_PREFIX + "cleanup.daily"]
    assert (daily.hour, daily.minute) == ({0}, {0})


async def test_wrapped_functions_call_handlers() -> None:
    calls: list[tuple[str, TaskPayload]] = []
    registry = _registry(calls)
    functions = {f.name: f for f in build_functions(registry)}
    await functions["orders.notify"].coroutine({}, {"order_id": 1})
    await functions["orders.notify"].coroutine({})
    await functions[NOOP_FUNCTION_NAME].coroutine({})
    for job in build_cron_jobs(registry):
        await job.coroutine({})
    assert calls == [
        ("orders.notify", {"order_id": 1}),
        ("orders.notify", {}),
        ("escalations.sweep", {}),
        ("cleanup.daily", {}),
    ]


async def test_wrapped_function_rejects_non_json_payload() -> None:
    functions = {f.name: f for f in build_functions(_registry([]))}
    with pytest.raises(TypeError):
        await functions["orders.notify"].coroutine({}, ["not", "a", "dict"])


def test_worker_settings_attributes_are_in_class_dict() -> None:
    """arq читает настройки через ``settings_cls.__dict__`` — наследованные атрибуты не видны."""
    settings_cls = build_worker_settings(_scaled_settings(), _registry([]))
    attrs = vars(settings_cls)
    for name in (
        "functions",
        "cron_jobs",
        "redis_settings",
        "job_serializer",
        "job_deserializer",
        "on_startup",
        "on_shutdown",
        "ctx",
        "max_tries",
        "job_timeout",
        "keep_result",
        "health_check_interval",
    ):
        assert name in attrs
    redis_settings: RedisSettings = attrs["redis_settings"]
    assert (redis_settings.host, redis_settings.port, redis_settings.database) == ("redis", 6379, 2)
    assert attrs["keep_result"] == 0
    assert attrs["job_timeout"] == timedelta(minutes=5)
    assert attrs["health_check_interval"] == timedelta(seconds=60)
    assert attrs["job_serializer"] is serialize_job
    assert attrs["job_deserializer"] is deserialize_job
    worker = create_worker(settings_cls, handle_signals=False)
    assert isinstance(worker, Worker)
    assert set(worker.functions) == {
        "orders.notify",
        "escalations.sweep",
        "cleanup.daily",
        NOOP_FUNCTION_NAME,
        CRON_NAME_PREFIX + "escalations.sweep",
        CRON_NAME_PREFIX + "cleanup.daily",
    }


def test_worker_requires_scaled_mode() -> None:
    with pytest.raises(ConfigError, match="APP_MODE=scaled"):
        build_worker_settings(make_settings(), TaskRegistry())


def test_worker_requires_redis_url() -> None:
    settings = _scaled_settings().model_copy(update={"redis_url": None})
    with pytest.raises(ConfigError, match="REDIS_URL обязателен"):
        build_worker_settings(settings, TaskRegistry())


@pytest.mark.parametrize("url", ["http://redis:6379/0", "redis://redis:6379/abc"])
def test_worker_invalid_redis_url_hides_value(url: str) -> None:
    settings = _scaled_settings(redis_url=url)
    with pytest.raises(ConfigError, match="некорректный адрес") as exc_info:
        build_worker_settings(settings, TaskRegistry())
    assert "redis:6379" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_module_getattr_builds_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[tuple[Any, Any]] = []
    monkeypatch.setattr(worker_module, "build_worker_settings", lambda s, r: built.append((s, r)) or "settings")
    monkeypatch.setattr("app.core.config.get_settings", lambda: "env-settings")
    from app.tasks import registry

    assert worker_module.WorkerSettings == "settings"
    assert built == [("env-settings", registry)]
    with pytest.raises(AttributeError, match="не содержит атрибута"):
        _ = worker_module.Missing


def test_import_has_no_side_effects() -> None:
    """Импорт модуля без REDIS_URL проходит; WorkerSettings без конфигурации — понятная ошибка."""
    importlib.reload(worker_module)
    code = (
        "import app.core.scaled.worker as w\n"
        "try:\n"
        "    w.WorkerSettings\n"
        "except Exception as exc:\n"
        "    print(type(exc).__name__, exc)\n"
    )
    env = {key: value for key, value in __import__("os").environ.items() if key not in {"APP_MODE", "REDIS_URL"}}
    result = subprocess.run(  # noqa: S603 — фиксированная команда текущего интерпретатора
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR / "tests",  # каталог без .env
        env={**env, "PYTHONPATH": str(BACKEND_DIR), "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    assert result.stdout.startswith("ConfigError")
    assert "APP_MODE=scaled" in result.stdout


async def test_on_startup_configures_logging(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    configured: list[Any] = []
    monkeypatch.setattr(worker_module, "configure_logging", configured.append)
    settings = _scaled_settings()
    caplog.set_level(logging.INFO, logger=worker_module.__name__)
    await worker_module.on_startup({"settings": settings})
    await worker_module.on_shutdown({})
    assert configured == [settings]
    messages = [r.getMessage() for r in caplog.records]
    assert "arq worker запущен" in messages
    assert "arq worker остановлен" in messages
    assert all("s3cret" not in m for m in messages)


async def test_enqueued_task_is_processed_by_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-4: задача, поставленная api-процессом, попадает в очередь arq и выполняется worker-ом."""
    monkeypatch.setattr(worker_module, "configure_logging", lambda settings: None)

    async def no_redis_info(redis: Any, log_func: Any) -> None:
        """fakeredis не поддерживает INFO, которым arq только логирует версию Redis при старте."""

    monkeypatch.setattr(arq_worker, "log_redis_info", no_redis_info)
    server = FakeServer()
    calls: list[tuple[str, TaskPayload]] = []
    registry = _registry(calls)
    scheduler = ArqTaskScheduler(REDIS_URL, registry, pool_factory=arq_factory(server))
    await scheduler.start()
    await scheduler.enqueue("orders.notify", {"order_id": 42}, job_id="order-42")
    cancelled = await scheduler.enqueue("orders.notify", {"order_id": 43}, job_id="order-43")
    assert await scheduler.cancel(cancelled) is True

    settings_cls = build_worker_settings(_scaled_settings(), registry)
    worker_pool = arq_factory(server)(REDIS_URL)
    worker = create_worker(settings_cls, redis_pool=worker_pool, burst=True, handle_signals=False, poll_delay=0.01)
    try:
        await worker.main()
    finally:
        # Worker.close() шлёт SIGUSR1, которого нет на Windows; worker в проде работает в Linux-контейнере.
        await worker_pool.aclose(close_connection_pool=True)

    assert calls == [("orders.notify", {"order_id": 42})]
    assert (worker.jobs_complete, worker.jobs_failed) == (1, 0)
    check_pool = arq_factory(server)(REDIS_URL)
    assert await check_pool.zcard(default_queue_name) == 0
    # Результат не хранится: тот же job_id можно поставить снова.
    assert await scheduler.enqueue("orders.notify", job_id="order-42") == "order-42"
    assert await check_pool.zcard(default_queue_name) == 1
    await check_pool.aclose(close_connection_pool=True)
    await scheduler.stop()
