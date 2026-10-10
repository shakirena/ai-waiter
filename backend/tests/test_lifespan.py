"""Lifespan и зависимости FastAPI (#38): Container создаётся при старте, кладётся в app.state,
останавливается при выходе; эндпоинты получают компоненты через app/api/deps.py."""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.api import deps
from app.core.config import ConfigError, Settings
from app.core.container import Container
from app.core.events import EventBus
from app.core.ratelimit import RateLimiter
from app.core.scheduler import TaskRegistry, TaskScheduler
from app.main import create_app
from tests.conftest import make_settings
from tests.doubles import FakeEventBus, make_fake_container


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
        assert calls == ["event_bus.start", "rate_limiter.start", "scheduler.start"]
    assert built == [(settings, registry)]
    assert calls[3:] == ["scheduler.stop", "rate_limiter.stop", "event_bus.stop"]


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
    ) -> dict[str, bool]:
        return {
            "container": c is container,
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
