"""Lifespan и зависимости FastAPI (#38): Container создаётся при старте, кладётся в app.state,
останавливается при выходе; эндпоинты получают компоненты через app/api/deps.py."""

from __future__ import annotations

import logging
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

import app.api.demo_data as demo_data_module
import app.api.health as health_module
import app.main as main_module
from app.api import deps
from app.api.demo_data import DemoDataMonitor, DemoDataState
from app.core.config import ConfigError, Settings
from app.core.container import Container
from app.core.events import EventBus
from app.core.ratelimit import RateLimiter
from app.core.scheduler import TaskRegistry, TaskScheduler
from app.db.session import Database
from app.main import create_app
from tests.conftest import make_settings
from tests.doubles import FakeDatabase, FakeEventBus, make_fake_container


async def test_lifespan_builds_starts_and_stops_container(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    built: list[tuple[Settings, TaskRegistry]] = []
    settings = make_settings()
    registry = TaskRegistry()
    container = make_fake_container(settings, calls)

    def fake_build(s: Settings, r: TaskRegistry) -> Container:
        built.append((s, r))
        return container

    monkeypatch.setattr(main_module, "build_container", fake_build)
    application = create_app(settings, registry=registry)
    async with application.router.lifespan_context(application):
        assert application.state.container is container
        assert calls == ["database.start", "event_bus.start", "rate_limiter.start", "scheduler.start"]
    assert built == [(settings, registry)]
    assert calls[4:] == ["scheduler.stop", "rate_limiter.stop", "event_bus.stop", "database.stop"]


async def test_lifespan_unknown_mode_fails_startup() -> None:
    settings = make_settings().model_copy(update={"app_mode": "bogus"})
    application = create_app(settings, registry=TaskRegistry())
    with pytest.raises(ConfigError, match="неизвестный режим"):
        async with application.router.lifespan_context(application):
            pytest.fail("приложение не должно стартовать")


async def test_lifespan_survives_component_start_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    bus = FakeEventBus(calls, start_error=ConnectionError("redis down"))
    monkeypatch.setattr(main_module, "build_container", lambda s, r: make_fake_container(s, calls, bus=bus))
    application = create_app(make_settings(), registry=TaskRegistry())
    async with application.router.lifespan_context(application):
        assert application.state.container.event_bus is bus
    assert "event_bus.stop" in calls


def _probe_app(container: Container) -> FastAPI:
    """Приложение с эндпоинтом, который получает все компоненты через deps."""
    application = FastAPI()
    application.state.container = container
    application.state.settings = container.settings

    @application.get("/probe")
    async def probe(
        c: Annotated[Container, Depends(deps.get_container)],
        settings: Annotated[Settings, Depends(deps.get_app_settings)],
        bus: Annotated[EventBus, Depends(deps.get_event_bus)],
        scheduler: Annotated[TaskScheduler, Depends(deps.get_scheduler)],
        limiter: Annotated[RateLimiter, Depends(deps.get_rate_limiter)],
        database: Annotated[Database, Depends(deps.get_database)],
    ) -> dict[str, bool]:
        return {
            "container": c is container,
            "database": database is container.database,
            "settings": settings is container.settings,
            "bus": bus is container.event_bus,
            "scheduler": scheduler is container.scheduler,
            "limiter": limiter is container.rate_limiter,
        }

    return application


async def test_deps_return_container_components() -> None:
    application = _probe_app(make_fake_container(make_settings()))
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as ac:
        r = await ac.get("/probe")
    assert r.status_code == 200
    assert all(r.json().values()), r.json()


async def test_session_dep_opens_and_closes_session_without_commit() -> None:
    """SessionDep (ADR-7.9): одна сессия на запрос, закрывается после ответа, автокоммита нет."""
    database = FakeDatabase()
    application = _probe_app(make_fake_container(make_settings(), database=database))

    @application.get("/session")
    async def session_probe(session: deps.SessionDep) -> dict[str, bool]:
        return {"open": not session.closed}  # type: ignore[attr-defined]

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as ac:
        r = await ac.get("/session")
    assert r.json() == {"open": True}
    assert len(database.sessions) == 1
    assert database.sessions[0].closed is True


async def test_get_container_before_lifespan_is_error() -> None:
    application = FastAPI()

    @application.get("/probe")
    async def probe(c: Annotated[Container, Depends(deps.get_container)]) -> dict[str, str]:
        return {}

    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=True), base_url="http://testserver"
    ) as ac:
        with pytest.raises(RuntimeError, match="Container не создан"):
            await ac.get("/probe")


async def test_app_settings_fall_back_to_state_before_lifespan() -> None:
    """Liveness /health не зависит от Container: до lifespan настройки берутся из app.state.settings."""
    settings = make_settings(app_mode="scaled", redis_url="redis://redis:6379/0")
    application = create_app(settings, registry=TaskRegistry())
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["mode"] == "scaled"


# ---------------------------------------------------------------- #71: DemoDataMonitor в create_app и lifespan

PROD = {"app_env": "prod", "public_base_url": "https://menu.example.com"}


class _MonitorSpy(DemoDataMonitor):
    """Записывает вызовы ``refresh`` (базу, с которой вызван) и делегирует настоящему методу."""

    def __init__(self) -> None:
        super().__init__(2.0)
        self.refreshed: list[object] = []

    async def refresh(self, database: Database) -> DemoDataState:
        self.refreshed.append(database)
        return await super().refresh(database)


def _spy_app(monkeypatch: pytest.MonkeyPatch, settings: Settings, container: Container) -> tuple[FastAPI, _MonitorSpy]:
    monkeypatch.setattr(main_module, "build_container", lambda s, r: container)
    application = create_app(settings, registry=TaskRegistry())
    spy = _MonitorSpy()
    application.state.demo_data_monitor = spy
    return application, spy


def test_create_app_creates_demo_data_monitor() -> None:
    application = create_app(make_settings(), registry=TaskRegistry())
    monitor = application.state.demo_data_monitor
    assert isinstance(monitor, DemoDataMonitor)
    assert monitor.state is None
    assert monitor._check_timeout == health_module.READINESS_CHECK_TIMEOUT


def test_get_demo_data_monitor_returns_state_object() -> None:
    application = create_app(make_settings(), registry=TaskRegistry())
    request = Request({"type": "http", "app": application})
    assert deps.get_demo_data_monitor(request) is application.state.demo_data_monitor


async def test_lifespan_in_prod_refreshes_once_with_container_database(monkeypatch: pytest.MonkeyPatch) -> None:
    async def found(session: object) -> bool:
        return True

    monkeypatch.setattr(demo_data_module, "demo_tenant_exists", found)
    settings = make_settings(**PROD)
    container = make_fake_container(settings)
    application, spy = _spy_app(monkeypatch, settings, container)
    async with application.router.lifespan_context(application):
        assert spy.refreshed == [container.database]
        assert spy.state is DemoDataState.FOUND


async def test_lifespan_in_prod_survives_failed_check(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """БД недоступна при старте в prod: старт не прерывается, состояние ``UNKNOWN``, liveness 200."""

    async def broken(session: object) -> bool:
        raise ConnectionRefusedError("db down")

    monkeypatch.setattr(demo_data_module, "demo_tenant_exists", broken)
    settings = make_settings(**PROD)
    application, spy = _spy_app(monkeypatch, settings, make_fake_container(settings))
    with caplog.at_level(logging.WARNING, logger="app.api.demo_data"):
        async with application.router.lifespan_context(application):
            assert spy.state is DemoDataState.UNKNOWN
            async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as ac:
                assert (await ac.get("/health")).status_code == 200
    assert len(spy.refreshed) == 1
    assert [rec.levelno for rec in caplog.records if rec.name == "app.api.demo_data"] == [logging.WARNING]


@pytest.mark.parametrize("app_env", ["dev", "test"])
async def test_lifespan_outside_prod_does_not_refresh(monkeypatch: pytest.MonkeyPatch, app_env: str) -> None:
    settings = make_settings(app_env=app_env)
    application, spy = _spy_app(monkeypatch, settings, make_fake_container(settings))
    async with application.router.lifespan_context(application):
        pass
    assert spy.refreshed == []
    assert spy.state is None
