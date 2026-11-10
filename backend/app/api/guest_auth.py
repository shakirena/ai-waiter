"""Гостевая сессия в HTTP-слое: cookie ``aiw_guest`` и зависимость ``current_guest`` (#9, ADR-9.2, ADR-9.7).

Использование в гостевых API #10–#12::

    async def handler(guest: CurrentGuest, session: SessionDep) -> ...:
        ...  # все запросы — по guest.tenant_id и guest.visit_id; tenant_id из клиента не принимается

Ответы 401: ``guest_session_required`` (cookie нет, повреждена, неверная подпись, истёк TTL),
``guest_session_invalid`` (``GuestSessionInvalidError``), ``visit_closed`` (``VisitClosedError``).
Cookie, токен и ``Accept-Language`` в лог не пишутся.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Request, Response

from app.api.deps import SessionDep, get_app_settings
from app.core.config import Settings
from app.guest.entry import GuestVisitView
from app.guest.session import GuestSessionCodec
from app.models.enums import Lang

GUEST_COOKIE_NAME: Final = "aiw_guest"
GUEST_COOKIE_PATH: Final = "/api/guest/"
GUEST_COOKIE_SAMESITE: Final = "strict"
# Значение client_ip_key для отсутствующего или нераспознанного адреса.
UNKNOWN_CLIENT_IP: Final = "unknown"
IPV6_RATE_PREFIX: Final = 64


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
    raise NotImplementedError


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
    raise NotImplementedError


CurrentGuestView = Annotated[GuestVisitView, Depends(current_guest_view)]


async def current_guest(view: CurrentGuestView) -> GuestContext:
    """``GuestContext`` из проверенной сессии: ``price_tier`` — ``view.table.price_tier``,
    ``languages`` — ``tuple(Lang(x) for x in view.tenant.languages)``, ``lang`` — ``view.lang``.
    FastAPI кэширует ``current_guest_view`` в пределах запроса: запрос в БД один."""
    raise NotImplementedError


CurrentGuest = Annotated[GuestContext, Depends(current_guest)]


def set_guest_cookie(response: Response, value: str, *, max_age: int, secure: bool) -> None:
    """``Set-Cookie: aiw_guest=<value>; HttpOnly; SameSite=Strict; Path=/api/guest/; Max-Age=<max_age>``
    и ``Secure`` при ``secure`` (``settings.guest_cookie_secure_effective``). ``Domain`` не задаётся
    (host-only), префикс ``__Host-`` не используется (ADR-9.2)."""
    raise NotImplementedError


def client_ip_key(host: str | None) -> str:
    """Часть ключа ``rate_key`` для IP клиента (ADR-9.7), без ``:`` и пробелов.

    IPv4 — как есть (``ipaddress`` нормализует); IPv6 — префикс /``IPV6_RATE_PREFIX``:
    ``ip_network(f"{ip}/64", strict=False).network_address.exploded`` с заменой ``:`` на ``-``;
    IPv4-mapped IPv6 — как IPv4; ``None``, пусто или не адрес — ``UNKNOWN_CLIENT_IP``."""
    raise NotImplementedError
