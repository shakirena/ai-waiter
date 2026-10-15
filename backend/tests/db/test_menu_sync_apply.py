"""Применение снимка меню ``apply_menu_snapshot`` на PostgreSQL (story #62, AC-2, ADR-8.3, ADR-8.4).

AC #62: позиции 1001, 1002, 1003 (с meta), скрытая 1004, у другого заведения своя 1001; снимок
1001 (новая цена), 1002, 1004, 1005 → новая цена у 1001, 1003 скрыта с meta, 1004 видима, 1005
создана, ничего не удалено, чужое заведение не изменилось.

Внутри одной транзакции ``now()`` постоянен, поэтому исходные строки создаются со старыми
``updated_at``/``synced_at`` (``OLD``): так видно, каким строкам сервис их поменял.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.menu_sync.report import MAX_REPORTED_ISSUES, EntityCounts, IssueCode, PriceCounts, Severity
from app.menu_sync.service import (
    MenuSyncBusyError,
    TenantNotFoundError,
    apply_menu_snapshot,
    load_current_menu,
)
from app.menu_sync.snapshot import MAX_ITEMS, MAX_TIERS_PER_ITEM, MenuSnapshot
from app.models.enums import DEFAULT_PRICE_TIER, MenuSyncSource, MenuSyncStatus
from app.models.menu import Category, MenuItem, MenuItemAllergen, MenuItemMeta, MenuItemPrice
from tests.db.conftest import isolated_session
from tests.db.factories import add, create_allergen, create_category, create_menu_item, create_tenant

pytestmark = pytest.mark.db

OLD = datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------- помощники


async def _category(session: AsyncSession, tenant_id: uuid.UUID, external_id: str = "19", **values: Any) -> Category:
    values.setdefault("pos_name", "Isti yemekler")
    values.setdefault("sort_key", external_id)
    return await create_category(
        session, tenant_id, external_id=external_id, updated_at=OLD, synced_at=OLD, created_at=OLD, **values
    )


async def _item(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    category_id: uuid.UUID,
    external_id: str,
    prices: dict[str, str] | None = None,
    **values: Any,
) -> MenuItem:
    values.setdefault("pos_name", f"Блюдо {external_id}")
    item = await create_menu_item(
        session,
        tenant_id,
        category_id,
        external_id=external_id,
        updated_at=OLD,
        synced_at=OLD,
        created_at=OLD,
        **values,
    )
    for tier, price in (prices or {"default": "8.00"}).items():
        await add(
            session,
            MenuItemPrice(
                tenant_id=tenant_id,
                menu_item_id=item.id,
                price_tier=tier,
                price=Decimal(price),
                updated_at=OLD,
                created_at=OLD,
            ),
        )
    return item


def _snap_item(external_id: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "external_id": external_id,
        "category_external_id": "19",
        "name": f"Блюдо {external_id}",
        "prices": {"default": "8.00"},
    }
    item.update(overrides)
    return item


def _snapshot(*items: dict[str, Any], categories: list[dict[str, Any]] | None = None) -> MenuSnapshot:
    if categories is None:
        categories = [{"external_id": "19", "name": "Isti yemekler", "sort_key": "19"}]
    return MenuSnapshot.model_validate({"categories": categories, "items": list(items)})


async def _apply(session: AsyncSession, tenant_id: uuid.UUID, snapshot: MenuSnapshot, **kwargs: Any) -> Any:
    return await apply_menu_snapshot(
        session, tenant_id=tenant_id, snapshot=snapshot, source=MenuSyncSource.FILE, source_ref="menu.csv", **kwargs
    )


async def _items(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Позиции заведения по ``external_id`` (свежие значения из БД, не из identity map)."""
    rows = await session.execute(
        select(
            MenuItem.id,
            MenuItem.external_id,
            MenuItem.category_id,
            MenuItem.pos_name,
            MenuItem.is_hidden,
            MenuItem.is_available,
            MenuItem.updated_at,
            MenuItem.synced_at,
        ).where(MenuItem.tenant_id == tenant_id)
    )
    return {row.external_id: row for row in rows}


async def _categories(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    rows = await session.execute(
        select(
            Category.id,
            Category.external_id,
            Category.pos_name,
            Category.is_hidden,
            Category.updated_at,
            Category.synced_at,
        ).where(Category.tenant_id == tenant_id)
    )
    return {row.external_id: row for row in rows}


async def _prices(session: AsyncSession, tenant_id: uuid.UUID) -> dict[tuple[str, str], tuple[Decimal, datetime]]:
    rows = await session.execute(
        select(MenuItem.external_id, MenuItemPrice.price_tier, MenuItemPrice.price, MenuItemPrice.updated_at)
        .join(MenuItem, MenuItem.id == MenuItemPrice.menu_item_id)
        .where(MenuItemPrice.tenant_id == tenant_id, MenuItem.tenant_id == tenant_id)
    )
    return {(row.external_id, row.price_tier): (row.price, row.updated_at) for row in rows}


async def _state(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[Any, ...]:
    """Всё синхронизируемое меню заведения — для проверки «ничего не записано»."""
    items = {k: tuple(v) for k, v in (await _items(session, tenant_id)).items()}
    categories = {k: tuple(v) for k, v in (await _categories(session, tenant_id)).items()}
    return items, categories, await _prices(session, tenant_id)


async def _now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.now()))
    assert value is not None
    return value


async def _count(session: AsyncSession, model: type, tenant_id: uuid.UUID) -> int:
    column = model.tenant_id  # type: ignore[attr-defined]
    return int(await session.scalar(select(func.count()).select_from(model).where(column == tenant_id)) or 0)


# ---------------------------------------------------------------- AC #62


async def test_ac62_scenario(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    other = await create_tenant(db_session, name="Другое заведение")
    category = await _category(db_session, tenant.id)
    for external_id in ("1001", "1002"):
        await _item(db_session, tenant.id, category.id, external_id)
    item_1003 = await _item(db_session, tenant.id, category.id, "1003")
    await add(db_session, MenuItemMeta(tenant_id=tenant.id, menu_item_id=item_1003.id, name_ru="Долма"))
    allergen = await create_allergen(db_session, tenant.id)
    await add(db_session, MenuItemAllergen(tenant_id=tenant.id, menu_item_id=item_1003.id, allergen_id=allergen.id))
    await _item(db_session, tenant.id, category.id, "1004", is_hidden=True)
    other_category = await _category(db_session, other.id)
    await _item(db_session, other.id, other_category.id, "1001", prices={"default": "5.00"})
    other_before = await _state(db_session, other.id)

    snapshot = _snapshot(
        _snap_item("1001", prices={"default": "9.50"}),
        _snap_item("1002"),
        _snap_item("1004"),
        _snap_item("1005", prices={"default": "4.00", "vip": "5.00"}, station="Bar"),
    )
    report = await _apply(db_session, tenant.id, snapshot)

    assert report.status is MenuSyncStatus.APPLIED
    assert report.dry_run is False
    assert report.issues == []
    # #63: применение журналируется — хеш снимка и строка menu_sync_runs (подробно — test_menu_sync_runs.py).
    assert report.snapshot_hash is not None
    assert report.run_id is not None
    assert report.items == EntityCounts(created=1, updated=1, hidden=1, restored=1, unchanged=1)
    assert report.categories == EntityCounts(unchanged=1)
    assert report.prices == PriceCounts(created=2, updated=1)

    now = await _now(db_session)
    items = await _items(db_session, tenant.id)
    prices = await _prices(db_session, tenant.id)
    assert prices[("1001", "default")] == (Decimal("9.50"), now)
    assert prices[("1002", "default")] == (Decimal("8.00"), OLD)  # не изменилась — не перезаписана
    assert prices[("1005", "vip")][0] == Decimal("5.00")
    assert items["1003"].is_hidden is True
    assert items["1004"].is_hidden is False
    assert items["1005"].is_hidden is False
    assert items["1005"].is_available is True
    assert set(items) == {"1001", "1002", "1003", "1004", "1005"}  # ничего не удалено
    assert await _count(db_session, Category, tenant.id) == 1

    # meta и аллергены скрытой позиции сохранены
    meta = await db_session.scalar(
        select(MenuItemMeta.name_ru).where(
            MenuItemMeta.tenant_id == tenant.id, MenuItemMeta.menu_item_id == items["1003"].id
        )
    )
    assert meta == "Долма"
    assert await _count(db_session, MenuItemAllergen, tenant.id) == 1

    # updated_at — только изменённым, synced_at — всем присутствующим
    assert items["1001"].updated_at == now
    assert items["1002"].updated_at == OLD
    assert items["1003"].updated_at == now  # скрыта
    assert items["1004"].updated_at == now  # возвращена
    assert {k: items[k].synced_at for k in ("1001", "1002", "1004", "1005")} == dict.fromkeys(
        ("1001", "1002", "1004", "1005"), now
    )
    assert items["1003"].synced_at == OLD
    categories = await _categories(db_session, tenant.id)
    assert categories["19"].updated_at == OLD
    assert categories["19"].synced_at == now

    # чужое заведение с той же 1001 не изменилось
    assert await _state(db_session, other.id) == other_before


async def test_categories_created_updated_hidden_and_restored(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    kept = await _category(db_session, tenant.id, "19")
    await _category(db_session, tenant.id, "20", pos_name="Старое имя")
    await _category(db_session, tenant.id, "21")
    await _category(db_session, tenant.id, "22", is_hidden=True)
    await _item(db_session, tenant.id, kept.id, "1")

    snapshot = _snapshot(
        _snap_item("1", category_external_id="23"),
        categories=[
            {"external_id": "19", "name": "Isti yemekler", "sort_key": "19"},
            {"external_id": "20", "name": "Новое имя", "sort_key": "20"},
            {"external_id": "22", "name": "Isti yemekler", "sort_key": "22"},
            {"external_id": "23", "name": "Şorbalar"},
        ],
    )
    report = await _apply(db_session, tenant.id, snapshot)

    assert report.categories == EntityCounts(created=1, updated=1, hidden=1, restored=1, unchanged=1)
    categories = await _categories(db_session, tenant.id)
    assert categories["20"].pos_name == "Новое имя"
    assert categories["21"].is_hidden is True
    assert categories["22"].is_hidden is False
    assert categories["23"].is_hidden is False
    items = await _items(db_session, tenant.id)
    assert items["1"].category_id == categories["23"].id
    assert report.items == EntityCounts(updated=1)


async def test_prices_and_availability(db_session: AsyncSession) -> None:
    """Тариф вне снимка удаляется; ``is_available=None`` не меняет наличие, значение — записывается."""
    tenant = await create_tenant(db_session)
    category = await _category(db_session, tenant.id)
    await _item(db_session, tenant.id, category.id, "1", prices={"default": "8.00", "vip": "10.00"}, is_available=False)
    await _item(db_session, tenant.id, category.id, "2", is_available=True)
    await _item(db_session, tenant.id, category.id, "3", is_available=False)

    snapshot = _snapshot(
        _snap_item("1"),
        _snap_item("2", is_available=False),
        _snap_item("3", is_available=True),
        _snap_item("4", is_available=False),
    )
    report = await _apply(db_session, tenant.id, snapshot)

    assert report.prices == PriceCounts(created=1, deleted=1)
    assert report.availability_changed == 2
    items = await _items(db_session, tenant.id)
    assert {k: v.is_available for k, v in items.items()} == {"1": False, "2": False, "3": True, "4": False}
    prices = await _prices(db_session, tenant.id)
    assert ("1", "vip") not in prices
    assert ("1", "default") in prices


async def test_zero_price_warning_does_not_block(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    report = await _apply(db_session, tenant.id, _snapshot(_snap_item("1", prices={"default": "0"})))

    assert report.status is MenuSyncStatus.APPLIED
    assert [(i.code, i.severity) for i in report.issues] == [(IssueCode.ZERO_PRICE, Severity.WARNING)]
    assert report.categories == EntityCounts(created=1)
    assert (await _prices(db_session, tenant.id))[("1", "default")][0] == Decimal("0.00")


# ---------------------------------------------------------------- пробный прогон


async def test_dry_run_writes_nothing_and_matches_real_counts(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    category = await _category(db_session, tenant.id)
    for external_id in ("1", "2", "3"):
        await _item(db_session, tenant.id, category.id, external_id)
    snapshot = _snapshot(_snap_item("1", prices={"default": "9.00"}), _snap_item("2"), _snap_item("4"))
    before = await _state(db_session, tenant.id)

    dry = await _apply(db_session, tenant.id, snapshot, dry_run=True)
    assert dry.status is MenuSyncStatus.APPLIED
    assert dry.dry_run is True
    assert await _state(db_session, tenant.id) == before

    real = await _apply(db_session, tenant.id, snapshot)
    assert real.dry_run is False
    assert real.counts_dict() == dry.counts_dict()
    assert await _state(db_session, tenant.id) != before


# ---------------------------------------------------------------- отказ: ничего не записано


async def test_currency_mismatch_rejects_whole_snapshot(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    category = await _category(db_session, tenant.id)
    await _item(db_session, tenant.id, category.id, "1")
    before = await _state(db_session, tenant.id)

    report = await _apply(
        db_session, tenant.id, _snapshot(_snap_item("1", prices={"default": "9.00"}), _snap_item("2", currency="USD"))
    )

    assert report.status is MenuSyncStatus.REJECTED
    assert [i.code for i in report.issues] == [IssueCode.CURRENCY_MISMATCH]
    assert report.counts_dict() == {
        "categories": asdict(EntityCounts()),
        "items": asdict(EntityCounts()),
        "prices": asdict(PriceCounts()),
        "availability_changed": 0,
    }
    assert await _state(db_session, tenant.id) == before


async def test_empty_snapshot_is_always_rejected(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    category = await _category(db_session, tenant.id)
    await _item(db_session, tenant.id, category.id, "1")
    before = await _state(db_session, tenant.id)

    report = await _apply(db_session, tenant.id, _snapshot(), allow_mass_hide=True)

    assert report.status is MenuSyncStatus.REJECTED
    assert [i.code for i in report.issues] == [IssueCode.EMPTY_SNAPSHOT]
    assert await _state(db_session, tenant.id) == before


async def test_mass_hide_rejected_and_allowed(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    category = await _category(db_session, tenant.id)
    for n in range(1, 13):
        await _item(db_session, tenant.id, category.id, str(n))
    snapshot = _snapshot(_snap_item("1"), _snap_item("2"))
    before = await _state(db_session, tenant.id)

    rejected = await _apply(db_session, tenant.id, snapshot)
    assert rejected.status is MenuSyncStatus.REJECTED
    assert [i.code for i in rejected.issues] == [IssueCode.MASS_HIDE]
    assert rejected.items == EntityCounts()
    assert await _state(db_session, tenant.id) == before

    applied = await _apply(db_session, tenant.id, snapshot, allow_mass_hide=True)
    assert applied.status is MenuSyncStatus.APPLIED
    assert applied.items == EntityCounts(hidden=10, unchanged=2)
    items = await _items(db_session, tenant.id)
    assert sum(1 for row in items.values() if row.is_hidden) == 10
    assert len(items) == 12


async def test_issues_are_limited(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    snapshot = _snapshot(*[_snap_item(str(n), currency="USD") for n in range(MAX_REPORTED_ISSUES + 20)])

    report = await _apply(db_session, tenant.id, snapshot)

    assert report.status is MenuSyncStatus.REJECTED
    assert len(report.issues) == MAX_REPORTED_ISSUES
    assert report.issues_truncated == 20
    assert await _count(db_session, MenuItem, tenant.id) == 0


async def test_max_size_snapshot_fits_bind_parameter_limit(db_session: AsyncSession) -> None:
    """Security review #62 (LOW): ``MAX_ITEMS`` позиций × ``MAX_TIERS_PER_ITEM`` тарифов, затем тот же снимок
    с одним тарифом — 45 000 удаляемых цен. Каждая запись укладывается в лимит asyncpg (32 767 параметров)."""
    tenant = await create_tenant(db_session)
    tiers = [DEFAULT_PRICE_TIER, *(f"t{n}" for n in range(1, MAX_TIERS_PER_ITEM))]
    full = _snapshot(*[_snap_item(str(n), prices=dict.fromkeys(tiers, "8.00")) for n in range(MAX_ITEMS)])

    created = await _apply(db_session, tenant.id, full)
    assert created.status is MenuSyncStatus.APPLIED
    assert created.prices == PriceCounts(created=MAX_ITEMS * MAX_TIERS_PER_ITEM)

    reduced = await _apply(db_session, tenant.id, _snapshot(*[_snap_item(str(n)) for n in range(MAX_ITEMS)]))
    assert reduced.status is MenuSyncStatus.APPLIED
    assert reduced.prices == PriceCounts(deleted=MAX_ITEMS * (MAX_TIERS_PER_ITEM - 1))
    assert await _count(db_session, MenuItemPrice, tenant.id) == MAX_ITEMS


# ---------------------------------------------------------------- lock, заведение, загрузка


async def test_busy_lock_raises(db_session: AsyncSession, migrated_database: str) -> None:
    """Lock держит второе соединение (та же формула, что в ADR-8.4: ``hashtext(tenant_id::text)``)."""
    tenant = await create_tenant(db_session)
    other = await create_tenant(db_session, name="Другое заведение")
    snapshot = _snapshot(_snap_item("1"))

    async with isolated_session(migrated_database) as holder:
        held = await holder.scalar(
            text("SELECT pg_try_advisory_xact_lock(8, hashtext(CAST(:tenant_id AS uuid)::text))"),
            {"tenant_id": str(tenant.id)},
        )
        assert held is True
        with pytest.raises(MenuSyncBusyError):
            await _apply(db_session, tenant.id, snapshot)
        # lock другого заведения свободен
        assert (await _apply(db_session, other.id, snapshot)).status is MenuSyncStatus.APPLIED

    # транзакция второго соединения завершена — lock снят
    assert (await _apply(db_session, tenant.id, snapshot)).status is MenuSyncStatus.APPLIED


async def test_unknown_tenant(db_session: AsyncSession) -> None:
    with pytest.raises(TenantNotFoundError):
        await _apply(db_session, uuid.uuid4(), _snapshot(_snap_item("1")))
    with pytest.raises(TenantNotFoundError):
        await load_current_menu(db_session, uuid.uuid4())


async def test_load_current_menu_is_tenant_scoped(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    other = await create_tenant(db_session, name="Другое заведение")
    category = await _category(db_session, tenant.id)
    await _item(db_session, tenant.id, category.id, "1", prices={"default": "8.00", "vip": "10.50"}, station="Bar")
    await _item(db_session, tenant.id, category.id, "2", is_hidden=True)
    other_category = await _category(db_session, other.id, "77")
    await _item(db_session, other.id, other_category.id, "1", prices={"default": "1.00"})

    current = await load_current_menu(db_session, tenant.id)

    assert current.tenant_id == tenant.id
    assert current.tenant_currency == "AZN"
    assert set(current.categories) == {"19"}
    assert set(current.items) == {"1", "2"}
    first = current.items["1"]
    assert first.prices == {"default": Decimal("8.00"), "vip": Decimal("10.50")}
    assert first.station == "Bar"
    assert first.category_id == category.id
    assert current.items["2"].is_hidden is True
