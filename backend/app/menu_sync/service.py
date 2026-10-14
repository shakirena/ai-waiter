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

До #63 сервис работает без журнала: ``snapshot_hash`` и ``run_id`` в отчёте — ``None``, статусы —
только ``applied``/``rejected``, параметр ``force`` принимается и ни на что не влияет. #63 вставляет
шаги 3 и 6, не меняя сигнатуру.

Отклонённый снимок журналируется отдельно (``record_rejected_run``) после отката основной
транзакции: иначе запись об ошибке откатилась бы вместе с ней (FR-20 — «ошибки коннектора»).

События EventBus не публикуются: CLI — отдельный процесс, в ``single`` шина в памяти не
пересекает процессы. Потребители меню (#10, #11) читают БД и не кешируют меню в памяти процесса
(ADR-8.6).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import delete, false, func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.menu_sync.plan import CurrentCategory, CurrentItem, CurrentMenu, ItemWrite, MenuSyncPlan, plan_menu_sync
from app.menu_sync.report import MenuSyncReport, SyncIssue, has_errors, limit_issues
from app.menu_sync.snapshot import MenuSnapshot, check_snapshot, resolve_currency
from app.models.enums import MenuSyncSource, MenuSyncStatus
from app.models.menu import Category, MenuItem, MenuItemPrice
from app.models.tenant import Tenant

if TYPE_CHECKING:
    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

# Первый ключ двухаргументного advisory lock — «пространство» синхронизации меню (номер issue).
MENU_SYNC_LOCK_NAMESPACE: Final[int] = 8
# source_ref хранится без пути: только имя файла или «тип/версия» коннектора.
SOURCE_REF_MAX: Final[int] = 255


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
    """(#63) Хеш последнего снимка со статусом ``applied``/``unchanged`` (любой источник) или ``None``."""
    raise NotImplementedError


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

    До #63 ``source``, ``source_ref`` и ``force`` не используются (они нужны журналу). Пробный прогон
    без ошибок возвращает ``applied`` с ``dry_run=True``: так выглядел бы итог применения.
    """
    await _acquire_lock(session, tenant_id)
    currency = await _tenant_currency(session, tenant_id)
    issues = check_snapshot(snapshot, currency)
    if has_errors(issues):
        return _report(MenuSyncStatus.REJECTED, dry_run, issues)
    snapshot = resolve_currency(snapshot, currency)

    current = await load_current_menu(session, tenant_id)
    plan = plan_menu_sync(current, snapshot, allow_mass_hide=allow_mass_hide)
    issues.extend(plan.issues)
    if has_errors(issues):
        return _report(MenuSyncStatus.REJECTED, dry_run, issues)
    if not dry_run:
        await _write_plan(session, tenant_id, plan)
    return _report(MenuSyncStatus.APPLIED, dry_run, issues, plan)


def _report(
    status: MenuSyncStatus, dry_run: bool, issues: list[SyncIssue], plan: MenuSyncPlan | None = None
) -> MenuSyncReport:
    """Отчёт; проблемы — не больше ``MAX_REPORTED_ISSUES`` (``limit_issues``). У отклонённого — нулевые счётчики."""
    reported, truncated = limit_issues(issues)
    report = MenuSyncReport(status=status, dry_run=dry_run, issues=reported, issues_truncated=truncated)
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

    if plan.category_writes:
        stmt = pg_insert(categories)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[categories.c.tenant_id, categories.c.external_id],
                set_={
                    "pos_name": stmt.excluded.pos_name,
                    "sort_key": stmt.excluded.sort_key,
                    "is_hidden": false(),
                    "updated_at": func.now(),
                },
            ),
            [
                {
                    "id": write.id,
                    "tenant_id": tenant_id,
                    "external_id": write.external_id,
                    "pos_name": write.pos_name,
                    "sort_key": write.sort_key,
                    "is_hidden": False,
                }
                for write in plan.category_writes
            ],
        )

    # is_available=None — колонку не трогать: такие позиции пишутся отдельным пакетом без неё.
    for with_availability in (True, False):
        batch = [write for write in plan.item_writes if (write.is_available is not None) == with_availability]
        if batch:
            await _upsert_items(session, items, tenant_id, batch, with_availability=with_availability)

    if plan.delete_prices:
        await session.execute(
            delete(prices).where(
                prices.c.tenant_id == tenant_id,
                tuple_(prices.c.menu_item_id, prices.c.price_tier).in_(plan.delete_prices),
            )
        )
    price_rows = [
        {"tenant_id": tenant_id, "menu_item_id": write.id, "price_tier": tier, "price": price}
        for write in plan.item_writes
        for tier, price in sorted(write.prices.items())
    ]
    if price_rows:
        stmt = pg_insert(prices)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[prices.c.menu_item_id, prices.c.price_tier],
                set_={"price": stmt.excluded.price, "updated_at": func.now()},
                where=prices.c.price.is_distinct_from(stmt.excluded.price),
            ),
            price_rows,
        )

    for table, hide_ids in ((categories, plan.hide_category_ids), (items, plan.hide_item_ids)):
        if hide_ids:
            await session.execute(
                update(table)
                .where(table.c.tenant_id == tenant_id, table.c.id.in_(hide_ids))
                .values(is_hidden=True, updated_at=func.now())
            )
    # В применяемом снимке всегда есть позиции и их категории (пустой отвергнут check_snapshot).
    for table, present_ids in ((categories, plan.present_category_ids), (items, plan.present_item_ids)):
        await session.execute(
            update(table)
            .where(table.c.tenant_id == tenant_id, table.c.id.in_(present_ids))
            .values(synced_at=func.now(), updated_at=table.c.updated_at)
        )


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
) -> uuid.UUID:
    """(#63) Записать ``menu_sync_runs`` со статусом ``rejected`` (проблемы — ``limit_issues``). Не коммитит.

    Вызывается в новой транзакции после отката: и для ошибок разбора файла (снимка нет, хеша нет),
    и для ``rejected`` из ``apply_menu_snapshot``. Пробный прогон не журналируется.
    """
    raise NotImplementedError
