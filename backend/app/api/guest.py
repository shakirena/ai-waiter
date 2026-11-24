"""Гостевой API ``/api/guest/v1`` (#9, ADR-9.1, 9.2, 9.4, 9.6, 9.7; ТЗ FR-1, FR-2, NFR-4).

- ``POST /entry`` — вход по QR-токену (токен в теле, не в пути: путь пишется в access-лог);
- ``GET /session`` — данные действующей сессии (после перезагрузки страницы);
- ``PUT /session/lang`` — смена языка устройства, cookie переподписывается.

Все ответы, включая ошибки (401 зависимости, 422 валидации тела), — ``Cache-Control: no-store``:
его ставит класс маршрута ``GuestRoute``. Он же переводит ошибки соединения с БД в 503 ``try_again``
(в лог — WARNING с ``describe_error``, #73); прочие исключения — 500 по умолчанию. Роутер подключает
``create_app``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import SessionDep, get_app_settings, get_rate_limiter
from app.api.errors import ApiErrorBody, ErrorCode, api_error
from app.api.guest_auth import (
    GUEST_COOKIE_NAME,
    CurrentGuestView,
    GuestSessionCodecDep,
    client_ip_key,
    set_guest_cookie,
)
from app.core.config import AppEnv, Settings
from app.core.ratelimit import RateLimiter, rate_key
from app.guest import entry as guest_entry
from app.guest.entry import EntryResult, GuestVisitView
from app.guest.errors import LangNotSupportedError, QrInvalidError, TableInactiveError, VisitOpenConflictError
from app.models.enums import Lang
from app.schemas.guest import (
    GuestEntryRequest,
    GuestEntryResponse,
    GuestEntryVisitOut,
    GuestLangRequest,
    GuestSessionResponse,
    GuestTableOut,
    GuestTenantOut,
    GuestVisitOut,
)

logger = logging.getLogger(__name__)

ENTRY_RATE_SCOPE: Final = "guest_entry"
ENTRY_RATE_WINDOW: Final = timedelta(seconds=60)
NO_STORE_HEADERS: Final = {"Cache-Control": "no-store"}

# Ошибки соединения с БД (arch «API Contracts»): asyncpg при недоступном сервере бросает
# ConnectionRefusedError/socket.gaierror (OSError) без обёртки SQLAlchemy.
_DB_UNAVAILABLE_ERRORS: Final = (OperationalError, InterfaceError, PoolTimeoutError, OSError)

SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def _is_db_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, _DB_UNAVAILABLE_ERRORS):
        return True
    return isinstance(exc, DBAPIError) and exc.connection_invalidated


def _describe_db_error(request: Request, exc: BaseException) -> str:
    """Текст для лога без деталей подключения (``Database.describe_error``, #73)."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return type(exc).__name__
    text: str = container.database.describe_error(exc)
    return text


class GuestRoute(APIRoute):
    """Маршрут гостевого API: ``Cache-Control: no-store`` на любом ответе и 503 ``try_again`` при
    недоступной БД. ``HTTPException`` и ``RequestValidationError`` обрабатываются здесь стандартными
    обработчиками FastAPI, чтобы заголовок попал и в ответы об ошибках."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guest_route_handler(request: Request) -> Response:
            try:
                response = await handler(request)
            except StarletteHTTPException as exc:
                response = await http_exception_handler(request, exc)
            except RequestValidationError as exc:
                response = await request_validation_exception_handler(request, exc)
            except Exception as exc:
                if not _is_db_unavailable(exc):
                    raise
                logger.warning(
                    "База данных недоступна для гостевого API: %s",
                    _describe_db_error(request, exc),
                    extra={"code": ErrorCode.TRY_AGAIN.value},
                )
                response = JSONResponse(
                    {"detail": {"code": ErrorCode.TRY_AGAIN.value}},
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            response.headers.update(NO_STORE_HEADERS)
            return response

        return guest_route_handler


router = APIRouter(prefix="/api/guest/v1", tags=["guest"], route_class=GuestRoute)

_SESSION_ERRORS: Final[dict[int | str, dict[str, object]]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ApiErrorBody,
        "description": "guest_session_required | guest_session_invalid | visit_closed",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiErrorBody, "description": "try_again"},
}


async def _check_entry_rate_limit(limiter: RateLimiter, host: str | None, limit: int) -> None:
    """``limit == 0`` — без лимита. Иначе ``limiter.hit(rate_key(ENTRY_RATE_SCOPE, "ip", client_ip_key(host)),
    limit=limit, window=ENTRY_RATE_WINDOW)``; не разрешено → 429 ``rate_limited`` с
    ``Retry-After = ceil(retry_after)`` (не меньше 1). Исключение самого лимитера (кроме
    ``CancelledError``) — fail-open: WARNING с именами классов исключений по цепочке, без текста (ADR-9.7)."""
    if limit == 0:
        return
    key = rate_key(ENTRY_RATE_SCOPE, "ip", client_ip_key(host))
    try:
        result = await limiter.hit(key, limit=limit, window=ENTRY_RATE_WINDOW)
    except Exception as exc:  # CancelledError — BaseException, не перехватывается
        logger.warning(
            "Лимит попыток входа гостя не проверен, вход без лимита: %s",
            _exception_chain_names(exc),
            extra={"component": "rate_limiter"},
        )
        return
    if result.allowed:
        return
    retry_after = max(1, math.ceil(result.retry_after))
    logger.info("Отказ во входе гостя", extra={"code": ErrorCode.RATE_LIMITED.value})
    raise api_error(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ErrorCode.RATE_LIMITED,
        {**NO_STORE_HEADERS, "Retry-After": str(retry_after)},
    )


def _exception_chain_names(exc: BaseException) -> str:
    """Имена классов по цепочке причин (``ConnectionError <- OSError``): текст исключения может
    содержать адрес Redis, он в лог не пишется."""
    names: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return " <- ".join(names)


async def enforce_entry_rate_limit(request: Request, settings: SettingsDep, limiter: RateLimiterDep) -> None:
    """Зависимость входа: лимит проверяется до валидации тела, поэтому считаются все попытки (ADR-9.7)."""
    host = request.client.host if request.client is not None else None
    await _check_entry_rate_limit(limiter, host, settings.guest_entry_rate_limit)


@router.post(
    "/entry",
    response_model=GuestEntryResponse,
    # Описание OpenAPI задано явно: docstring обработчика — для разработчиков, не для схемы API.
    description="Вход гостя по QR-токену стола: открывает визит или присоединяет к открытому, выдаёт cookie сессии.",
    dependencies=[Depends(enforce_entry_rate_limit)],
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ApiErrorBody, "description": "table_inactive"},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorBody, "description": "qr_invalid"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ApiErrorBody, "description": "rate_limited (+ Retry-After)"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiErrorBody, "description": "try_again"},
    },
)
async def enter(
    body: GuestEntryRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    codec: GuestSessionCodecDep,
    settings: SettingsDep,
) -> GuestEntryResponse:
    """Последовательность «Первый вход» arch:

    1. лимит попыток по IP — зависимость ``enforce_entry_rate_limit``;
    2. ``codec.decode(cookie)`` — claims для шага 2 выбора языка (может быть ``None``);
    3. ``entry.enter_table(..., accept_language=request.headers.get("accept-language"),
       reject_demo=settings.app_env is AppEnv.PROD)``: ``QrInvalidError`` → 404 ``qr_invalid``,
       ``TableInactiveError`` → 403 ``table_inactive``, ``VisitOpenConflictError`` → 503 ``try_again``;
    4. ``set_guest_cookie(response, codec.encode(result.claims), max_age=int(codec.ttl.total_seconds()),
       secure=settings.guest_cookie_secure_effective)``, ``Cache-Control: no-store``;
    5. ``_entry_response(result)``."""
    claims = codec.decode(request.cookies.get(GUEST_COOKIE_NAME))
    try:
        result = await guest_entry.enter_table(
            session,
            token=body.token,
            requested_lang=body.lang,
            session_claims=claims,
            accept_language=request.headers.get("accept-language"),
            reject_demo=settings.app_env is AppEnv.PROD,
        )
    except QrInvalidError:
        raise api_error(status.HTTP_404_NOT_FOUND, ErrorCode.QR_INVALID, NO_STORE_HEADERS) from None
    except TableInactiveError:
        raise api_error(status.HTTP_403_FORBIDDEN, ErrorCode.TABLE_INACTIVE, NO_STORE_HEADERS) from None
    except VisitOpenConflictError:
        logger.warning("Визит стола не удалось ни найти, ни открыть", extra={"code": ErrorCode.TRY_AGAIN.value})
        raise api_error(status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.TRY_AGAIN, NO_STORE_HEADERS) from None
    set_guest_cookie(
        response,
        codec.encode(result.claims),
        max_age=int(codec.ttl.total_seconds()),
        secure=settings.guest_cookie_secure_effective,
    )
    response.headers.update(NO_STORE_HEADERS)
    return _entry_response(result)


@router.get(
    "/session",
    response_model=GuestSessionResponse,
    description="Заведение, стол, визит и язык действующей гостевой сессии.",
    responses=_SESSION_ERRORS,
)
async def read_session(view: CurrentGuestView, response: Response) -> GuestSessionResponse:
    """``_session_response(view)`` + ``Cache-Control: no-store``. Cookie не переподписывается."""
    response.headers.update(NO_STORE_HEADERS)
    return _session_response(view)


@router.put(
    "/session/lang",
    response_model=GuestSessionResponse,
    description="Смена языка устройства гостя; cookie сессии переподписывается.",
    # 422 не переопределяется моделью: иначе OpenAPI потеряет схему ошибки валидации тела;
    # 422 lang_not_supported имеет тело ApiErrorBody (ADR-9.6).
    responses=_SESSION_ERRORS,
)
async def put_session_lang(
    body: GuestLangRequest,
    view: CurrentGuestView,
    response: Response,
    session: SessionDep,
    codec: GuestSessionCodecDep,
    settings: SettingsDep,
) -> GuestSessionResponse:
    """``entry.change_lang`` (``LangNotSupportedError`` → 422 ``lang_not_supported``) → новая cookie
    ``codec.encode(new_view.claims)`` с ``Max-Age = codec.remaining_seconds(claims)`` →
    ``_session_response(new_view)``. Только JSON-тело (CSRF: form/text — 422, Security arch)."""
    try:
        new_view = await guest_entry.change_lang(session, view, body.lang)
    except LangNotSupportedError:
        logger.info("Язык не поддерживается заведением", extra={"code": ErrorCode.LANG_NOT_SUPPORTED.value})
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.LANG_NOT_SUPPORTED, NO_STORE_HEADERS) from None
    set_guest_cookie(
        response,
        codec.encode(new_view.claims),
        max_age=codec.remaining_seconds(new_view.claims),
        secure=settings.guest_cookie_secure_effective,
    )
    response.headers.update(NO_STORE_HEADERS)
    return _session_response(new_view)


def _tenant_out(view: EntryResult | GuestVisitView) -> GuestTenantOut:
    languages = [Lang(value) for value in view.tenant.languages]
    return GuestTenantOut(
        name=view.tenant.name,
        languages=languages,
        default_lang=languages[0],
        currency=view.tenant.currency,
    )


def _table_out(view: EntryResult | GuestVisitView) -> GuestTableOut:
    return GuestTableOut.model_validate(view.table)


def _entry_response(result: EntryResult) -> GuestEntryResponse:
    """``GuestEntryResponse``: ``default_lang = tenant.languages[0]``, ``visit.is_new = result.created``,
    ``lang = result.lang``."""
    return GuestEntryResponse(
        tenant=_tenant_out(result),
        table=_table_out(result),
        visit=GuestEntryVisitOut(id=result.visit.id, opened_at=result.visit.opened_at, is_new=result.created),
        lang=result.lang,
    )


def _session_response(view: GuestVisitView) -> GuestSessionResponse:
    """``GuestSessionResponse`` из проверенной сессии; ``lang = view.lang``."""
    return GuestSessionResponse(
        tenant=_tenant_out(view),
        table=_table_out(view),
        visit=GuestVisitOut.model_validate(view.visit),
        lang=view.lang,
    )
