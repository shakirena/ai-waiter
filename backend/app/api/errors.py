"""Формат ошибки API ``/api/*`` (#9, ADR-9.6, DEC-015): ``{"detail": {"code": "<snake_case>"}}``.

Совместим с FastAPI ``{"detail": …}``: ``HTTPException(detail={"code": …})``. 422 валидации тела
остаётся стандартным ``{"detail": [...]}``. Текст ошибки локализует фронтенд по ``code``: язык в
ошибку не вкладывается, деталей (токена, названий, причины) нет.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from fastapi import HTTPException
from pydantic import BaseModel


class ErrorCode(StrEnum):
    """Коды ошибок гостевого API (arch «API Contracts»)."""

    QR_INVALID = "qr_invalid"  # 404
    TABLE_INACTIVE = "table_inactive"  # 403
    RATE_LIMITED = "rate_limited"  # 429 + Retry-After
    TRY_AGAIN = "try_again"  # 503
    GUEST_SESSION_REQUIRED = "guest_session_required"  # 401
    GUEST_SESSION_INVALID = "guest_session_invalid"  # 401
    VISIT_CLOSED = "visit_closed"  # 401
    LANG_NOT_SUPPORTED = "lang_not_supported"  # 422


class ApiErrorDetail(BaseModel):
    code: ErrorCode


class ApiErrorBody(BaseModel):
    """Тело ошибки для ``responses=`` в OpenAPI."""

    detail: ApiErrorDetail


def api_error(status_code: int, code: ErrorCode, headers: Mapping[str, str] | None = None) -> HTTPException:
    """``HTTPException(status_code, detail={"code": code.value}, headers=dict(headers) if headers else None)``.

    Вызывающий делает ``raise api_error(...)``. ``Cache-Control: no-store`` к ошибкам гостевого API
    добавляет роутер (ADR-9.6: ответы ``qr_invalid`` одинаковы по коду, телу и заголовкам)."""
    raise NotImplementedError
