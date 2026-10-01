"""Container и build_container (#38, AC-2): выбор реализации по APP_MODE, ленивый импорт,
порядок запуска/остановки, терпимость к ошибкам запуска и остановки."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import ConfigError, Settings
from app.core.container import build_container, start_container, stop_container
from app.core.scheduler import TaskRegistry
from tests.conftest import make_settings
from tests.doubles import FakeEventBus, FakeRateLimiter, FakeTaskScheduler, make_fake_container

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCALED_SETTINGS = {"app_mode": "scaled", "redis_url": "redis://redis:6379/0"}


def _forget_modules(monkeypatch: pytest.MonkeyPatch, package: str) -> None:
    """Убрать пакет реализаций из sys.modules (monkeypatch вернёт их после теста), чтобы проверка
    «не импортирован» не зависела от порядка тестов."""
    for name in [name for name in sys.modules if name == package or name.startswith(f"{package}.")]:
        monkeypatch.delitem(sys.modules, name)


def test_single_mode_uses_in_memory_implementations(settings: Settings, registry: TaskRegistry) -> None:
    from app.core.single.events import InMemoryEventBus
    from app.core.single.ratelimit import InMemoryRateLimiter
    from app.core.single.scheduler import InProcessTaskScheduler

    c = build_container(settings, registry)
    assert c.settings is settings
    assert type(c.event_bus) is InMemoryEventBus
    assert type(c.scheduler) is InProcessTaskScheduler
    assert type(c.rate_limiter) is InMemoryRateLimiter


def test_single_mode_does_not_import_scaled_backends(
    settings: Settings, registry: TaskRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forget_modules(monkeypatch, "app.core.scaled")
    build_container(settings, registry)
    assert "app.core.scaled.events" not in sys.modules
    assert "app.core.scaled.scheduler" not in sys.modules
    assert "app.core.scaled.ratelimit" not in sys.modules


def test_scaled_mode_uses_redis_implementations(registry: TaskRegistry) -> None:
    from app.core.scaled.events import RedisEventBus
    from app.core.scaled.ratelimit import RedisRateLimiter
    from app.core.scaled.scheduler import ArqTaskScheduler

    c = build_container(make_settings(**SCALED_SETTINGS), registry)
    assert type(c.event_bus) is RedisEventBus
    assert type(c.scheduler) is ArqTaskScheduler
    assert type(c.rate_limiter) is RedisRateLimiter


def test_scaled_mode_does_not_import_single_backends(registry: TaskRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    _forget_modules(monkeypatch, "app.core.single")
    build_container(make_settings(**SCALED_SETTINGS), registry)
    assert not [name for name in sys.modules if name.startswith("app.core.single")]


def test_build_container_does_not_connect_anywhere(registry: TaskRegistry) -> None:
    """Сборка только создаёт объекты: scaled с недоступным адресом Redis собирается без ошибок."""
    build_container(make_settings(app_mode="scaled", redis_url="redis://unreachable.invalid:6379/0"), registry)


def test_unknown_mode_is_startup_error(settings: Settings, registry: TaskRegistry) -> None:
    bogus = settings.model_copy(update={"app_mode": "bogus"})
    with pytest.raises(ConfigError, match="APP_MODE: неизвестный режим 'bogus'"):
        build_container(bogus, registry)


def test_scaled_without_redis_url_is_startup_error(registry: TaskRegistry) -> None:
    broken = make_settings(**SCALED_SETTINGS).model_copy(update={"redis_url": None})
    with pytest.raises(ConfigError, match="REDIS_URL обязателен"):
        build_container(broken, registry)


@pytest.mark.parametrize(
    ("mode_env", "forbidden"),
    [
        ({"APP_MODE": "single"}, ("redis", "arq", "app.core.scaled")),
        ({"APP_MODE": "scaled", "REDIS_URL": "redis://redis:6379/0"}, ("apscheduler", "app.core.single")),
    ],
)
def test_lazy_import_in_clean_process(mode_env: dict[str, str], forbidden: tuple[str, ...], tmp_path: Path) -> None:
    """В чистом процессе: сборка Container одного режима не импортирует библиотеки другого."""
    code = (
        "import sys\n"
        "from app.core.config import Settings\n"
        "from app.core.container import build_container\n"
        "from app.core.scheduler import TaskRegistry\n"
        "build_container(Settings(_env_file=None, serve_frontend=False), TaskRegistry())\n"
        f"bad = [m for m in sys.modules if m.split('.')[0] in {forbidden!r} or m.startswith({forbidden!r})]\n"
        "assert not bad, bad\n"
    )
    env = {key: value for key, value in os.environ.items() if key.upper() not in {"APP_MODE", "REDIS_URL"}}
    env.update(mode_env)
    env["PYTHONPATH"] = str(BACKEND_DIR)
    result = subprocess.run(  # noqa: S603 — фиксированная команда, без shell
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


async def test_start_and_stop_order(settings: Settings) -> None:
    calls: list[str] = []
    c = make_fake_container(settings, calls)
    await start_container(c)
    await stop_container(c)
    assert calls == [
        "event_bus.start",
        "rate_limiter.start",
        "scheduler.start",
        "scheduler.stop",
        "rate_limiter.stop",
        "event_bus.stop",
    ]


async def test_start_failure_is_logged_and_others_still_start(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """Redis недоступен при старте: процесс не падает, остальные компоненты запускаются."""
    calls: list[str] = []
    bus = FakeEventBus(calls, start_error=ConnectionError("redis down"))
    c = make_fake_container(settings, calls, bus=bus)
    with caplog.at_level(logging.ERROR, logger="app.core.container"):
        await start_container(c)
    assert calls == ["event_bus.start", "rate_limiter.start", "scheduler.start"]
    assert [getattr(r, "component", None) for r in caplog.records] == ["event_bus"]


async def test_stop_failure_does_not_prevent_stopping_others(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []
    scheduler = FakeTaskScheduler(TaskRegistry(), calls, stop_error=RuntimeError("boom"))
    limiter = FakeRateLimiter(calls, stop_error=OSError("closed"))
    c = make_fake_container(settings, calls, scheduler=scheduler, rate_limiter=limiter)
    with caplog.at_level(logging.ERROR, logger="app.core.container"):
        await stop_container(c)
    assert calls == ["scheduler.stop", "rate_limiter.stop", "event_bus.stop"]
    assert [getattr(r, "component", None) for r in caplog.records] == ["scheduler", "rate_limiter"]


def test_container_is_immutable(settings: Settings) -> None:
    c = make_fake_container(settings)
    with pytest.raises(AttributeError):
        c.event_bus = FakeEventBus()  # type: ignore[misc]
