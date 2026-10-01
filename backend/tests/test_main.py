"""Сборка приложения (#37): create_app, ленивый ``app``, запуск ``python -m app``."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import app.__main__ as entrypoint
import app.main as main_module
from app import __version__
from app.core.config import AppEnv, Settings, get_settings
from app.core.scheduler import TaskRegistry
from app.main import create_app
from tests.conftest import make_settings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[pytest.MonkeyPatch]:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


async def _get(settings: Settings, path: str) -> int:
    application = create_app(settings, registry=TaskRegistry())
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return (await ac.get(path)).status_code


def test_create_app_keeps_settings_in_state() -> None:
    settings = make_settings()
    registry = TaskRegistry()
    application = create_app(settings, registry=registry)
    assert application.state.settings is settings
    assert application.state.task_registry is registry
    assert application.version == __version__


def test_create_app_uses_default_task_registry() -> None:
    from app.tasks import registry as default_registry

    application = create_app(make_settings())
    assert application.state.task_registry is default_registry


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_docs_enabled_outside_prod(path: str) -> None:
    assert await _get(make_settings(), path) == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_docs_disabled_in_prod(path: str) -> None:
    settings = make_settings(app_env=AppEnv.PROD, public_base_url="https://menu.example.com")
    assert await _get(settings, path) == 404


async def test_health_reports_scaled_mode() -> None:
    settings = make_settings(app_mode="scaled", redis_url="redis://redis:6379/0")
    application = create_app(settings, registry=TaskRegistry())
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "mode": "scaled", "version": __version__}


async def test_health_has_no_auth_and_no_internal_details(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status", "mode", "version"}


def test_import_does_not_read_environment(tmp_path: Path) -> None:
    """Импорт app.main не читает окружение: даже с некорректным APP_MODE импорт проходит,
    а ``app`` не создаётся, пока к нему не обратились."""
    backend_dir = Path(__file__).resolve().parents[1]
    code = "import app.main as m; assert 'app' not in vars(m)"
    env = {**os.environ, "APP_MODE": "bogus", "PYTHONPATH": str(backend_dir)}
    result = subprocess.run(  # noqa: S603 — фиксированная команда, без shell
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_lazy_app_attribute_built_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SERVE_FRONTEND", "false")
    clean_env.setenv("LOG_FORMAT", "console")
    clean_env.delitem(main_module.__dict__, "app", raising=False)
    application = main_module.app
    assert application.state.settings.serve_frontend is False
    assert main_module.app is application  # закэширован в globals()
    clean_env.delitem(main_module.__dict__, "app")


def test_unknown_module_attribute_raises() -> None:
    with pytest.raises(AttributeError, match="nonexistent"):
        _ = main_module.nonexistent


def test_main_runs_uvicorn_with_settings(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("PORT", "8765")
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    clean_env.setattr(entrypoint.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    entrypoint.main()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("app.main:create_app",)
    assert kwargs == {
        "factory": True,
        "host": "127.0.0.1",
        "port": 8765,
        "workers": 1,
        "log_config": None,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1,::1",
    }


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"APP_MODE": "bogus"}, "APP_MODE: недопустимое значение"),
        ({"APP_MODE": "scaled"}, "REDIS_URL обязателен при APP_MODE=scaled"),
    ],
)
def test_main_exits_with_clear_error(clean_env: pytest.MonkeyPatch, env: dict[str, str], expected: str) -> None:
    for key, value in env.items():
        clean_env.setenv(key, value)
    clean_env.setattr(entrypoint.uvicorn, "run", lambda *a, **kw: pytest.fail("uvicorn не должен запускаться"))
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert expected in str(exc_info.value.code)
