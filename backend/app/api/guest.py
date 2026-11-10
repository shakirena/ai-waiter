"""Гостевой API ``/api/guest/v1`` (#9, ADR-9.1, 9.2, 9.4, 9.6, 9.7; ТЗ FR-1, FR-2, NFR-4).

- ``POST /entry`` — вход по QR-токену (токен в теле, не в пути: путь пишется в access-лог);
- ``GET /session`` — данные действующей сессии (после перезагрузки страницы);
- ``PUT /session/lang`` — смена языка устройства, cookie переподписывается.

Все ответы, включая ошибки, — ``Cache-Control: no-store``. Подключение роутера в ``create_app``
(``app.include_router(guest.router)``) и ``app.state.guest_session_codec`` — developer (#9).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import SessionDep, get_app_settings, get_rate_limiter
from app.api.errors import ApiErrorBody
from app.api.guest_auth import CurrentGuestView, GuestSessionCodecDep
from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.guest.entry import EntryResult, GuestVisitView
from app.schemas.guest import GuestEntryRequest, GuestEntryResponse, GuestLangRequest, GuestSessionResponse

router = APIRouter(prefix="/api/guest/v1", tags=["guest"])

ENTRY_RATE_SCOPE: Final = "guest_entry"
ENTRY_RATE_WINDOW: Final = timedelta(seconds=60)
NO_STORE_HEADERS: Final = {"Cache-Control": "no-store"}

SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]

_SESSION_ERRORS: Final[dict[int | str, dict[str, object]]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ApiErrorBody,
        "description": "guest_session_required | guest_session_invalid | visit_closed",
    },
}


@router.post(
    "/entry",
    response_model=GuestEntryResponse,
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
    limiter: RateLimiterDep,
) -> GuestEntryResponse:
    """Последовательность «Первый вход» arch:

    1. ``_check_entry_rate_limit(limiter, request.client.host, settings.guest_entry_rate_limit)``;
    2. ``codec.decode(cookie)`` — claims для шага 2 выбора языка (может быть ``None``);
    3. ``entry.enter_table(..., accept_language=request.headers.get("accept-language"),
       reject_demo=settings.app_env is AppEnv.PROD)``: ``QrInvalidError`` → 404 ``qr_invalid``,
       ``TableInactiveError`` → 403 ``table_inactive``, ``VisitOpenConflictError`` → 503 ``try_again``;
    4. ``set_guest_cookie(response, codec.encode(result.claims), max_age=int(codec.ttl.total_seconds()),
       secure=settings.guest_cookie_secure_effective)``, ``Cache-Control: no-store``;
    5. ``_entry_response(result)``."""
    raise NotImplementedError


@router.get("/session", response_model=GuestSessionResponse, responses=_SESSION_ERRORS)
async def read_session(view: CurrentGuestView, response: Response) -> GuestSessionResponse:
    """``_session_response(view)`` + ``Cache-Control: no-store``. Cookie не переподписывается."""
    raise NotImplementedError


@router.put(
    "/session/lang",
    response_model=GuestSessionResponse,
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
    raise NotImplementedError


async def _check_entry_rate_limit(limiter: RateLimiter, host: str | None, limit: int) -> None:
    """``limit == 0`` — без лимита. Иначе ``limiter.hit(rate_key(ENTRY_RATE_SCOPE, "ip", client_ip_key(host)),
    limit=limit, window=ENTRY_RATE_WINDOW)``; не разрешено → 429 ``rate_limited`` с
    ``Retry-After = ceil(retry_after)`` (не меньше 1). Исключение самого лимитера (кроме
    ``CancelledError``) — fail-open: WARNING с именами классов исключений по цепочке, без текста (ADR-9.7)."""
    raise NotImplementedError


def _entry_response(result: EntryResult) -> GuestEntryResponse:
    """``GuestEntryResponse``: ``default_lang = tenant.languages[0]``, ``visit.is_new = result.created``,
    ``lang = result.lang``."""
    raise NotImplementedError


def _session_response(view: GuestVisitView) -> GuestSessionResponse:
    """``GuestSessionResponse`` из проверенной сессии; ``lang = view.lang``."""
    raise NotImplementedError
