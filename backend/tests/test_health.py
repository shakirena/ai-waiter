from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

import pytest
from httpx import ASGITransport, AsyncClient, Response

import app.api.demo_data as demo_data_module
import app.api.health as health_module
import app.main as main_module
from app.api.demo_data import DEMO_FOUND_WARNING
from app.core.config import Settings
from app.core.container import Container
from app.core.scheduler import TaskRegistry
from app.db.session import Database
from app.main import create_app
from tests.conftest import make_settings
from tests.doubles import FakeDatabase, FakeEventBus, FakeRateLimiter, make_fake_container


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
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "redis": "skipped"}}


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
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


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
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": "fail"}}
    assert "s3cret" not in r.text
    assert "10.0.0.5" not in r.text
    logged = [rec for rec in caplog.records if rec.name == "app.api.health"]
    assert [getattr(rec, "component", None) for rec in logged] == [failing]
    # #71: без traceback и без сообщения клиента Redis (там может быть URL с паролем) — только класс.
    assert logged[0].exc_info is None
    message = logged[0].getMessage()
    assert "ConnectionError" in message
    assert "s3cret" not in message
    assert "10.0.0.5" not in message


async def test_ready_returns_503_when_ping_reports_false(monkeypatch: pytest.MonkeyPatch) -> None:
    [r] = await _get_with_container(
        monkeypatch, lambda s: make_fake_container(s, bus=FakeEventBus(ping_result=False)), "/health/ready"
    )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": "fail"}}


async def test_ready_check_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_module, "READINESS_CHECK_TIMEOUT", 0.05)
    [r] = await _get_with_container(
        monkeypatch, lambda s: make_fake_container(s, rate_limiter=FakeRateLimiter(ping_delay=5.0)), "/health/ready"
    )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": "fail"}}


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
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "redis": "skipped"}}


async def test_ready_is_listed_in_openapi_with_503(monkeypatch: pytest.MonkeyPatch) -> None:
    [r] = await _get_with_container(monkeypatch, make_fake_container, "/openapi.json")
    responses = r.json()["paths"]["/health/ready"]["get"]["responses"]
    assert {"200", "503"} <= set(responses)


# ---------------------------------------------------------------- #56: проверка database (ADR-7.9)

DB_SECRET_DETAIL = "connection to postgresql+asyncpg://ai_waiter:pw-s3cret@db.example.com/ai_waiter refused"


@pytest.mark.parametrize("settings_overrides", [{}, SCALED], ids=["single", "scaled"])
async def test_ready_checks_database_in_both_modes(
    monkeypatch: pytest.MonkeyPatch, settings_overrides: dict[str, str]
) -> None:
    database = FakeDatabase(ping_result=False)
    [r] = await _get_with_container(
        monkeypatch,
        lambda s: make_fake_container(s, database=database),
        "/health/ready",
        settings=make_settings(**settings_overrides),
    )
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "fail"
    assert body["checks"]["redis"] == ("ok" if settings_overrides else "skipped")


async def test_ready_database_error_has_no_details_in_body(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    database = FakeDatabase(ping_error=ConnectionError(DB_SECRET_DETAIL))
    with caplog.at_level(logging.WARNING, logger="app.api.health"):
        [r] = await _get_with_container(
            monkeypatch, lambda s: make_fake_container(s, database=database), "/health/ready", settings=make_settings()
        )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "fail", "redis": "skipped"}}
    for leaked in ("pw-s3cret", "db.example.com", "asyncpg", "refused"):
        assert leaked not in r.text
    logged = [rec for rec in caplog.records if rec.name == "app.api.health"]
    assert [getattr(rec, "component", None) for rec in logged] == ["database"]


async def test_ready_database_timeout_is_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_module, "READINESS_CHECK_TIMEOUT", 0.05)
    database = FakeDatabase(ping_delay=5.0)
    [r] = await _get_with_container(
        monkeypatch, lambda s: make_fake_container(s, database=database), "/health/ready", settings=make_settings()
    )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "fail", "redis": "skipped"}}


async def test_ready_runs_checks_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """База и Redis проверяются параллельно: суммарное время — одна задержка, а не сумма."""
    monkeypatch.setattr(health_module, "READINESS_CHECK_TIMEOUT", 0.5)

    def factory(settings: Settings) -> Container:
        return make_fake_container(
            settings,
            database=FakeDatabase(ping_delay=0.3),
            bus=FakeEventBus(ping_delay=0.3),
            rate_limiter=FakeRateLimiter(ping_delay=0.3),
        )

    started = time.perf_counter()
    [r] = await _get_with_container(monkeypatch, factory, "/health/ready")
    elapsed = time.perf_counter() - started
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}
    assert elapsed < 0.8, f"проверки шли последовательно: {elapsed:.2f} с (последовательно ≥ 0.9 с)"


async def test_ready_with_real_database_object_masks_password_in_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Настоящий ``Database`` с недоступным движком: 503 без деталей, в логе ошибка без пароля."""
    secret_url = "postgresql+asyncpg://ai_waiter:pw-s3cret@db.invalid/ai_waiter"

    class _BrokenEngine:
        def connect(self) -> object:
            raise ConnectionRefusedError(f"cannot connect: {secret_url}")

    def factory(settings: Settings) -> Container:
        database = Database(settings)
        database._engine = _BrokenEngine()  # type: ignore[assignment]
        return make_fake_container(settings, database=database)  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING):
        [r] = await _get_with_container(
            monkeypatch, factory, "/health/ready", settings=make_settings(database_url=secret_url)
        )
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == "fail"
    assert "pw-s3cret" not in r.text
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("ConnectionRefusedError" in message for message in messages)
    assert all("pw-s3cret" not in message for message in messages)
    assert all(rec.exc_info is None for rec in caplog.records if rec.name in {"app.db.session", "app.api.health"})


async def test_liveness_does_not_touch_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = FakeDatabase(ping_error=AssertionError("/health не обращается к БД"))
    [r] = await _get_with_container(
        monkeypatch, lambda s: make_fake_container(s, database=database), "/health", settings=make_settings()
    )
    assert r.status_code == 200


# ---------------------------------------------------------------- #71: демо-заведение при APP_ENV=prod (ADR-60.2/60.3)

PROD = {"app_env": "prod", "public_base_url": "https://menu.example.com"}


class DemoQuery:
    """Подмена ``app.api.demo_data.demo_tenant_exists``: результат, ошибка или задержка; счётчик вызовов."""

    def __init__(self, result: bool = False, *, error: Exception | None = None, delay: float = 0.0) -> None:
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = 0

    async def __call__(self, session: object) -> bool:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


def _install(monkeypatch: pytest.MonkeyPatch, query: DemoQuery) -> DemoQuery:
    monkeypatch.setattr(demo_data_module, "demo_tenant_exists", query)
    return query


MODES = pytest.mark.parametrize(("overrides", "redis"), [({}, "skipped"), (SCALED, "ok")], ids=["single", "scaled"])


@MODES
async def test_prod_demo_found_is_503_with_unchanged_body(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str], redis: str
) -> None:
    _install(monkeypatch, DemoQuery(True))
    [r] = await _get_with_container(
        monkeypatch, make_fake_container, "/health/ready", settings=make_settings(**PROD, **overrides)
    )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": redis}}
    assert "demo" not in r.text.lower()


@MODES
async def test_prod_demo_check_failed_is_503(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str], redis: str
) -> None:
    _install(monkeypatch, DemoQuery(error=RuntimeError("relation tenants does not exist")))
    [r] = await _get_with_container(
        monkeypatch, make_fake_container, "/health/ready", settings=make_settings(**PROD, **overrides)
    )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": redis}}
    assert "tenants" not in r.text


async def test_prod_demo_check_timeout_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_module, "READINESS_CHECK_TIMEOUT", 0.05)
    _install(monkeypatch, DemoQuery(True, delay=5.0))
    [r] = await _get_with_container(monkeypatch, make_fake_container, "/health/ready", settings=make_settings(**PROD))
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": "skipped"}}


@MODES
async def test_prod_without_demo_is_ready(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str], redis: str
) -> None:
    query = _install(monkeypatch, DemoQuery(False))
    [r] = await _get_with_container(
        monkeypatch, make_fake_container, "/health/ready", settings=make_settings(**PROD, **overrides)
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "redis": redis}}
    assert query.calls == 2, "одна проверка в lifespan и одна на запрос"


async def test_prod_database_down_is_503_regardless_of_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    """E-9: БД недоступна — 503 из-за ``database``; «демо нет» не делает приложение готовым."""
    _install(monkeypatch, DemoQuery(False))
    [r] = await _get_with_container(
        monkeypatch,
        lambda s: make_fake_container(s, database=FakeDatabase(ping_result=False)),
        "/health/ready",
        settings=make_settings(**PROD),
    )
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "fail", "redis": "skipped"}}


@pytest.mark.parametrize("app_env", ["dev", "test"])
@pytest.mark.parametrize("overrides", [{}, SCALED], ids=["single", "scaled"])
async def test_demo_check_not_called_outside_prod(
    monkeypatch: pytest.MonkeyPatch, app_env: str, overrides: dict[str, str]
) -> None:
    """FR-4/E-7/E-8: вне prod проверка не вызывается, демо в базе на readiness не влияет."""
    query = _install(monkeypatch, DemoQuery(True))
    [r] = await _get_with_container(
        monkeypatch, make_fake_container, "/health/ready", settings=make_settings(app_env=app_env, **overrides)
    )
    assert r.status_code == 200
    assert query.calls == 0


async def test_prod_demo_warning_logged_once_for_repeated_polls(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    query = _install(monkeypatch, DemoQuery(True))
    with caplog.at_level(logging.INFO, logger="app.api.demo_data"):
        responses = await _get_with_container(
            monkeypatch, make_fake_container, *["/health/ready"] * 3, settings=make_settings(**PROD)
        )
    assert [r.status_code for r in responses] == [503, 503, 503]
    assert query.calls == 4
    logged = [rec for rec in caplog.records if rec.name == "app.api.demo_data"]
    assert [(rec.levelno, rec.getMessage()) for rec in logged] == [(logging.WARNING, DEMO_FOUND_WARNING)]


async def test_prod_demo_check_runs_concurrently_with_pings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка демо идёт в том же ``gather``, что и ping-и: время запроса — одна задержка, не сумма."""
    monkeypatch.setattr(health_module, "READINESS_CHECK_TIMEOUT", 0.5)
    _install(monkeypatch, DemoQuery(False, delay=0.3))
    container = make_fake_container(
        make_settings(**PROD, **SCALED),
        database=FakeDatabase(ping_delay=0.3),
        bus=FakeEventBus(ping_delay=0.3),
        rate_limiter=FakeRateLimiter(ping_delay=0.3),
    )
    monkeypatch.setattr(main_module, "build_container", lambda s, r: container)
    application = create_app(container.settings, registry=TaskRegistry())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            started = time.perf_counter()
            r = await ac.get("/health/ready")
            elapsed = time.perf_counter() - started
    assert r.status_code == 200
    assert elapsed < 0.55, f"проверка демо шла последовательно с ping-ами: {elapsed:.2f} с"


async def test_prod_openapi_has_no_demo_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-60.3: схема ``/health/ready`` прежняя — в ``checks`` только ``database`` и ``redis``."""
    _install(monkeypatch, DemoQuery(False))
    [r] = await _get_with_container(
        monkeypatch, make_fake_container, "/openapi.json", settings=make_settings(**PROD, docs_enabled=True)
    )
    assert r.status_code == 200
    schema = r.json()["components"]["schemas"]["ReadinessResponse"]
    assert set(schema["properties"]) == {"status", "checks"}
    assert schema["properties"]["checks"]["propertyNames"]["enum"] == ["database", "redis"]
    assert "demo" not in r.text.lower()


async def test_check_database_exception_logged_masked_without_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``_check``: исключение из ping настоящего ``Database`` — текст через ``describe_error``, без traceback."""
    secret_url = "postgresql+asyncpg://ai_waiter:pw-s3cret@db.invalid/ai_waiter"

    def factory(settings: Settings) -> Container:
        database = Database(settings)

        async def raising_ping() -> bool:
            raise ConnectionRefusedError(f"cannot connect: {secret_url}")

        database.ping = raising_ping  # type: ignore[method-assign]
        return make_fake_container(settings, database=database)  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING, logger="app.api.health"):
        [r] = await _get_with_container(
            monkeypatch, factory, "/health/ready", settings=make_settings(database_url=secret_url)
        )
    assert r.status_code == 503
    logged = [rec for rec in caplog.records if rec.name == "app.api.health"]
    assert [getattr(rec, "component", None) for rec in logged] == ["database"]
    assert logged[0].exc_info is None
    message = logged[0].getMessage()
    assert "ConnectionRefusedError" in message
    assert "***" in message
    assert "pw-s3cret" not in message


def test_exception_names_follow_cause_chain_without_messages() -> None:
    try:
        try:
            raise OSError("redis://:s3cret@cache.example.com:6379")
        except OSError as inner:
            raise ConnectionError("Error connecting to redis://:s3cret@cache.example.com") from inner
    except ConnectionError as exc:
        text = health_module._exception_names(exc)
    assert text == "ConnectionError <- OSError"
