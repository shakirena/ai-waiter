"""/health (liveness) и /health/ready (readiness). Без авторизации, без внутренних деталей.

Тело ответа не содержит текстов исключений, строк подключения и хостов — детали только в лог.
Проверка ``database`` (``SELECT 1``) добавляется в #7.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app import __version__
from app.api.deps import get_app_settings, get_container
from app.core.config import AppMode, Settings
from app.core.container import Container

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# Таймаут одной проверки readiness, секунды (arch doc: «каждая проверка с таймаутом 2 с»).
READINESS_CHECK_TIMEOUT = 2.0

CheckStatus = Literal["ok", "fail", "skipped"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    mode: AppMode
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[Literal["database", "redis"], CheckStatus]


@router.get("", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_app_settings)]) -> HealthResponse:
    """Liveness: не обращается к внешним сервисам. 200, пока жив event loop."""
    return HealthResponse(status="ok", mode=settings.app_mode, version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(container: Annotated[Container, Depends(get_container)], response: Response) -> ReadinessResponse:
    """Readiness: в scaled — ``ping()`` шины и rate-limiter-а (Redis), в single — ``"skipped"``.
    Хотя бы одна проверка ``"fail"`` → 503."""
    checks: dict[Literal["database", "redis"], CheckStatus] = {}
    if container.settings.app_mode == AppMode.SCALED:
        results = await asyncio.gather(
            _check("event_bus", container.event_bus.ping),
            _check("rate_limiter", container.rate_limiter.ping),
        )
        checks["redis"] = "ok" if all(results) else "fail"
    else:
        checks["redis"] = "skipped"

    if "fail" in checks.values():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready", checks=checks)
    return ReadinessResponse(status="ready", checks=checks)


async def _check(component: str, ping: Callable[[], Awaitable[bool]]) -> bool:
    """Одна проверка с таймаутом. Исключение, таймаут или ``False`` — неуспех; детали только в лог."""
    try:
        async with asyncio.timeout(READINESS_CHECK_TIMEOUT):
            ok = await ping()
    except TimeoutError:
        logger.warning("Проверка готовности: превышен таймаут", extra={"component": component})
        return False
    except Exception:
        logger.warning("Проверка готовности: ошибка", extra={"component": component}, exc_info=True)
        return False
    if ok is not True:
        logger.warning("Проверка готовности: компонент недоступен", extra={"component": component})
        return False
    return True
