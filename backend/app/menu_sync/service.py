"""Применение снимка меню в ядре (ADR-8.1, ADR-8.4, ADR-8.5, DEC-011). Единый путь для файла и ``PUT /menu``.

``apply_menu_snapshot`` выполняется внутри транзакции вызывающего и сам её не фиксирует (как
``apply_seed``): CLI оборачивает вызов в ``session.begin()``, ``PUT /menu`` (#16) — так же,
db-тесты — в откатываемую транзакцию. Порядок шагов (в скобках — story, которая добавляет шаг):

1. (#62) ``pg_try_advisory_xact_lock(MENU_SYNC_LOCK_NAMESPACE, hashtext(tenant_id::text))`` — не
   получилось → ``MenuSyncBusyError`` (параллельная синхронизация того же заведения; тот же
   lock берёт ``PUT /stoplist`` в #16, потому что пишет ``menu_items.is_available``);
2. (#62) заведение по ``tenant_id`` (нет → ``TenantNotFoundError``), ``check_snapshot``,
   ``resolve_currency``; ошибки → итог ``rejected``, ничего не пишется;
3. (#63) ``snapshot_hash``; хеш равен ``last_applied_hash`` и нет ``force`` → итог ``unchanged``,
   данные меню не трогаются (INT-1);
4. (#62) ``load_current_menu`` → ``plan_menu_sync``; ошибки плана → ``rejected``;
5. (#62) не ``dry_run`` → пакетная запись плана (``INSERT … ON CONFLICT (tenant_id, external_id) DO UPDATE``
   для категорий и позиций, ``(menu_item_id, price_tier)`` для цен; ``updated_at`` — явно);
6. (#63) не ``dry_run`` → строка ``menu_sync_runs`` (``applied``/``unchanged``) в той же транзакции.

В отчёте ``snapshot_hash`` — хеш снимка после ``resolve_currency`` (``None``, если снимок отвергнут
``check_snapshot`` до расчёта), ``run_id`` — строка журнала (``None`` у пробного прогона и у
``rejected``). В журнал пишется только имя файла без каталога (``source_ref``), проблемы — не больше
``MAX_REPORTED_ISSUES`` с обрезанными значениями (``SyncIssue``), число отброшенных —
``counts.issues_truncated``.

Отклонённый снимок журналируется отдельно (``record_rejected_run``) после отката основной
транзакции: иначе запись об ошибке откатилась бы вместе с ней (FR-20 — «ошибки коннектора»).

События EventBus не публикуются: CLI — отдельный процесс, в ``single`` шина в памяти не
пересекает процессы. Потребители меню (#10, #11) читают БД и не кешируют меню в памяти процесса
(ADR-8.6).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import Text, Uuid, bindparam, delete, false, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.ids import new_id
from app.menu_sync.plan import CurrentCategory, CurrentItem, CurrentMenu, ItemWrite, MenuSyncPlan, plan_menu_sync
from app.menu_sync.report import MenuSyncReport, SyncIssue, has_errors, limit_issues, safe_text
from app.menu_sync.snapshot import MenuSnapshot, check_snapshot, resolve_currency, snapshot_hash
from app.models.enums import MenuSyncSource, MenuSyncStatus
from app.models.menu import Category, MenuItem, MenuItemPrice
from app.models.menu_sync import MenuSyncRun
from app.models.tenant import Tenant

if TYPE_CHECKING:
    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

# Первый ключ двухаргументного advisory lock — «пространство» синхронизации меню (номер issue).
MENU_SYNC_LOCK_NAMESPACE: Final[int] = 8
# source_ref хранится без пути: только имя файла или «тип/версия» коннектора.
SOURCE_REF_MAX: Final[int] = 255
# Строк (или id, пар id+тариф) в одном операторе записи плана. Лимит asyncpg — 32 767 параметров на
# оператор; без пакетов снимок MAX_ITEMS × MAX_TIERS_PER_ITEM его превышает (security review #62).
# Самая широкая строка — позиция (≈ 11 параметров): 1000 × 11 с запасом укладывается в лимит.
WRITE_BATCH_ROWS: Final[int] = 1000


class MenuSyncError(RuntimeError):
    """Базовая ошибка синхронизации, не связанная с данными снимка."""


class MenuSyncBusyError(MenuSyncError):
    """Синхронизация меню этого заведения уже идёт (advisory lock занят)."""


class TenantNotFoundError(MenuSyncError):
    """Заведения с таким ``tenant_id`` нет."""


async def _acquire_lock(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Транзакционный advisory lock синхронизации меню заведения или ``MenuSyncBusyError`` без ожидания."""
    acquired = await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(:namespace, hashtext(CAST(:tenant_id AS text)))"),
        {"namespace": MENU_SYNC_LOCK_NAMESPACE, "tenant_id": str(tenant_id)},
    )
    if not acquired:
        raise MenuSyncBusyError("синхронизация меню этого заведения уже выполняется")


async def _tenant_currency(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    currency = await session.scalar(select(Tenant.currency).where(Tenant.id == tenant_id))
    if currency is None:
        raise TenantNotFoundError("заведение не найдено")
    return currency


async def load_current_menu(session: AsyncSession, tenant_id: uuid.UUID) -> CurrentMenu:
    """Категории, позиции (включая скрытые) и цены заведения; фильтр ``tenant_id`` в каждом запросе."""
    currency = await _tenant_currency(session, tenant_id)
    category_rows = await session.execute(
        select(Category.id, Category.external_id, Category.pos_name, Category.sort_key, Category.is_hidden).where(
            Category.tenant_id == tenant_id
        )
    )
    categories = {
        row.external_id: CurrentCategory(
            id=row.id,
            external_id=row.external_id,
            pos_name=row.pos_name,
            sort_key=row.sort_key,
            is_hidden=row.is_hidden,
        )
        for row in category_rows
    }

    prices: dict[uuid.UUID, dict[str, Decimal]] = defaultdict(dict)
    price_rows = await session.execute(
        select(MenuItemPrice.menu_item_id, MenuItemPrice.price_tier, MenuItemPrice.price).where(
            MenuItemPrice.tenant_id == tenant_id
        )
    )
    for row in price_rows:
        prices[row.menu_item_id][row.price_tier] = row.price

    item_rows = await session.execute(
        select(
            MenuItem.id,
            MenuItem.external_id,
            MenuItem.category_id,
            MenuItem.pos_name,
            MenuItem.currency,
            MenuItem.station,
            MenuItem.sort_key,
            MenuItem.is_available,
            MenuItem.is_hidden,
        ).where(MenuItem.tenant_id == tenant_id)
    )
    items = {
        row.external_id: CurrentItem(
            id=row.id,
            external_id=row.external_id,
            category_id=row.category_id,
            pos_name=row.pos_name,
            currency=row.currency,
            station=row.station,
            sort_key=row.sort_key,
            is_available=row.is_available,
            is_hidden=row.is_hidden,
            prices=dict(prices.get(row.id, {})),
        )
        for row in item_rows
    }
    return CurrentMenu(tenant_id=tenant_id, tenant_currency=currency, categories=categories, items=items)


async def last_applied_hash(session: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    """Хеш последнего снимка заведения со статусом ``applied``/``unchanged`` (любой источник) или ``None``.

    Состояние меню одно на заведение, поэтому источник не учитывается (ADR-8.5). Отклонённые снимки
    меню не меняли и не считаются. Порядок — ``finished_at``, при равенстве — ``id`` (UUIDv7).
    """
    return await session.scalar(
        select(MenuSyncRun.snapshot_hash)
        .where(
            MenuSyncRun.tenant_id == tenant_id,
            MenuSyncRun.status.in_((MenuSyncStatus.APPLIED, MenuSyncStatus.UNCHANGED)),
        )
        .order_by(MenuSyncRun.finished_at.desc(), MenuSyncRun.id.desc())
        .limit(1)
    )


async def apply_menu_snapshot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    snapshot: MenuSnapshot,
    source: MenuSyncSource,
    source_ref: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    allow_mass_hide: bool = False,
) -> MenuSyncReport:
    """Применить полный снимок меню заведения (шаги — в docstring модуля).

    Не коммитит. ``dry_run`` — всё, кроме записи (lock тоже берётся: счётчики считаются по
    согласованному состоянию). Ошибки данных возвращаются в отчёте (``rejected``), а не исключением;
    исключения — только ``MenuSyncBusyError``, ``TenantNotFoundError`` и ошибки БД.

    ``force`` — применить, даже если хеш совпал с последним применённым. Пробный прогон ничего не
    пишет и не журналируется, но возвращает тот статус, который дало бы применение (``applied`` или
    ``unchanged``) с ``dry_run=True``. ``rejected`` здесь не журналируется: вызывающий откатывает
    транзакцию и вызывает ``record_rejected_run`` (хеш — ``report.snapshot_hash``).
    """
    started_at = _utc_now()
    await _acquire_lock(session, tenant_id)
    currency = await _tenant_currency(session, tenant_id)
    issues = check_snapshot(snapshot, currency)
    if has_errors(issues):
        return _report(MenuSyncStatus.REJECTED, dry_run, issues)
    snapshot = resolve_currency(snapshot, currency)
    digest = snapshot_hash(snapshot)

    if not force and digest == await last_applied_hash(session, tenant_id):
        # INT-1: неизменный снимок не пересчитывается; таблицы меню (и synced_at) не трогаются.
        report = _report(MenuSyncStatus.UNCHANGED, dry_run, issues, digest=digest)
    else:
        current = await load_current_menu(session, tenant_id)
        plan = plan_menu_sync(current, snapshot, allow_mass_hide=allow_mass_hide)
        issues.extend(plan.issues)
        if has_errors(issues):
            return _report(MenuSyncStatus.REJECTED, dry_run, issues, digest=digest)
        if not dry_run:
            await _write_plan(session, tenant_id, plan)
        report = _report(MenuSyncStatus.APPLIED, dry_run, issues, plan, digest=digest)
    if not dry_run:
        report.run_id = await _insert_run(
            session,
            tenant_id=tenant_id,
            source=source,
            source_ref=source_ref,
            status=report.status,
            snapshot_hash=digest,
            started_at=started_at,
            counts=report.counts_dict(),
            issues=report.issues,
            issues_truncated=report.issues_truncated,
        )
    return report


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _report(
    status: MenuSyncStatus,
    dry_run: bool,
    issues: list[SyncIssue],
    plan: MenuSyncPlan | None = None,
    *,
    digest: str | None = None,
) -> MenuSyncReport:
    """Отчёт; проблемы — не больше ``MAX_REPORTED_ISSUES`` (``limit_issues``). У отклонённого и
    неизменного — нулевые счётчики."""
    reported, truncated = limit_issues(issues)
    report = MenuSyncReport(
        status=status, dry_run=dry_run, snapshot_hash=digest, issues=reported, issues_truncated=truncated
    )
    if plan is not None:
        report.categories = plan.categories
        report.items = plan.items
        report.prices = plan.prices
        report.availability_changed = plan.availability_changed
    return report


async def _write_plan(session: AsyncSession, tenant_id: uuid.UUID, plan: MenuSyncPlan) -> None:
    """Пакетная запись плана. ``updated_at`` ставится явно только изменённым строкам: ``onupdate`` ORM на
    Core-UPSERT не срабатывает, а в ``UPDATE`` ``synced_at`` он подавлен присваиванием ``updated_at``
    самому себе. Порядок: категории → позиции (составной FK) → цены → скрытие → ``synced_at``."""
    categories = Category.__table__
    items = MenuItem.__table__
    prices = MenuItemPrice.__table__

    category_stmt = pg_insert(categories)
    category_stmt = category_stmt.on_conflict_do_update(
        index_elements=[categories.c.tenant_id, categories.c.external_id],
        set_={
            "pos_name": category_stmt.excluded.pos_name,
            "sort_key": category_stmt.excluded.sort_key,
            "is_hidden": false(),
            "updated_at": func.now(),
        },
    )
    for chunk in _chunks(plan.category_writes):
        await session.execute(
            category_stmt,
            [
                {
                    "id": write.id,
                    "tenant_id": tenant_id,
                    "external_id": write.external_id,
                    "pos_name": write.pos_name,
                    "sort_key": write.sort_key,
                    "is_hidden": False,
                }
                for write in chunk
            ],
        )

    # is_available=None — колонку не трогать: такие позиции пишутся отдельным пакетом без неё.
    for with_availability in (True, False):
        batch = [write for write in plan.item_writes if (write.is_available is not None) == with_availability]
        for chunk in _chunks(batch):
            await _upsert_items(session, items, tenant_id, chunk, with_availability=with_availability)

    if plan.delete_prices:
        # Пары (позиция, тариф) — два массива и unnest: 3 параметра на любой объём (без IN по кортежам,
        # который упирался в лимит параметров asyncpg и глубину выражения PostgreSQL).
        pairs = (
            func.unnest(
                bindparam("delete_item_ids", [item_id for item_id, _ in plan.delete_prices], type_=ARRAY(Uuid)),
                bindparam("delete_tiers", [tier for _, tier in plan.delete_prices], type_=ARRAY(Text)),
            )
            .table_valued("menu_item_id", "price_tier")
            .render_derived(name="deleted_prices")
        )
        await session.execute(
            delete(prices).where(
                prices.c.tenant_id == tenant_id,
                prices.c.menu_item_id == pairs.c.menu_item_id,
                prices.c.price_tier == pairs.c.price_tier,
            )
        )
    price_rows = [
        {"tenant_id": tenant_id, "menu_item_id": write.id, "price_tier": tier, "price": price}
        for write in plan.item_writes
        for tier, price in sorted(write.prices.items())
    ]
    # Конфликт — по PK (menu_item_id, price_tier) без tenant_id. Это безопасно: menu_item_id берутся
    # только из позиций этого заведения (план строится по load_current_menu с фильтром tenant_id или
    # создаёт новые id), а составной FK (tenant_id, menu_item_id) → menu_items не даст сослаться на
    # позицию другого заведения.
    price_stmt = pg_insert(prices)
    price_stmt = price_stmt.on_conflict_do_update(
        index_elements=[prices.c.menu_item_id, prices.c.price_tier],
        set_={"price": price_stmt.excluded.price, "updated_at": func.now()},
        where=prices.c.price.is_distinct_from(price_stmt.excluded.price),
    )
    for chunk in _chunks(price_rows):
        await session.execute(price_stmt, chunk)

    for table, hide_ids in ((categories, plan.hide_category_ids), (items, plan.hide_item_ids)):
        for chunk in _chunks(hide_ids):
            await session.execute(
                update(table)
                .where(table.c.tenant_id == tenant_id, table.c.id.in_(chunk))
                .values(is_hidden=True, updated_at=func.now())
            )
    for table, present_ids in ((categories, plan.present_category_ids), (items, plan.present_item_ids)):
        for chunk in _chunks(present_ids):
            await session.execute(
                update(table)
                .where(table.c.tenant_id == tenant_id, table.c.id.in_(chunk))
                .values(synced_at=func.now(), updated_at=table.c.updated_at)
            )


def _chunks[T](values: Sequence[T], size: int = WRITE_BATCH_ROWS) -> Iterator[Sequence[T]]:
    """Последовательные срезы по ``size`` элементов (пустой список — ни одного среза)."""
    for start in range(0, len(values), size):
        yield values[start : start + size]


async def _upsert_items(
    session: AsyncSession, items: Table, tenant_id: uuid.UUID, batch: list[ItemWrite], *, with_availability: bool
) -> None:
    stmt = pg_insert(items)
    set_: dict[str, Any] = {
        "category_id": stmt.excluded.category_id,
        "pos_name": stmt.excluded.pos_name,
        "currency": stmt.excluded.currency,
        "station": stmt.excluded.station,
        "sort_key": stmt.excluded.sort_key,
        "is_hidden": false(),
        "updated_at": func.now(),
    }
    if with_availability:
        set_["is_available"] = stmt.excluded.is_available
    rows: list[dict[str, Any]] = []
    for write in batch:
        row: dict[str, Any] = {
            "id": write.id,
            "tenant_id": tenant_id,
            "category_id": write.category_id,
            "external_id": write.external_id,
            "pos_name": write.pos_name,
            "currency": write.currency,
            "station": write.station,
            "sort_key": write.sort_key,
            "is_hidden": False,
        }
        if with_availability:
            row["is_available"] = write.is_available
        rows.append(row)
    await session.execute(
        stmt.on_conflict_do_update(index_elements=[items.c.tenant_id, items.c.external_id], set_=set_),
        rows,
    )


async def record_rejected_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source: MenuSyncSource,
    source_ref: str | None,
    issues: list[SyncIssue],
    snapshot_hash: str | None = None,
    started_at: datetime | None = None,
) -> uuid.UUID:
    """Записать ``menu_sync_runs`` со статусом ``rejected`` (проблемы — ``limit_issues``) и вернуть ``id``.
    Не коммитит.

    Вызывается в новой транзакции после отката: и для ошибок разбора файла (снимка нет, хеша нет),
    и для ``rejected`` из ``apply_menu_snapshot``. Пробный прогон не журналируется. ``started_at`` —
    начало синхронизации (по умолчанию — момент записи).
    """
    reported, truncated = limit_issues(issues)
    return await _insert_run(
        session,
        tenant_id=tenant_id,
        source=source,
        source_ref=source_ref,
        status=MenuSyncStatus.REJECTED,
        snapshot_hash=snapshot_hash,
        started_at=started_at or _utc_now(),
        counts={},
        issues=reported,
        issues_truncated=truncated,
    )


def journal_source_ref(source: MenuSyncSource, source_ref: str | None) -> str | None:
    """``source_ref`` для журнала: у файла — только имя без каталога (разделители ``/`` и ``\\``),
    невидимые символы экранированы, длина не больше ``SOURCE_REF_MAX``; пустое значение — ``None``."""
    if source_ref is None:
        return None
    value = source_ref.strip()
    if source is MenuSyncSource.FILE:
        value = PureWindowsPath(value).name.strip()
    return safe_text(value, SOURCE_REF_MAX) or None


async def _insert_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source: MenuSyncSource,
    source_ref: str | None,
    status: MenuSyncStatus,
    snapshot_hash: str | None,
    started_at: datetime,
    counts: dict[str, Any],
    issues: list[SyncIssue],
    issues_truncated: int,
) -> uuid.UUID:
    """Строка ``menu_sync_runs``. Время — часы приложения: ``now()`` внутри транзакции равен её началу и
    может оказаться раньше ``started_at`` (CHECK ``finished_at >= started_at``)."""
    run_id = new_id()
    if issues_truncated:
        counts = {**counts, "issues_truncated": issues_truncated}
    await session.execute(
        insert(MenuSyncRun).values(
            id=run_id,
            tenant_id=tenant_id,
            source=source.value,
            source_ref=journal_source_ref(source, source_ref),
            status=status.value,
            snapshot_hash=snapshot_hash,
            started_at=started_at,
            finished_at=max(_utc_now(), started_at),
            counts=counts,
            issues=[issue.to_dict() for issue in issues],
        )
    )
    return run_id
