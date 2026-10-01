"""Точка сборки FastAPI-приложения.

Запуск: ``uvicorn app.main:app``, ``uvicorn app.main:create_app --factory`` или ``python -m app``.
Атрибут ``app`` создаётся лениво (module ``__getattr__``): импорт ``app.main`` не читает
окружение (G3 проверяет ``python -c "import app.main"``), тесты передают свой Settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.core.config import Settings, get_settings
from app.core.scheduler import TaskRegistry


def create_app(settings: Settings | None = None, *, registry: TaskRegistry | None = None) -> FastAPI:
    """Собрать приложение.

    1. ``settings = settings or get_settings()``; ``configure_logging(settings)``.
    2. ``FastAPI(title="AI Waiter", version=__version__, lifespan=...)``; ``docs_url``/``redoc_url``/
       ``openapi_url`` = None, если ``not settings.is_docs_enabled``.
    3. Роутеры: ``health.router``; далее ``/api`` и ``/integration/v1`` (следующие stories).
    4. Если ``settings.serve_frontend`` — ``mount_spa(app, settings.frontend_dist_path)`` ПОСЛЕДНИМ.
    5. ``registry`` по умолчанию — ``app.tasks.registry``.
    """
    settings = settings or get_settings()
    raise NotImplementedError(f"create_app(mode={settings.app_mode})")


def _lifespan(
    settings: Settings, registry: TaskRegistry
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Фабрика lifespan: build_container → start_container → app.state.container → yield → stop_container.
    Недоступность БД/Redis на старте не роняет процесс — это видно в /health/ready."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        raise NotImplementedError
        yield

    return lifespan


def __getattr__(name: str) -> Any:
    """``uvicorn app.main:app``: при первом обращении к ``app`` собрать приложение из env
    и закэшировать в ``globals()``; прочие имена — AttributeError."""
    raise NotImplementedError


__all__ = ["__version__", "create_app"]
