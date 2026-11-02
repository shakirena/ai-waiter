"""FastAPI-зависимости: доступ к Container из app.state (без глобальных синглтонов).

Использование в эндпоинтах::

    async def handler(bus: Annotated[EventBus, Depends(get_event_bus)]) -> ...: ...

    async def create(session: SessionDep) -> ...:
        ...
        await session.commit()  # транзакцию фиксирует сервис явно (ADR-7.9)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.demo_data import DemoDataMonitor
from app.core.config import Settings
from app.core.container import Container
from app.core.events import EventBus
from app.core.ratelimit import RateLimiter
from app.core.scheduler import TaskScheduler
from app.db.session import Database


def get_container(request: Request) -> Container:
    """``request.app.state.container``; для WebSocket — через ``HTTPConnection`` в #20.

    Container появляется в lifespan; обращение до старта — ошибка программиста (RuntimeError)."""
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("Container не создан: lifespan приложения не запущен")
    return container


def get_app_settings(request: Request) -> Settings:
    """Настройки из Container; до старта lifespan — те же настройки из ``app.state.settings``
    (их кладёт ``create_app``), чтобы liveness ``/health`` не зависел от Container."""
    container: Container | None = getattr(request.app.state, "container", None)
    if container is not None:
        return container.settings
    settings: Settings = request.app.state.settings
    return settings


def get_event_bus(request: Request) -> EventBus:
    return get_container(request).event_bus


def get_scheduler(request: Request) -> TaskScheduler:
    return get_container(request).scheduler


def get_rate_limiter(request: Request) -> RateLimiter:
    return get_container(request).rate_limiter


def get_database(request: Request) -> Database:
    return get_container(request).database


def get_demo_data_monitor(request: Request) -> DemoDataMonitor:
    """``request.app.state.demo_data_monitor`` — его создаёт ``create_app`` (#71, ADR-60.2)."""
    monitor: DemoDataMonitor = request.app.state.demo_data_monitor
    return monitor


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Сессия на запрос. Автокоммита нет: сервис вызывает ``await session.commit()`` сам
    (NFR-3: заказ фиксируется до вызова ИИ), незафиксированное откатывается при закрытии."""
    async with get_database(request).session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
