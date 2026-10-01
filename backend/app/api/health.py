"""/health (liveness) и /health/ready (readiness). Без авторизации, без внутренних деталей."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.api.deps import get_container
from app.core.config import AppMode
from app.core.container import Container

CheckStatus = Literal["ok", "fail", "skipped"]

CHECK_TIMEOUT_SECONDS = 2.0

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    mode: AppMode
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckStatus]  # каркас: "redis"; #7 добавляет "database"


@router.get("", response_model=HealthResponse)
async def health(container: Annotated[Container, Depends(get_container)]) -> HealthResponse:
    """Liveness: не обращается к внешним сервисам. 200, пока жив event loop."""
    raise NotImplementedError


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def ready(
    response: Response, container: Annotated[Container, Depends(get_container)]
) -> ReadinessResponse:
    """redis: в scaled — ``event_bus.ping()`` и ``rate_limiter.ping()`` с таймаутом
    CHECK_TIMEOUT_SECONDS; в single — "skipped". database — добавляется в #7 (``SELECT 1``).
    Любой "fail" → 503 и status="not_ready". Тексты исключений только в лог."""
    raise NotImplementedError
