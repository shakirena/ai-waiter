"""Сценарий входа гостя и контекст гостя по сессии (#9; ADR-9.1, 9.2, 9.4, 9.6; ТЗ FR-1, FR-2, FR-14a).

- ``enter_table`` — вход по QR-токену: стол → язык → get-or-open визита → **commit** (DEC-007).
  Cookie выставляет HTTP-слой по ``EntryResult``.
- ``load_guest_context`` — проверка действующей сессии по БД одним запросом (для ``current_guest``).
- ``change_lang`` — смена языка устройства (``PUT /session/lang``), commit.

Демо-заведение в prod отвергается сравнением ``tenant_id`` с ``app.seed.data.DEMO_TENANT_ID``
(запроса в БД не добавляет); флаг ``reject_demo`` передаёт вызывающий
(``settings.app_env is AppEnv.PROD``), ``Settings`` модуль не читает. Все запросы — с ``tenant_id``.
В лог — только ``tenant_id``/``table_id``, без токена и cookie.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.guest.session import GuestSessionClaims
from app.models.enums import Lang
from app.models.tenant import Table, Tenant
from app.models.visit import Visit


@dataclass(frozen=True, slots=True)
class EntryResult:
    """Итог входа: данные для ``GuestEntryResponse`` и claims новой cookie."""

    tenant: Tenant
    table: Table
    visit: Visit
    created: bool  # визит открыт этим входом (visit.is_new)
    lang: Lang  # язык устройства (resolve_entry_lang)
    claims: GuestSessionClaims


@dataclass(frozen=True, slots=True)
class GuestVisitView:
    """Действующая сессия, проверенная по БД: из неё ``app.api.guest_auth`` строит ``GuestContext``,
    а ``GET /session`` — ``GuestSessionResponse``."""

    tenant: Tenant
    table: Table
    visit: Visit
    claims: GuestSessionClaims

    @property
    def lang(self) -> Lang:
        return self.claims.lang

    def with_lang(self, lang: Lang) -> GuestVisitView:
        """Копия с ``claims.lang = lang`` (``iat`` прежний — смена языка не продлевает сессию)."""
        return dataclasses.replace(self, claims=dataclasses.replace(self.claims, lang=lang))


async def find_table_by_token(session: AsyncSession, token: str) -> tuple[Table, Tenant] | None:
    """``SELECT tables JOIN tenants WHERE tables.qr_token = :token`` — поиск по ``uq_tables_qr_token``.

    Единственный запрос без фильтра по ``tenant_id``: заведение определяется самим токеном (CLAUDE.md
    «Мультиарендность»). Формат токена здесь не проверяется — это делает ``enter_table``."""
    raise NotImplementedError


async def enter_table(
    session: AsyncSession,
    *,
    token: str,
    requested_lang: Lang | None,
    session_claims: GuestSessionClaims | None,
    accept_language: str | None,
    reject_demo: bool,
) -> EntryResult:
    """Вход по QR-токену (последовательность «Первый вход» arch):

    1. ``tokens.is_valid_token_format`` — нет → ``QrInvalidError`` без запроса в БД;
    2. ``find_table_by_token`` — нет, или ``reject_demo`` и ``tenant.id == DEMO_TENANT_ID`` →
       ``QrInvalidError``; ``table.is_active = false`` → ``TableInactiveError``;
    3. ``lang.resolve_entry_lang``; ``session_lang`` — ``session_claims.lang``, только если
       ``claims.tid == tenant.id`` и ``claims.tbl == table.id``;
    4. ``visits.get_or_open_visit`` (``VisitOpenConflictError`` пробрасывается);
    5. ``session.commit()``; ``claims`` — ``session.issue_claims`` (``tia`` из ``table.token_issued_at``).

    Повторный вход идемпотентен: тот же открытый визит, ``created=False``. ``visits.lang`` найденного
    визита при входе не меняется (меняет только явная смена языка, ADR-9.4)."""
    raise NotImplementedError


async def load_guest_context(session: AsyncSession, claims: GuestSessionClaims, *, reject_demo: bool) -> GuestVisitView:
    """Один запрос (ADR-9.2, шаг 3)::

        SELECT … FROM visits v
          JOIN tables t ON t.tenant_id = v.tenant_id AND t.id = v.table_id
          JOIN tenants n ON n.id = v.tenant_id
         WHERE v.tenant_id = :tid AND v.id = :vid AND v.table_id = :tbl

    Строки нет; ``reject_demo`` и ``tid == DEMO_TENANT_ID``; ``t.is_active = false``;
    ``epoch_micros(t.token_issued_at) != claims.tia`` → ``GuestSessionInvalidError``.
    ``v.status != 'open'`` → ``VisitClosedError``. Демо-проверка — до запроса. Только чтение, без commit."""
    raise NotImplementedError


async def change_lang(session: AsyncSession, view: GuestVisitView, lang: Lang) -> GuestVisitView:
    """Смена языка устройства (ADR-9.4): ``lang`` не в ``view.tenant.languages`` → ``LangNotSupportedError``;
    иначе ``visits.set_visit_lang`` + ``session.commit()`` и ``view.with_lang(lang)`` (новую cookie
    подписывает HTTP-слой)."""
    raise NotImplementedError
