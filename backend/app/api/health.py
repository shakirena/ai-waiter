"""/health (liveness) и /health/ready (readiness). Без авторизации, без внутренних деталей.

Тело ответа не содержит текстов исключений, строк подключения и хостов — детали только в лог.
Проверка ``database`` (``SELECT 1`` через ``Database.ping``, #56, ADR-7.9) — в обоих режимах.
При ``APP_ENV=prod`` — ещё проверка демо-заведения (#71, ADR-60.2): найдено или проверка не
выполнена → 503 ``not_ready``; тело при этом прежнее, ключа для демо в ``checks`` нет (ADR-60.3).

В лог — имя компонента и текст ошибки без traceback (traceback драйвера может содержать строку
подключения): для ``database`` — ``Database.describe_error`` (пароль → ``***``), для Redis —
только имена классов исключений по цепочке причин (сообщение клиента Redis может содержать URL).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app import __version__
from app.api.demo_data import DemoDataMonitor, DemoDataState
from app.api.deps import get_app_settings, get_container, get_demo_data_monitor
from app.core.config import AppEnv, AppMode, Settings
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
async def ready(
    container: Annotated[Container, Depends(get_container)],
    monitor: Annotated[DemoDataMonitor, Depends(get_demo_data_monitor)],
    response: Response,
) -> ReadinessResponse:
    """Readiness: ``database`` — ``SELECT 1`` в обоих режимах; ``redis`` — в scaled ``ping()`` шины
    и rate-limiter-а, в single — ``"skipped"``. Проверки идут параллельно, каждая с таймаутом 2 с.
    Хотя бы одна проверка ``"fail"`` → 503."""
    # Docstring попадает в OpenAPI — он прежний (ADR-60.3). #71: при APP_ENV=prod в том же gather
    # выполняется DemoDataMonitor.refresh; демо найдено или проверка не выполнена (не ABSENT) → 503
    # с тем же телом, без отдельного ключа в checks.
    settings = container.settings
    scaled = settings.app_mode == AppMode.SCALED
    database = container.database
    pings: list[Awaitable[bool]] = [_check("database", database.ping, database.describe_error)]
    if scaled:
        pings += [
            _check("event_bus", container.event_bus.ping, _exception_names),
            _check("rate_limiter", container.rate_limiter.ping, _exception_names),
        ]
    demo_check: Awaitable[DemoDataState | None] = (
        monitor.refresh(database) if settings.app_env is AppEnv.PROD else _no_demo_check()
    )
    demo_state, (database_ok, *redis_results) = await asyncio.gather(demo_check, asyncio.gather(*pings))

    checks: dict[Literal["database", "redis"], CheckStatus] = {"database": "ok" if database_ok else "fail"}
    if scaled:
        checks["redis"] = "ok" if all(redis_results) else "fail"
    else:
        checks["redis"] = "skipped"

    demo_blocks = demo_state is not None and demo_state is not DemoDataState.ABSENT
    if "fail" in checks.values() or demo_blocks:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready", checks=checks)
    return ReadinessResponse(status="ready", checks=checks)


async def _no_demo_check() -> None:
    """Вне prod проверка демо-заведения не выполняется (FR-4 spec #60)."""
    return None


def _exception_names(exc: BaseException) -> str:
    """Безопасный текст ошибки Redis: только имена классов по цепочке причин, без сообщений."""
    names: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__)
        if current.__cause__ is not None:
            current = current.__cause__
        else:
            current = None if current.__suppress_context__ else current.__context__
    return " <- ".join(names)


async def _check(
    component: str,
    ping: Callable[[], Awaitable[bool]],
    describe_error: Callable[[BaseException], str],
) -> bool:
    """Одна проверка с таймаутом. Исключение, таймаут или ``False`` — неуспех; детали только в лог.

    Текст исключения — через ``describe_error`` компонента, без traceback (``exc_info`` не передаётся)."""
    try:
        async with asyncio.timeout(READINESS_CHECK_TIMEOUT):
            ok = await ping()
    except TimeoutError:
        logger.warning("Проверка готовности: превышен таймаут", extra={"component": component})
        return False
    except Exception as exc:
        logger.warning("Проверка готовности: ошибка: %s", describe_error(exc), extra={"component": component})
        return False
    if ok is not True:
        logger.warning("Проверка готовности: компонент недоступен", extra={"component": component})
        return False
    return True
