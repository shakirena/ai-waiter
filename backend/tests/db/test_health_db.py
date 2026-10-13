"""#56: /health/ready с настоящим PostgreSQL — ``"database": "ok"``; недоступная БД — ``"fail"`` без деталей."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import make_url

import app.core.container as container_module
from app.core.config import Settings
from app.core.scheduler import TaskRegistry
from app.db.session import Database
from app.main import create_app
from tests.conftest import make_settings

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
