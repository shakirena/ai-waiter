"""FastAPI-зависимости: доступ к Container из app.state (без глобальных синглтонов)."""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.container import Container
from app.core.events import EventBus
from app.core.ratelimit import RateLimiter
from app.core.scheduler import TaskScheduler


def get_container(request: Request) -> Container:
    """``request.app.state.container``; для WebSocket — через ``HTTPConnection`` в #20."""
    raise NotImplementedError


def get_app_settings(request: Request) -> Settings:
    raise NotImplementedError


def get_event_bus(request: Request) -> EventBus:
    raise NotImplementedError


def get_scheduler(request: Request) -> TaskScheduler:
    raise NotImplementedError


def get_rate_limiter(request: Request) -> RateLimiter:
    raise NotImplementedError
