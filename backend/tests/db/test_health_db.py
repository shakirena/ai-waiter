"""#56: /health/ready с настоящим PostgreSQL — ``"database": "ok"``; недоступная БД — ``"fail"`` без деталей.

#71 (ADR-60.2): при ``APP_ENV=prod`` демо-заведение в базе (или невыполненная проверка) → 503 с
прежним телом и WARNING без строки подключения; удаление демо видно со следующего опроса.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import app.core.container as container_module
from app.api.demo_data import DEMO_FOUND_WARNING, DEMO_GONE_INFO
from app.core.config import Settings
from app.core.scheduler import TaskRegistry
from app.db.session import Database
from app.main import create_app
from app.models.tenant import Tenant
from app.seed.data import DEMO_TENANT_ID
from app.seed.loader import apply_seed
from tests.conftest import make_settings
from tests.db.conftest import alembic_command, reset_schema

pytestmark = pytest.mark.db


async def _ready(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Response:
    monkeypatch.setattr(container_module, "Database", Database)  # настоящий Database вместо FakeDatabase
    application = create_app(settings, registry=TaskRegistry())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get("/health/ready")


async def test_ready_with_available_database(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    r = await _ready(make_settings(database_url=migrated_database), monkeypatch)
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "redis": "skipped"}}


async def test_ready_with_wrong_credentials_is_503_without_details(
    migrated_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong_password = "wrong-pw-56-x7"  # заведомо неверный пароль
    url = make_url(migrated_database).set(password=wrong_password, database="missing_db_56_test")
    r = await _ready(make_settings(database_url=url.render_as_string(hide_password=False)), monkeypatch)
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "fail", "redis": "skipped"}}
    assert wrong_password not in r.text


# ---------------------------------------------------------------- #71: демо-заведение при APP_ENV=prod (ADR-60.2)

PROD = {"app_env": "prod", "public_base_url": "https://menu.example.com"}


@pytest.fixture
def committed_database(migrated_database: str) -> Iterator[str]:
    """Чистая схема до и после теста: тест фиксирует строки ``tenants``, другим тестам они не нужны."""
    reset_schema(migrated_database)
    alembic_command(migrated_database, "upgrade", "head")
    yield migrated_database
    reset_schema(migrated_database)
    alembic_command(migrated_database, "upgrade", "head")


@asynccontextmanager
async def _committed_session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session:
            yield session
    finally:
        await engine.dispose()


def _demo_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [rec for rec in caplog.records if rec.name == "app.api.demo_data"]


async def test_prod_with_demo_tenant_is_503_and_warns(
    committed_database: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-2: prod + демо-заведение (полный сид, зафиксирован) → 503 без деталей, WARNING без пароля."""
    async with _committed_session(committed_database) as session:
        await apply_seed(session)
        await session.commit()

    password = make_url(committed_database).password
    with caplog.at_level(logging.INFO, logger="app.api.demo_data"):
        r = await _ready(make_settings(database_url=committed_database, **PROD), monkeypatch)
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": "skipped"}}
    records = _demo_records(caplog)
    assert [(rec.levelno, rec.getMessage()) for rec in records] == [(logging.WARNING, DEMO_FOUND_WARNING)]
    for rec in caplog.records:
        message = rec.getMessage()
        assert "postgresql" not in message
        if password:
            assert password not in message


async def test_prod_without_demo_tenant_is_ready(
    committed_database: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """E-10: prod, в базе только «чужое» (боевое) заведение — 200, записей о демо нет."""
    async with _committed_session(committed_database) as session:
        session.add(Tenant(name="Боевое заведение"))
        await session.commit()

    with caplog.at_level(logging.INFO, logger="app.api.demo_data"):
        r = await _ready(make_settings(database_url=committed_database, **PROD), monkeypatch)
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "redis": "skipped"}}
    assert _demo_records(caplog) == []


async def test_prod_demo_removed_between_polls_becomes_ready(
    committed_database: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Удаление демо без перезапуска: следующий опрос — 200 и INFO ``DEMO_GONE_INFO``."""
    async with _committed_session(committed_database) as session:
        session.add(Tenant(id=DEMO_TENANT_ID, name="Demo Restoran"))
        await session.commit()

    monkeypatch.setattr(container_module, "Database", Database)
    application = create_app(make_settings(database_url=committed_database, **PROD), registry=TaskRegistry())
    with caplog.at_level(logging.INFO, logger="app.api.demo_data"):
        async with application.router.lifespan_context(application):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                first = await ac.get("/health/ready")
                async with _committed_session(committed_database) as session:
                    await session.execute(delete(Tenant).where(Tenant.id == DEMO_TENANT_ID))
                    await session.commit()
                second = await ac.get("/health/ready")
                third = await ac.get("/health/ready")
    assert first.status_code == 503
    assert second.status_code == 200
    assert third.status_code == 200
    assert second.json() == {"status": "ready", "checks": {"database": "ok", "redis": "skipped"}}
    assert [(rec.levelno, rec.getMessage()) for rec in _demo_records(caplog)] == [
        (logging.WARNING, DEMO_FOUND_WARNING),
        (logging.INFO, DEMO_GONE_INFO),
    ]


async def test_prod_without_schema_is_503_with_database_ok(
    committed_database: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """NFR-5: нет таблицы ``tenants`` (миграции не применены) — ``database`` ok, но 503: неизвестно ≠ «демо нет»."""
    reset_schema(committed_database)
    password = make_url(committed_database).password
    with caplog.at_level(logging.INFO, logger="app.api.demo_data"):
        r = await _ready(make_settings(database_url=committed_database, **PROD), monkeypatch)
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": "skipped"}}
    [record] = _demo_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    if password:
        assert password not in record.getMessage()
