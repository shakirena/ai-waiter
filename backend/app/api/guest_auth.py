"""Гостевая сессия в HTTP-слое: cookie ``aiw_guest`` и зависимость ``current_guest`` (#9, ADR-9.2, ADR-9.7).

Использование в гостевых API #10–#12::

    async def handler(guest: CurrentGuest, session: SessionDep) -> ...:
        ...  # все запросы — по guest.tenant_id и guest.visit_id; tenant_id из клиента не принимается

Ответы 401: ``guest_session_required`` (cookie нет, повреждена, неверная подпись, истёк TTL),
``guest_session_invalid`` (``GuestSessionInvalidError``), ``visit_closed`` (``VisitClosedError``).
Cookie, токен и ``Accept-Language`` в лог не пишутся.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, HTTPException, Request, Response, status

from app.api.deps import SessionDep, get_app_settings
from app.api.errors import ErrorCode, api_error
from app.core.config import AppEnv, Settings
from app.guest import entry as guest_entry
from app.guest.entry import GuestVisitView
from app.guest.errors import GuestSessionInvalidError, VisitClosedError
from app.guest.session import GuestSessionCodec
from app.models.enums import Lang

logger = logging.getLogger(__name__)

GUEST_COOKIE_NAME: Final = "aiw_guest"
GUEST_COOKIE_PATH: Final = "/api/guest/"
GUEST_COOKIE_SAMESITE: Final = "strict"
# Значение client_ip_key для отсутствующего или нераспознанного адреса.
UNKNOWN_CLIENT_IP: Final = "unknown"
IPV6_RATE_PREFIX: Final = 64
NO_STORE: Final = {"Cache-Control": "no-store"}


@dataclass(frozen=True, slots=True)
class GuestContext:
    """Гость текущего запроса (arch «Зависимость current_guest»)."""

    tenant_id: uuid.UUID
    table_id: uuid.UUID
    visit_id: uuid.UUID
    lang: Lang
    price_tier: str  # тариф стола — цены меню #10
    languages: tuple[Lang, ...]
    currency: str


def get_guest_session_codec(request: Request) -> GuestSessionCodec:
    """``request.app.state.guest_session_codec`` — его создаёт ``create_app`` (``build_guest_session_codec``)."""
    codec: GuestSessionCodec = request.app.state.guest_session_codec
    return codec


def _session_refused(code: ErrorCode, reason: str | None = None) -> HTTPException:
    """INFO об отказе (только код и причина, без cookie) и 401 с ``Cache-Control: no-store``."""
    extra: dict[str, object] = {"code": code.value}
    if reason:
        extra["reason"] = reason
    logger.info("Гостевая сессия отклонена", extra=extra)
    return api_error(status.HTTP_401_UNAUTHORIZED, code, NO_STORE)


GuestSessionCodecDep = Annotated[GuestSessionCodec, Depends(get_guest_session_codec)]


async def current_guest_view(
    request: Request,
    session: SessionDep,
    codec: GuestSessionCodecDep,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> GuestVisitView:
    """``codec.decode(request.cookies.get(GUEST_COOKIE_NAME))`` → ``None`` — 401 ``guest_session_required``;
    затем ``entry.load_guest_context(session, claims, reject_demo=settings.app_env is AppEnv.PROD)``:
    ``GuestSessionInvalidError`` → 401 ``guest_session_invalid``, ``VisitClosedError`` → 401 ``visit_closed``.
    Ошибки — через ``api_error`` с ``Cache-Control: no-store``."""
    claims = codec.decode(request.cookies.get(GUEST_COOKIE_NAME))
    if claims is None:
        raise _session_refused(ErrorCode.GUEST_SESSION_REQUIRED)
    try:
        return await guest_entry.load_guest_context(session, claims, reject_demo=settings.app_env is AppEnv.PROD)
    except GuestSessionInvalidError as exc:
        raise _session_refused(ErrorCode.GUEST_SESSION_INVALID, str(exc)) from None
    except VisitClosedError:
        raise _session_refused(ErrorCode.VISIT_CLOSED) from None


CurrentGuestView = Annotated[GuestVisitView, Depends(current_guest_view)]


async def current_guest(view: CurrentGuestView) -> GuestContext:
    """``GuestContext`` из проверенной сессии: ``price_tier`` — ``view.table.price_tier``,
    ``languages`` — ``tuple(Lang(x) for x in view.tenant.languages)``, ``lang`` — ``view.lang``.
    FastAPI кэширует ``current_guest_view`` в пределах запроса: запрос в БД один."""
    return GuestContext(
        tenant_id=view.tenant.id,
        table_id=view.table.id,
        visit_id=view.visit.id,
        lang=view.lang,
        price_tier=view.table.price_tier,
        languages=tuple(Lang(value) for value in view.tenant.languages),
        currency=view.tenant.currency,
    )


CurrentGuest = Annotated[GuestContext, Depends(current_guest)]


def set_guest_cookie(response: Response, value: str, *, max_age: int, secure: bool) -> None:
    """``Set-Cookie: aiw_guest=<value>; HttpOnly; SameSite=Strict; Path=/api/guest/; Max-Age=<max_age>``
    и ``Secure`` при ``secure`` (``settings.guest_cookie_secure_effective``). ``Domain`` не задаётся
    (host-only), префикс ``__Host-`` не используется (ADR-9.2)."""
    response.set_cookie(
        GUEST_COOKIE_NAME,
        value,
        max_age=max_age,
        path=GUEST_COOKIE_PATH,
        secure=secure,
        httponly=True,
        samesite=GUEST_COOKIE_SAMESITE,
    )


def client_ip_key(host: str | None) -> str:
    """Часть ключа ``rate_key`` для IP клиента (ADR-9.7), без ``:`` и пробелов.

    IPv4 — как есть (``ipaddress`` нормализует); IPv6 — префикс /``IPV6_RATE_PREFIX``:
    ``ip_network(f"{ip}/64", strict=False).network_address.exploded`` с заменой ``:`` на ``-``;
    IPv4-mapped IPv6 — как IPv4; ``None``, пусто или не адрес — ``UNKNOWN_CLIENT_IP``.
    Зона IPv6 (``%eth0``) в ключ не попадает: префикс считается по числовому значению адреса."""
    if not host:
        return UNKNOWN_CLIENT_IP
    try:
        address = ipaddress.ip_address(host.strip())
    except ValueError:
        return UNKNOWN_CLIENT_IP
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        host_bits = 128 - IPV6_RATE_PREFIX
        network = ipaddress.IPv6Network((int(address) >> host_bits << host_bits, IPV6_RATE_PREFIX))
        return network.network_address.exploded.replace(":", "-")
    return str(address)
