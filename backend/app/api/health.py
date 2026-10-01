"""/health (liveness). Без авторизации, без внутренних деталей.

Readiness (``/health/ready``: проверки Redis, затем БД) подключается вместе с Container в #38.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app import __version__
from app.core.config import AppMode, Settings

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    mode: AppMode
    version: str


def _app_settings(request: Request) -> Settings:
    """Настройки, с которыми собрано приложение (``create_app`` кладёт их в ``app.state.settings``)."""
    settings: Settings = request.app.state.settings
    return settings


@router.get("", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(_app_settings)]) -> HealthResponse:
    """Liveness: не обращается к внешним сервисам. 200, пока жив event loop."""
    return HealthResponse(status="ok", mode=settings.app_mode, version=__version__)
