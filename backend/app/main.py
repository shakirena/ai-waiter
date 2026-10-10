"""Точка сборки FastAPI-приложения.

Запуск: ``uvicorn app.main:app``, ``uvicorn app.main:create_app --factory`` или ``python -m app``.
Атрибут ``app`` создаётся лениво (module ``__getattr__``): импорт ``app.main`` не читает
окружение (G3 проверяет ``python -c "import app.main"``), тесты передают свой Settings.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app import __version__
from app.api import health
from app.core.config import Settings, get_settings
from app.core.container import build_container, start_container, stop_container
from app.core.log import configure_logging
from app.core.scheduler import TaskRegistry
from app.web.spa import mount_spa

logger = logging.getLogger(__name__)


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
    configure_logging(settings)

    if registry is None:
        from app.tasks import registry as default_registry

        registry = default_registry

    docs_enabled = settings.is_docs_enabled
    app = FastAPI(
        title="AI Waiter",
        version=__version__,
        lifespan=_lifespan(settings, registry),
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    # Доступны и до старта lifespan: зависимости эндпоинтов читают их из request.app.state.
    app.state.settings = settings
    app.state.task_registry = registry

    app.include_router(health.router)

    if settings.serve_frontend:
        mount_spa(app, settings.frontend_dist_path)

    return app


def _lifespan(settings: Settings, registry: TaskRegistry) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Фабрика lifespan: ``build_container`` → ``start_container`` → ``app.state.container`` →
    работа → ``stop_container``.

    Неизвестный режим — ``ConfigError`` из ``build_container``: приложение не стартует.
    Недоступность Redis при старте процесс не роняет (``start_container`` логирует ошибку),
    о ней сообщает ``/health/ready``."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = build_container(settings, registry)
        await start_container(container)
        app.state.container = container
        logger.info(
            "Приложение запущено",
            extra={
                "mode": settings.app_mode.value,
                "env": settings.app_env.value,
                "version": __version__,
                "tasks": len(registry.handlers),
            },
        )
        try:
            yield
        finally:
            await stop_container(container)
            logger.info("Приложение остановлено", extra={"mode": settings.app_mode.value})

    return lifespan


def __getattr__(name: str) -> Any:
    """``uvicorn app.main:app``: при первом обращении к ``app`` собрать приложение из env
    и закэшировать в ``globals()``; прочие имена — AttributeError."""
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"модуль {__name__!r} не содержит атрибута {name!r}")


__all__ = ["__version__", "create_app"]
