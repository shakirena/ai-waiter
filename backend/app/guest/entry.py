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
import logging
from dataclasses import dataclass
from typing import Final

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.guest import visits
from app.guest.errors import (
    GuestSessionInvalidError,
    LangNotSupportedError,
    QrInvalidError,
    TableInactiveError,
    VisitClosedError,
)
from app.guest.lang import resolve_entry_lang
from app.guest.session import GuestSessionClaims, epoch_micros, issue_claims
from app.guest.tokens import is_valid_token_format
from app.models.enums import Lang, VisitStatus
from app.models.tenant import Table, Tenant
from app.models.visit import Visit
from app.seed.data import DEMO_TENANT_ID

logger = logging.getLogger(__name__)

# Причины отказа — только для лога сервера; гостю все варианты qr_invalid отвечают одинаково (ADR-9.6).
REASON_FORMAT: Final = "format"
REASON_UNKNOWN: Final = "unknown"
REASON_DEMO: Final = "demo"
REASON_NOT_FOUND: Final = "not_found"
REASON_TABLE_INACTIVE: Final = "table_inactive"
REASON_TOKEN_REISSUED: Final = "token_reissued"  # noqa: S105 — причина отказа, не секрет


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
    statement = select(Table, Tenant).join(Tenant, Tenant.id == Table.tenant_id).where(Table.qr_token == token)
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        return None
    return row[0], row[1]


def _refuse_entry(code: str, reason: str, *, tenant_id: object = None, table_id: object = None) -> None:
    """INFO об отказе входа: машинный код и причина, ``tenant_id``/``table_id`` — если известны.
    Токена, cookie и ``Accept-Language`` в записи нет (NFR-3)."""
    extra: dict[str, object] = {"code": code, "reason": reason}
    if tenant_id is not None:
        extra["tenant_id"] = str(tenant_id)
    if table_id is not None:
        extra["table_id"] = str(table_id)
    logger.info("Отказ во входе гостя", extra=extra)


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
    if not is_valid_token_format(token):
        _refuse_entry("qr_invalid", REASON_FORMAT)
        raise QrInvalidError
    found = await find_table_by_token(session, token)
    if found is None:
        _refuse_entry("qr_invalid", REASON_UNKNOWN)
        raise QrInvalidError
    table, tenant = found
    if reject_demo and tenant.id == DEMO_TENANT_ID:
        _refuse_entry("qr_invalid", REASON_DEMO, tenant_id=tenant.id, table_id=table.id)
        raise QrInvalidError
    if not table.is_active:
        _refuse_entry("table_inactive", REASON_TABLE_INACTIVE, tenant_id=tenant.id, table_id=table.id)
        raise TableInactiveError

    session_lang: Lang | None = None
    if session_claims is not None and session_claims.tid == tenant.id and session_claims.tbl == table.id:
        session_lang = session_claims.lang
    lang = resolve_entry_lang(
        requested=requested_lang,
        session_lang=session_lang,
        accept_language=accept_language,
        languages=tenant.languages,
    )
    visit, created = await visits.get_or_open_visit(session, tenant_id=tenant.id, table_id=table.id, lang=lang)
    await session.commit()

    claims = issue_claims(
        tenant_id=tenant.id,
        table_id=table.id,
        visit_id=visit.id,
        token_issued_at=table.token_issued_at,
        lang=lang,
    )
    logger.info(
        "Вход гостя",
        extra={
            "tenant_id": str(tenant.id),
            "table_id": str(table.id),
            "visit_id": str(visit.id),
            "is_new": created,
            "lang": lang.value,
        },
    )
    return EntryResult(tenant=tenant, table=table, visit=visit, created=created, lang=lang, claims=claims)


async def load_guest_context(session: AsyncSession, claims: GuestSessionClaims, *, reject_demo: bool) -> GuestVisitView:
    """Один запрос (ADR-9.2, шаг 3)::

        SELECT … FROM visits v
          JOIN tables t ON t.tenant_id = v.tenant_id AND t.id = v.table_id
          JOIN tenants n ON n.id = v.tenant_id
         WHERE v.tenant_id = :tid AND v.id = :vid AND v.table_id = :tbl

    Строки нет; ``reject_demo`` и ``tid == DEMO_TENANT_ID``; ``t.is_active = false``;
    ``epoch_micros(t.token_issued_at) != claims.tia`` → ``GuestSessionInvalidError``.
    ``v.status != 'open'`` → ``VisitClosedError``. Демо-проверка — до запроса. Только чтение, без commit.

    Текст ``GuestSessionInvalidError`` — причина для лога (``REASON_*``), без данных визита."""
    if reject_demo and claims.tid == DEMO_TENANT_ID:
        raise GuestSessionInvalidError(REASON_DEMO)
    statement = (
        select(Visit, Table, Tenant)
        .join(Table, and_(Table.tenant_id == Visit.tenant_id, Table.id == Visit.table_id))
        .join(Tenant, Tenant.id == Visit.tenant_id)
        .where(Visit.tenant_id == claims.tid, Visit.id == claims.vid, Visit.table_id == claims.tbl)
    )
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise GuestSessionInvalidError(REASON_NOT_FOUND)
    visit, table, tenant = row[0], row[1], row[2]
    if visit.status != VisitStatus.OPEN.value:
        raise VisitClosedError
    if not table.is_active:
        raise GuestSessionInvalidError(REASON_TABLE_INACTIVE)
    if epoch_micros(table.token_issued_at) != claims.tia:
        raise GuestSessionInvalidError(REASON_TOKEN_REISSUED)
    return GuestVisitView(tenant=tenant, table=table, visit=visit, claims=claims)


async def change_lang(session: AsyncSession, view: GuestVisitView, lang: Lang) -> GuestVisitView:
    """Смена языка устройства (ADR-9.4): ``lang`` не в ``view.tenant.languages`` → ``LangNotSupportedError``;
    иначе ``visits.set_visit_lang`` + ``session.commit()`` и ``view.with_lang(lang)`` (новую cookie
    подписывает HTTP-слой)."""
    if lang.value not in view.tenant.languages:
        raise LangNotSupportedError
    await visits.set_visit_lang(session, tenant_id=view.tenant.id, visit_id=view.visit.id, lang=lang)
    await session.commit()
    logger.info(
        "Гость сменил язык",
        extra={"tenant_id": str(view.tenant.id), "visit_id": str(view.visit.id), "lang": lang.value},
    )
    return view.with_lang(lang)
