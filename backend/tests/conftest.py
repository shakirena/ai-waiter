"""Общие фикстуры. Тесты без маркеров db/scaled не требуют PostgreSQL и Redis
и запускаются на Linux и Windows (ADR-5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import AppMode, Settings
from app.core.scheduler import TaskRegistry
from app.main import create_app


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_mode": AppMode.SINGLE,
        "app_env": "test",
        "serve_frontend": False,
        "log_format": "console",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def registry() -> TaskRegistry:
    return TaskRegistry()


@pytest.fixture
def app(settings: Settings, registry: TaskRegistry) -> FastAPI:
    return create_app(settings, registry=registry)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


@pytest.fixture
def spa_dist(tmp_path: Path) -> Path:
    """Минимальная «сборка Vite» во временном каталоге."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path
