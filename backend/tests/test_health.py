from __future__ import annotations

import logging
from collections.abc import Callable

import pytest
from httpx import ASGITransport, AsyncClient, Response

import app.api.health as health_module
import app.main as main_module
from app.core.config import Settings
from app.core.container import Container
from app.core.scheduler import TaskRegistry
from app.main import create_app
from tests.conftest import make_settings
from tests.doubles import FakeEventBus, FakeRateLimiter, make_fake_container


async def test_health_liveness(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mode"] == "single"
    assert body["version"]


async def test_ready_in_single_mode_skips_redis(client: AsyncClient) -> None:
    r = await client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"redis": "skipped"}}


# ---------------------------------------------------------------- /health/ready с тестовыми двойниками (#38)

SECRET_DETAIL = "redis://:s3cret@10.0.0.5:6379 connection refused"
SCALED = {"app_mode": "scaled", "redis_url": "redis://redis:6379/0"}


async def _get_with_container(
    monkeypatch: pytest.MonkeyPatch,
    container_factory: Callable[[Settings], Container],
    *paths: str,
    settings: Settings | None = None,
) -> list[Response]:
    """Запросы к приложению, у которого Container подменён двойником через ``app.main.build_container``."""
    settings = settings or make_settings(**SCALED)
    monkeypatch.setattr(main_module, "build_container", lambda s, r: container_factory(s))
    application = create_app(settings, registry=TaskRegistry())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return [await ac.get(path) for path in paths]


async def test_ready_in_scaled_mode_when_redis_available(monkeypatch: pytest.MonkeyPatch) -> None:
    [r] = await _get_with_container(monkeypatch, make_fake_container, "/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"redis": "ok"}}


@pytest.mark.parametrize("failing", ["event_bus", "rate_limiter"])
async def test_ready_returns_503_without_details_when_check_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failing: str
) -> None:
    error = ConnectionError(SECRET_DETAIL)

    def factory(settings: Settings) -> Container:
        if failing == "event_bus":
            return make_fake_container(settings, bus=FakeEventBus(ping_error=error))
        return make_fake_container(settings, rate_limiter=FakeRateLimiter(ping_error=error))

    with caplog.at_level(logging.WARNING, logger="app.api.health"):
        [r] = await _get_with_container(monkeypatch, factory, "/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"redis": "fail"}}
    assert "s3cret" not in r.text
    assert "10.0.0.5" not in r.text
    logged = [rec for rec in caplog.records if rec.name == "app.api.health"]
    assert [getattr(rec, "component", None) for rec in logged] == [failing]
    assert logged[0].exc_info is not None, "детали ошибки должны попасть в лог"


async def test_ready_returns_503_when_ping_reports_false(monkeypatch: pytest.MonkeyPatch) -> None:
    [r] = await _get_with_container(
        monkeypatch, lambda s: make_fake_container(s, bus=FakeEventBus(ping_result=False)), "/health/ready"
    )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"redis": "fail"}}


async def test_ready_check_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_module, "READINESS_CHECK_TIMEOUT", 0.05)
    [r] = await _get_with_container(
        monkeypatch, lambda s: make_fake_container(s, rate_limiter=FakeRateLimiter(ping_delay=5.0)), "/health/ready"
    )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"redis": "fail"}}


def test_readiness_timeout_is_two_seconds() -> None:
    assert health_module.READINESS_CHECK_TIMEOUT == 2.0


async def test_redis_down_at_startup_keeps_liveness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis недоступен на старте: процесс работает, liveness 200, readiness 503."""
    down = ConnectionError(SECRET_DETAIL)
    live, ready = await _get_with_container(
        monkeypatch,
        lambda s: make_fake_container(s, bus=FakeEventBus(start_error=down, ping_error=down)),
        "/health",
        "/health/ready",
    )
    assert live.status_code == 200
    assert live.json()["mode"] == "scaled"
    assert ready.status_code == 503
    assert "s3cret" not in ready.text


async def test_ready_does_not_ping_in_single_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = FakeEventBus(ping_error=AssertionError("ping в single не вызывается"))
    [r] = await _get_with_container(
        monkeypatch, lambda s: make_fake_container(s, bus=bus), "/health/ready", settings=make_settings()
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"redis": "skipped"}}


async def test_ready_is_listed_in_openapi_with_503(monkeypatch: pytest.MonkeyPatch) -> None:
    [r] = await _get_with_container(monkeypatch, make_fake_container, "/openapi.json")
    responses = r.json()["paths"]["/health/ready"]["get"]["responses"]
    assert {"200", "503"} <= set(responses)
