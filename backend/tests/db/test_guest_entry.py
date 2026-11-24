"""Вход гостя, визит, сессия и язык на настоящем PostgreSQL (#75–#83; ADR-9.2…9.6).

Сервисы ``app.guest`` — в транзакции теста (``db_session``, откат после теста). HTTP-сценарии —
приложение с ``get_session``, подменённым на ту же сессию: commit сервиса фиксирует SAVEPOINT.
Гонка двух входов (E-1) — на отдельных соединениях с настоящим commit и уборкой строк после теста.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.deps import get_session
from app.api.guest_auth import GUEST_COOKIE_NAME
from app.core.config import Settings
from app.core.scheduler import TaskRegistry
from app.guest import entry, tokens, visits
from app.guest.entry import enter_table, load_guest_context
from app.guest.errors import (
    GuestSessionInvalidError,
    LangNotSupportedError,
    QrInvalidError,
    TableInactiveError,
    TableNotFoundError,
    VisitClosedError,
)
from app.guest.session import GuestSessionCodec, epoch_micros, issue_claims
from app.main import create_app
from app.models.enums import Lang, VisitClosedBy
from app.models.tenant import Table, Tenant
from app.models.visit import Visit
from app.seed.data import DEMO_TENANT_ID, dev_token
from app.seed.loader import apply_seed
from tests.conftest import make_settings
from tests.db.factories import create_table, create_tenant, create_visit
from tests.doubles import make_fake_container

pytestmark = pytest.mark.db

ENTRY = "/api/guest/v1/entry"
SESSION = "/api/guest/v1/session"
LANG = "/api/guest/v1/session/lang"
PROD = {"app_env": "prod", "public_base_url": "https://menu.example.com"}


async def _enter(session: AsyncSession, token: str, **overrides: Any) -> entry.EntryResult:
    values: dict[str, Any] = {
        "token": token,
        "requested_lang": None,
        "session_claims": None,
        "accept_language": None,
        "reject_demo": False,
    }
    values.update(overrides)
    return await enter_table(session, **values)


async def _visit_count(session: AsyncSession, table_id: uuid.UUID, *, open_only: bool = False) -> int:
    statement = select(func.count()).select_from(Visit).where(Visit.table_id == table_id)
    if open_only:
        statement = statement.where(Visit.status == "open")
    return int((await session.execute(statement)).scalar_one())


async def _total_visits(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(Visit))).scalar_one())


async def _reload(session: AsyncSession, model: type[Any], obj_id: uuid.UUID) -> Any:
    return (
        await session.execute(select(model).where(model.id == obj_id).execution_options(populate_existing=True))
    ).scalar_one()


@pytest.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    return await create_tenant(db_session, name="Кафе А", languages=["az", "ru"])


@pytest.fixture
async def table(db_session: AsyncSession, tenant: Tenant) -> Table:
    return await create_table(db_session, tenant.id, name="Стол 7", qr_token=tokens.generate_qr_token())


# ================================================================ #75, #76: вход и присоединение


async def test_first_entry_opens_visit(db_session: AsyncSession, tenant: Tenant, table: Table) -> None:
    """AC-1: нет открытого визита — создаётся визит ``open`` с языком гостя; claims привязаны к столу."""
    result = await _enter(db_session, table.qr_token, accept_language="ru-RU,ru;q=0.9")
    assert result.created is True
    assert result.lang is Lang.RU
    assert (result.tenant.id, result.table.id) == (tenant.id, table.id)
    visit = await _reload(db_session, Visit, result.visit.id)
    assert (visit.status, visit.lang, visit.tenant_id, visit.table_id) == ("open", "ru", tenant.id, table.id)
    assert visit.opened_at.tzinfo is not None and visit.closed_at is None
    claims = result.claims
    assert (claims.tid, claims.tbl, claims.vid, claims.lang) == (tenant.id, table.id, visit.id, Lang.RU)
    assert claims.tia == epoch_micros(table.token_issued_at)


async def test_second_entry_joins_open_visit(db_session: AsyncSession, table: Table) -> None:
    """AC-2, FR-12: второй вход — тот же визит, ``is_new = false``, ``last_activity_at`` обновлён,
    ``visits.lang`` не меняется (меняет только явная смена языка)."""
    first = await _enter(db_session, table.qr_token, requested_lang=Lang.AZ)
    past = datetime.now(UTC) - timedelta(hours=3)
    await db_session.execute(update(Visit).where(Visit.id == first.visit.id).values(last_activity_at=past))
    second = await _enter(db_session, table.qr_token, requested_lang=Lang.RU)
    assert second.created is False
    assert second.visit.id == first.visit.id
    assert second.lang is Lang.RU  # язык устройства — свой
    visit = await _reload(db_session, Visit, first.visit.id)
    assert visit.lang == "az"
    assert visit.last_activity_at > past
    assert await _visit_count(db_session, table.id, open_only=True) == 1


async def test_reentry_keeps_language_of_same_table_cookie(db_session: AsyncSession, table: Table) -> None:
    """E-2 / FR-7 шаг 2: язык прежней cookie того же стола важнее Accept-Language."""
    first = await _enter(db_session, table.qr_token, requested_lang=Lang.RU)
    again = await _enter(db_session, table.qr_token, session_claims=first.claims, accept_language="az")
    assert again.lang is Lang.RU


async def test_cookie_of_other_table_does_not_set_language(
    db_session: AsyncSession, tenant: Tenant, table: Table
) -> None:
    other_table = await create_table(db_session, tenant.id, name="Стол 8")
    other = await _enter(db_session, other_table.qr_token, requested_lang=Lang.RU)
    result = await _enter(db_session, table.qr_token, session_claims=other.claims, accept_language="az-AZ")
    assert result.lang is Lang.AZ


async def test_default_language_of_tenant(db_session: AsyncSession) -> None:
    """E-11: без подходящего языка браузера — ``tenants.languages[0]``."""
    tenant = await create_tenant(db_session, languages=["ru", "az"])
    table = await create_table(db_session, tenant.id)
    result = await _enter(db_session, table.qr_token, accept_language="en-US,tr;q=0.5")
    assert result.lang is Lang.RU
    assert (await _reload(db_session, Visit, result.visit.id)).lang == "ru"


# ================================================================ #77, #78: недействительный токен


async def test_unknown_token_does_not_create_visit(db_session: AsyncSession, table: Table) -> None:
    before = await _total_visits(db_session)
    with pytest.raises(QrInvalidError):
        await _enter(db_session, tokens.generate_qr_token())
    with pytest.raises(QrInvalidError):
        await _enter(db_session, table.qr_token.swapcase())  # регистрозависим (E-4)
    assert await _total_visits(db_session) == before


async def test_inactive_table_is_refused(db_session: AsyncSession, tenant: Tenant) -> None:
    """E-5: отключённый стол — ``TableInactiveError``, визит не создаётся."""
    table = await create_table(db_session, tenant.id, is_active=False)
    with pytest.raises(TableInactiveError):
        await _enter(db_session, table.qr_token)
    assert await _visit_count(db_session, table.id) == 0


async def test_demo_tokens_rejected_only_with_reject_demo(db_session: AsyncSession) -> None:
    """AC-4 (#78), E-9: при ``reject_demo`` демо-токен — как неизвестный, визитов не прибавилось;
    без флага (dev/test) вход работает."""
    await apply_seed(db_session)
    before = await _total_visits(db_session)
    with pytest.raises(QrInvalidError):
        await _enter(db_session, dev_token(2), reject_demo=True)
    assert await _total_visits(db_session) == before
    result = await _enter(db_session, dev_token(2), reject_demo=False)
    assert result.tenant.id == DEMO_TENANT_ID


async def test_demo_session_is_invalid_with_reject_demo(db_session: AsyncSession) -> None:
    """E-10: действующая сессия демо-визита при prod — ``GuestSessionInvalidError``."""
    await apply_seed(db_session)
    result = await _enter(db_session, dev_token(2))
    assert (await load_guest_context(db_session, result.claims, reject_demo=False)).visit.id == result.visit.id
    with pytest.raises(GuestSessionInvalidError, match="demo"):
        await load_guest_context(db_session, result.claims, reject_demo=True)


# ================================================================ #80, #81: сессия по БД


async def test_load_guest_context_returns_view(db_session: AsyncSession, tenant: Tenant, table: Table) -> None:
    result = await _enter(db_session, table.qr_token)
    view = await load_guest_context(db_session, result.claims, reject_demo=False)
    assert (view.tenant.id, view.table.id, view.visit.id, view.lang) == (
        tenant.id,
        table.id,
        result.visit.id,
        result.lang,
    )


async def test_session_of_other_tenant_or_table_is_invalid(
    db_session: AsyncSession, tenant: Tenant, table: Table
) -> None:
    """E-14a, NFR-2: запрос фильтрует по ``tid``, ``vid``, ``tbl`` одновременно — подмена любого поля
    (даже при верной подписи) не открывает чужой визит."""
    other_tenant = await create_tenant(db_session, name="Кафе Б")
    other_table = await create_table(db_session, other_tenant.id)
    other_visit = (await _enter(db_session, other_table.qr_token)).visit
    own = (await _enter(db_session, table.qr_token)).claims
    second_table = await create_table(db_session, tenant.id, name="Стол 9")

    def forged(**changes: uuid.UUID) -> Any:
        return issue_claims(
            tenant_id=changes.get("tid", own.tid),
            table_id=changes.get("tbl", own.tbl),
            visit_id=changes.get("vid", own.vid),
            token_issued_at=table.token_issued_at,
            lang=Lang.RU,
        )

    for claims in (
        forged(tid=other_tenant.id),  # своё vid/tbl, чужое заведение
        forged(vid=other_visit.id),  # чужой визит при своём заведении
        forged(tid=other_tenant.id, vid=other_visit.id),  # чужой визит и заведение при своём столе
        forged(tbl=second_table.id),  # свой визит, другой стол того же заведения
        forged(vid=uuid.uuid4()),
    ):
        with pytest.raises(GuestSessionInvalidError, match="not_found"):
            await load_guest_context(db_session, claims, reject_demo=False)


async def test_closed_visit_session_and_new_visit(db_session: AsyncSession, tenant: Tenant, table: Table) -> None:
    """AC-7 (#81), E-7: после закрытия — ``VisitClosedError``; новый вход открывает новый визит,
    старый остаётся закрытым в истории."""
    first = await _enter(db_session, table.qr_token)
    assert await visits.close_visit(
        db_session, tenant_id=tenant.id, visit_id=first.visit.id, closed_by=VisitClosedBy.POS
    )
    with pytest.raises(VisitClosedError):
        await load_guest_context(db_session, first.claims, reject_demo=False)
    second = await _enter(db_session, table.qr_token)
    assert second.created is True and second.visit.id != first.visit.id
    old = await _reload(db_session, Visit, first.visit.id)
    assert (old.status, old.closed_by) == ("closed", "pos")
    assert await _visit_count(db_session, table.id) == 2
    assert await _visit_count(db_session, table.id, open_only=True) == 1


async def test_close_visit_is_idempotent_and_keeps_first_closer(
    db_session: AsyncSession, tenant: Tenant, table: Table
) -> None:
    """E-8: повторное закрытие ничего не меняет и ошибкой не считается."""
    visit = await create_visit(db_session, tenant.id, table.id)
    staff_id = uuid.uuid4()
    assert await visits.close_visit(
        db_session, tenant_id=tenant.id, visit_id=visit.id, closed_by=VisitClosedBy.STAFF, staff_id=staff_id
    )
    closed = await _reload(db_session, Visit, visit.id)
    closed_at = closed.closed_at
    assert (closed.status, closed.closed_by, closed.closed_by_staff_id) == ("closed", "staff", staff_id)
    assert closed_at is not None
    assert not await visits.close_visit(
        db_session, tenant_id=tenant.id, visit_id=visit.id, closed_by=VisitClosedBy.TIMEOUT
    )
    again = await _reload(db_session, Visit, visit.id)
    assert (again.closed_by, again.closed_at, again.closed_by_staff_id) == ("staff", closed_at, staff_id)


async def test_close_visit_filters_by_tenant(db_session: AsyncSession, table: Table, tenant: Tenant) -> None:
    visit = await create_visit(db_session, tenant.id, table.id)
    other = await create_tenant(db_session, name="Чужое")
    assert not await visits.close_visit(
        db_session, tenant_id=other.id, visit_id=visit.id, closed_by=VisitClosedBy.STAFF
    )
    assert (await _reload(db_session, Visit, visit.id)).status == "open"


async def test_close_visit_staff_id_only_for_staff(db_session: AsyncSession, tenant: Tenant, table: Table) -> None:
    visit = await create_visit(db_session, tenant.id, table.id)
    with pytest.raises(ValueError, match="closed_by=staff"):
        await visits.close_visit(
            db_session, tenant_id=tenant.id, visit_id=visit.id, closed_by=VisitClosedBy.POS, staff_id=uuid.uuid4()
        )


async def test_touch_visit_updates_only_open_visit_of_tenant(
    db_session: AsyncSession, tenant: Tenant, table: Table
) -> None:
    past = datetime.now(UTC) - timedelta(hours=5)
    visit = await create_visit(db_session, tenant.id, table.id, last_activity_at=past)
    other = await create_tenant(db_session, name="Чужое")
    await visits.touch_visit(db_session, tenant_id=other.id, visit_id=visit.id)
    assert (await _reload(db_session, Visit, visit.id)).last_activity_at == past
    await visits.touch_visit(db_session, tenant_id=tenant.id, visit_id=visit.id)
    assert (await _reload(db_session, Visit, visit.id)).last_activity_at > past
    await visits.close_visit(db_session, tenant_id=tenant.id, visit_id=visit.id, closed_by=VisitClosedBy.TIMEOUT)
    await db_session.execute(update(Visit).where(Visit.id == visit.id).values(last_activity_at=past))
    await visits.touch_visit(db_session, tenant_id=tenant.id, visit_id=visit.id)
    assert (await _reload(db_session, Visit, visit.id)).last_activity_at == past


async def test_inactive_table_and_reactivation_e20(db_session: AsyncSession, table: Table) -> None:
    """E-5, E-20: стол отключён — сессия недействительна; включён без перевыпуска — снова действует (Q-4)."""
    result = await _enter(db_session, table.qr_token)
    await db_session.execute(update(Table).where(Table.id == table.id).values(is_active=False))
    with pytest.raises(GuestSessionInvalidError, match="table_inactive"):
        await load_guest_context(db_session, result.claims, reject_demo=False)
    await db_session.execute(update(Table).where(Table.id == table.id).values(is_active=True))
    assert (await load_guest_context(db_session, result.claims, reject_demo=False)).visit.id == result.visit.id


# ================================================================ #79: перевыпуск токена


async def test_reissue_token(db_session: AsyncSession, tenant: Tenant, table: Table) -> None:
    """AC-5, E-6: новый токен (32 символа), новое ``token_issued_at``; старый — ``QrInvalidError``,
    старая сессия — недействительна; вход по новому — в тот же открытый визит."""
    old_token, old_issued = table.qr_token, table.token_issued_at
    first = await _enter(db_session, old_token)
    reissued = await tokens.reissue_table_token(db_session, tenant_id=tenant.id, table_id=table.id)
    assert reissued.id == table.id
    assert reissued.qr_token != old_token and len(reissued.qr_token) == 32
    assert tokens.is_valid_token_format(reissued.qr_token)
    assert reissued.token_issued_at > old_issued
    await db_session.commit()

    with pytest.raises(QrInvalidError):
        await _enter(db_session, old_token)
    with pytest.raises(GuestSessionInvalidError, match="token_reissued"):
        await load_guest_context(db_session, first.claims, reject_demo=False)
    again = await _enter(db_session, reissued.qr_token)
    assert again.created is False and again.visit.id == first.visit.id
    assert (await load_guest_context(db_session, again.claims, reject_demo=False)).visit.id == first.visit.id


async def test_reissue_twice_in_one_transaction_changes_issued_at(
    db_session: AsyncSession, tenant: Tenant, table: Table
) -> None:
    """``clock_timestamp()``: даже в одной транзакции каждый перевыпуск меняет ``token_issued_at``."""
    first = await tokens.reissue_table_token(db_session, tenant_id=tenant.id, table_id=table.id)
    first_issued = first.token_issued_at
    second = await tokens.reissue_table_token(db_session, tenant_id=tenant.id, table_id=table.id)
    assert second.token_issued_at > first_issued


async def test_reissue_filters_by_tenant(db_session: AsyncSession, table: Table) -> None:
    other = await create_tenant(db_session, name="Чужое")
    with pytest.raises(TableNotFoundError):
        await tokens.reissue_table_token(db_session, tenant_id=other.id, table_id=table.id)
    with pytest.raises(TableNotFoundError):
        await tokens.reissue_table_token(db_session, tenant_id=table.tenant_id, table_id=uuid.uuid4())
    assert (await _reload(db_session, Table, table.id)).qr_token == table.qr_token


async def test_reissue_retries_on_collision(
    db_session: AsyncSession, tenant: Tenant, table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-17: коллизия с токеном другого стола — повтор генерации в SAVEPOINT, не 500."""
    other = await create_table(db_session, tenant.id, name="Стол 2")
    fresh = tokens.generate_qr_token()
    generated = iter([other.qr_token, other.qr_token, fresh])
    monkeypatch.setattr(tokens, "generate_qr_token", lambda: next(generated))
    reissued = await tokens.reissue_table_token(db_session, tenant_id=tenant.id, table_id=table.id)
    assert reissued.qr_token == fresh
    assert (await _reload(db_session, Table, other.id)).qr_token == other.qr_token


async def test_reissue_gives_up_after_attempts(
    db_session: AsyncSession, tenant: Tenant, table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = await create_table(db_session, tenant.id, name="Стол 2")
    calls: list[int] = []

    def colliding() -> str:
        calls.append(1)
        return other.qr_token

    monkeypatch.setattr(tokens, "generate_qr_token", colliding)
    with pytest.raises(IntegrityError):
        await tokens.reissue_table_token(db_session, tenant_id=tenant.id, table_id=table.id)
    assert len(calls) == tokens.REISSUE_ATTEMPTS
    assert (await _reload(db_session, Table, table.id)).qr_token == table.qr_token  # сессия рабочая


# ================================================================ #83: смена языка


async def test_change_lang_updates_visit(db_session: AsyncSession, table: Table) -> None:
    result = await _enter(db_session, table.qr_token, requested_lang=Lang.RU)
    view = await load_guest_context(db_session, result.claims, reject_demo=False)
    past = datetime.now(UTC) - timedelta(hours=1)
    await db_session.execute(update(Visit).where(Visit.id == view.visit.id).values(last_activity_at=past))
    changed = await entry.change_lang(db_session, view, Lang.AZ)
    assert changed.lang is Lang.AZ and changed.claims.iat == view.claims.iat
    visit = await _reload(db_session, Visit, view.visit.id)
    assert visit.lang == "az" and visit.last_activity_at > past


async def test_change_lang_not_supported_by_tenant(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session, languages=["ru"])
    table = await create_table(db_session, tenant.id)
    result = await _enter(db_session, table.qr_token, requested_lang=Lang.AZ)
    assert result.lang is Lang.RU  # E-13: единственный язык заведения
    view = await load_guest_context(db_session, result.claims, reject_demo=False)
    with pytest.raises(LangNotSupportedError):
        await entry.change_lang(db_session, view, Lang.AZ)
    assert (await _reload(db_session, Visit, view.visit.id)).lang == "ru"


# ================================================================ HTTP с настоящей БД


def _app(db_session: AsyncSession, settings: Settings | None = None) -> FastAPI:
    settings = settings or make_settings()
    application = create_app(settings, registry=TaskRegistry())
    application.state.container = make_fake_container(settings)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_session] = session_override
    return application


@pytest.fixture
async def http(db_session: AsyncSession) -> AsyncIterator[Callable[..., AsyncClient]]:
    clients: list[AsyncClient] = []

    def factory(settings: Settings | None = None) -> AsyncClient:
        application = _app(db_session, settings)
        client = AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver")
        client.app = application  # type: ignore[attr-defined]
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


def _cookie(response: Response) -> dict[str, str]:
    """Cookie из ``Set-Cookie`` для следующего запроса (httpx не шлёт cookie с Path=/api/guest/ без хоста)."""
    value = response.cookies.get(GUEST_COOKIE_NAME)
    assert value
    return {"Cookie": f"{GUEST_COOKIE_NAME}={value}"}


async def test_http_full_flow_entry_session_lang(
    http: Callable[..., AsyncClient], db_session: AsyncSession, table: Table
) -> None:
    """AC-1, AC-6, AC-8, AC-9: вход по Accept-Language, чтение сессии, смена языка и повторное чтение."""
    client = http()
    entered = await client.post(
        ENTRY, json={"token": table.qr_token}, headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}
    )
    assert entered.status_code == 200
    assert entered.json()["lang"] == "ru" and entered.json()["visit"]["is_new"] is True
    cookie = _cookie(entered)

    session = await client.get(SESSION, headers=cookie)
    assert session.status_code == 200
    assert session.json()["visit"]["id"] == entered.json()["visit"]["id"]
    assert session.json()["table"] == {"name": "Стол 7", "type": "table"}

    changed = await client.put(LANG, json={"lang": "az"}, headers=cookie)
    assert changed.status_code == 200 and changed.json()["lang"] == "az"
    after = await client.get(SESSION, headers=_cookie(changed))
    assert after.json()["lang"] == "az"
    assert (await _reload(db_session, Visit, uuid.UUID(entered.json()["visit"]["id"]))).lang == "az"

    rejoin = await client.post(
        ENTRY, json={"token": table.qr_token}, headers={**_cookie(changed), "Accept-Language": "ru"}
    )
    assert rejoin.json()["visit"]["is_new"] is False and rejoin.json()["lang"] == "az"  # E-2


async def test_http_reissue_and_disable_break_sessions(
    http: Callable[..., AsyncClient], db_session: AsyncSession, tenant: Tenant, table: Table
) -> None:
    """R-Q3: перевыпуск и отключение стола обрывают сессии на следующем запросе."""
    client = http()
    entered = await client.post(ENTRY, json={"token": table.qr_token})
    cookie = _cookie(entered)
    old_token = table.qr_token
    reissued = await tokens.reissue_table_token(db_session, tenant_id=tenant.id, table_id=table.id)
    await db_session.commit()

    invalid = await client.get(SESSION, headers=cookie)
    assert (invalid.status_code, invalid.json()) == (401, {"detail": {"code": "guest_session_invalid"}})
    assert (await client.post(ENTRY, json={"token": old_token})).status_code == 404
    new_entry = await client.post(ENTRY, json={"token": reissued.qr_token})
    assert new_entry.json()["visit"]["id"] == entered.json()["visit"]["id"]  # визит принадлежит столу

    await db_session.execute(update(Table).where(Table.id == table.id).values(is_active=False))
    await db_session.commit()
    disabled = await client.get(SESSION, headers=_cookie(new_entry))
    assert disabled.json() == {"detail": {"code": "guest_session_invalid"}}
    refused = await client.post(ENTRY, json={"token": reissued.qr_token})
    assert (refused.status_code, refused.json()) == (403, {"detail": {"code": "table_inactive"}})
    assert "set-cookie" not in refused.headers
    assert "Кафе" not in refused.text and "Стол" not in refused.text


async def test_http_spa_page_does_not_open_visit(
    http: Callable[..., AsyncClient], db_session: AsyncSession, table: Table, tmp_path: Any
) -> None:
    """E-16: превью мессенджера / prefetch HTML ``/t/{token}`` не создаёт визит — его открывает только API входа."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    client = http(make_settings(serve_frontend=True, frontend_dist_dir=dist))
    preview_headers = {"User-Agent": "TelegramBot (like TwitterBot)", "Purpose": "prefetch", "Sec-Purpose": "prefetch"}
    for path in (f"/t/{table.qr_token}", f"/t/{table.qr_token}/menu"):
        page = await client.get(path, headers=preview_headers)
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert "set-cookie" not in page.headers
        assert (await client.head(path)).status_code == 200
    assert await _visit_count(db_session, table.id) == 0

    entered = await client.post(ENTRY, json={"token": table.qr_token})
    assert entered.status_code == 200
    assert await _visit_count(db_session, table.id) == 1


async def test_http_closed_visit(
    http: Callable[..., AsyncClient], db_session: AsyncSession, tenant: Tenant, table: Table
) -> None:
    """AC-7: 401 ``visit_closed`` без данных визита; новый вход — новый визит."""
    client = http()
    entered = await client.post(ENTRY, json={"token": table.qr_token})
    visit_id = uuid.UUID(entered.json()["visit"]["id"])
    await visits.close_visit(db_session, tenant_id=tenant.id, visit_id=visit_id, closed_by=VisitClosedBy.STAFF)
    await db_session.commit()
    closed = await client.get(SESSION, headers=_cookie(entered))
    assert (closed.status_code, closed.json()) == (401, {"detail": {"code": "visit_closed"}})
    assert str(visit_id) not in closed.text
    changed = await client.put(LANG, json={"lang": "ru"}, headers=_cookie(entered))
    assert changed.json() == {"detail": {"code": "visit_closed"}}
    again = await client.post(ENTRY, json={"token": table.qr_token}, headers=_cookie(entered))
    assert again.json()["visit"]["is_new"] is True and again.json()["visit"]["id"] != str(visit_id)


async def test_http_scanning_other_tenant_replaces_session(
    http: Callable[..., AsyncClient], db_session: AsyncSession, table: Table
) -> None:
    """E-3: QR другого заведения заменяет сессию; данные первого во втором не видны."""
    other_tenant = await create_tenant(db_session, name="Кафе Б", languages=["ru"])
    other_table = await create_table(db_session, other_tenant.id, name="Стол Б")
    client = http()
    first = await client.post(ENTRY, json={"token": table.qr_token})
    second = await client.post(ENTRY, json={"token": other_table.qr_token}, headers=_cookie(first))
    session = await client.get(SESSION, headers=_cookie(second))
    assert session.json()["tenant"]["name"] == "Кафе Б"
    assert "Кафе А" not in session.text and first.json()["visit"]["id"] not in session.text


async def test_http_demo_in_prod(http: Callable[..., AsyncClient], db_session: AsyncSession) -> None:
    """AC-4, E-10: в prod демо-токен отвечает как неизвестный; сессия демо-визита — 401 invalid."""
    await apply_seed(db_session)
    dev_client = http()
    dev_entry = await dev_client.post(ENTRY, json={"token": dev_token(2)})
    assert dev_entry.status_code == 200  # E-9
    prod_client = http(make_settings(**PROD))
    before = await _total_visits(db_session)
    demo = await prod_client.post(ENTRY, json={"token": dev_token(3)})
    unknown = await prod_client.post(ENTRY, json={"token": tokens.generate_qr_token()})
    assert demo.status_code == unknown.status_code == 404
    assert demo.content == unknown.content
    assert dict(demo.headers) == dict(unknown.headers)
    assert await _total_visits(db_session) == before

    # Кодек prod-приложения с тем же секретом: cookie dev-входа подписана верно, но заведение демо.
    prod_codec: GuestSessionCodec = prod_client.app.state.guest_session_codec  # type: ignore[attr-defined]
    assert prod_codec.decode(dev_entry.cookies[GUEST_COOKIE_NAME]) is not None
    session = await prod_client.get(SESSION, headers=_cookie(dev_entry))
    assert (session.status_code, session.json()) == (401, {"detail": {"code": "guest_session_invalid"}})


# ================================================================ E-1: гонка входов (настоящий commit)


@pytest.fixture
async def committed(migrated_database: str) -> AsyncIterator[tuple[Any, list[uuid.UUID]]]:
    """Движок без внешней транзакции и уборка зафиксированных строк заведений теста."""
    engine = create_async_engine(migrated_database, pool_size=10)
    tenant_ids: list[uuid.UUID] = []
    try:
        yield engine, tenant_ids
    finally:
        async with engine.begin() as connection:
            if tenant_ids:
                await connection.execute(delete(Visit).where(Visit.tenant_id.in_(tenant_ids)))
                await connection.execute(delete(Table).where(Table.tenant_id.in_(tenant_ids)))
                await connection.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        await engine.dispose()


async def test_concurrent_entries_open_exactly_one_visit(committed: tuple[Any, list[uuid.UUID]]) -> None:
    """E-1 (#76): одновременные входы к столам без визита — ровно один открытый визит на стол,
    все гости в нём; ``uq_visits_open_table`` не превращается в 500."""
    engine, tenant_ids = committed
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        tenant = await create_tenant(setup, name="Гонка")
        tenant_ids.append(tenant.id)
        tables = [await create_table(setup, tenant.id, name=f"Стол {n}") for n in range(5)]
        await setup.commit()

    async def scan(token: str) -> entry.EntryResult:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await _enter(session, token)

    devices = 4
    results = await asyncio.gather(*(scan(t.qr_token) for t in tables for _ in range(devices)))

    async with AsyncSession(engine) as check:
        for index, table in enumerate(tables):
            per_table = results[index * devices : (index + 1) * devices]
            assert len({r.visit.id for r in per_table}) == 1
            assert sum(r.created for r in per_table) == 1
            assert await _visit_count(check, table.id, open_only=True) == 1
            assert await _visit_count(check, table.id) == 1


async def test_insert_conflict_joins_visit_of_parallel_transaction(committed: tuple[Any, list[uuid.UUID]]) -> None:
    """ADR-9.3, детерминированно: вторая транзакция ждёт на ``uq_visits_open_table``, после commit
    первой получает пустой ``RETURNING`` (DO NOTHING) и присоединяется к её визиту, без 500."""
    engine, tenant_ids = committed
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        tenant = await create_tenant(setup, name="Гонка 2")
        tenant_ids.append(tenant.id)
        table = await create_table(setup, tenant.id)
        await setup.commit()

    async with (
        AsyncSession(engine, expire_on_commit=False) as first,
        AsyncSession(engine, expire_on_commit=False) as second,
    ):
        visit_a, created_a = await visits.get_or_open_visit(first, tenant_id=tenant.id, table_id=table.id, lang=Lang.AZ)
        waiting = asyncio.create_task(
            visits.get_or_open_visit(second, tenant_id=tenant.id, table_id=table.id, lang=Lang.RU)
        )
        await asyncio.sleep(0.5)
        assert not waiting.done()  # INSERT второй транзакции ждёт commit первой
        await first.commit()
        visit_b, created_b = await asyncio.wait_for(waiting, timeout=10)
        await second.commit()

    assert (created_a, created_b) == (True, False)
    assert visit_b.id == visit_a.id
    assert visit_b.lang == "az"
