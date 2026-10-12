"""AC-6 (#53), ADR-7.12: сид-данные на настоящем PostgreSQL.

- ``apply_seed`` в откатываемой транзакции: два запуска дают одинаковые счётчики строк во всех
  таблицах, полный набор данных, возврат к эталонным значениям, защита чужого стола;
- ``python -m app.seed`` (``main``) по-настоящему фиксирует транзакцию дважды подряд, после
  теста схема пересоздаётся миграциями (данные сида не попадают в другие тесты);
- ошибка подключения не показывает пароль.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import func, make_url, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import app.seed.__main__ as seed_cli
from app.models.enums import DEFAULT_PRICE_TIER, OrderEventType, OrderStatus, TableType, VisitStatus
from app.models.menu import Allergen, Category, MenuItem, MenuItemAllergen, MenuItemMeta, MenuItemPrice
from app.models.order import Order, OrderEvent, OrderItem
from app.models.reference import EU14_ALLERGEN_CODES
from app.models.tenant import Hall, Table, Tenant
from app.models.visit import CartItem, Message, Visit
from app.seed import data
from app.seed.loader import SeedError, apply_seed
from tests.db.conftest import alembic_command, reset_schema, run_in_thread
from tests.db.factories import create_table, create_tenant

pytestmark = pytest.mark.db

TABLES_SQL = "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"


async def row_counts(session: AsyncSession) -> dict[str, int]:
    """Число строк в каждой таблице схемы ``public`` (кроме ``alembic_version``)."""
    names = sorted((await session.scalars(text(TABLES_SQL))).all())
    return {name: (await session.scalar(text(f'SELECT count(*) FROM "{name}"'))) or 0 for name in names}  # noqa: S608


EXPECTED_COUNTS: dict[str, int] = {
    "tenants": 1,
    "halls": 2,
    "tables": 6,
    "allergens": 14,
    "categories": 4,
    "menu_items": len(data.DISHES),
    "menu_item_prices": sum(len(dish.prices) for dish in data.DISHES),
    "menu_item_meta": len(data.DISHES),
    "menu_item_allergens": sum(len(dish.allergens) for dish in data.DISHES),
    "visits": 1,
    "messages": len(data.VISIT.messages),
    "cart_items": len(data.VISIT.cart),
    "orders": 1,
    "order_items": len(data.ORDER.lines),
    "order_events": 1,
}


async def test_seed_twice_gives_same_row_counts(db_session: AsyncSession) -> None:
    """AC-6: идемпотентность — второй запуск не меняет число строк ни в одной таблице."""
    before = await row_counts(db_session)
    assert set(before.values()) == {0}
    await apply_seed(db_session)
    first = await row_counts(db_session)
    await apply_seed(db_session)
    second = await row_counts(db_session)

    assert first == second
    assert first == EXPECTED_COUNTS


async def test_seed_loads_full_dataset(db_session: AsyncSession) -> None:
    summary = await apply_seed(db_session)
    tenant_id = summary.tenant_id
    assert tenant_id == data.DEMO_TENANT_ID

    tenant = await db_session.get(Tenant, tenant_id)
    assert tenant is not None
    assert (tenant.name, tenant.currency, tenant.timezone, tenant.languages) == (
        "Demo Restoran",
        "AZN",
        "Asia/Baku",
        ["az", "ru"],
    )

    tables = (await db_session.scalars(select(Table).where(Table.tenant_id == tenant_id))).all()
    assert {t.qr_token for t in tables} == {t.qr_token for t in data.TABLES}
    cabins = [t for t in tables if t.type == TableType.CABIN]
    assert [(t.price_tier, t.is_active) for t in cabins] == [("vip", True)]
    assert [t.is_active for t in tables].count(False) == 1
    assert all(t.hall_id is not None for t in tables)
    assert len({t.hall_id for t in tables}) == 2

    codes = set(await db_session.scalars(select(Allergen.code).where(Allergen.tenant_id == tenant_id)))
    assert codes == set(EU14_ALLERGEN_CODES)

    items = (await db_session.scalars(select(MenuItem).where(MenuItem.tenant_id == tenant_id))).all()
    assert [i.is_hidden for i in items].count(True) == 1
    assert [i.is_available for i in items].count(False) == 1
    assert {i.currency for i in items} == {"AZN"}

    tiers = (await db_session.execute(select(MenuItemPrice.menu_item_id, MenuItemPrice.price_tier))).all()
    for item in items:
        assert {(item.id, DEFAULT_PRICE_TIER), (item.id, "vip")} <= set(tiers)

    metas = (await db_session.scalars(select(MenuItemMeta))).all()
    assert {m.allergens_verified for m in metas} == {True, False}
    assert all(m.name_az and m.name_ru and m.description_az and m.description_ru for m in metas)

    # Позиция с подтверждённым списком аллергенов связана ровно с ним.
    caesar = next(i for i in items if i.external_id == "demo-d02")
    linked = set(
        await db_session.scalars(
            select(Allergen.code)
            .join(MenuItemAllergen, MenuItemAllergen.allergen_id == Allergen.id)
            .where(MenuItemAllergen.menu_item_id == caesar.id)
        )
    )
    assert linked == set(data.dish_by_external_id("demo-d02").allergens)

    visit = (await db_session.scalars(select(Visit))).one()
    assert visit.status == VisitStatus.OPEN
    table_1 = next(t for t in tables if t.qr_token == data.VISIT.table_token)
    assert visit.table_id == table_1.id

    order = (await db_session.scalars(select(Order))).one()
    assert order.status == OrderStatus.SUBMITTED
    assert order.visit_id == visit.id
    assert order.total == data.order_total(data.ORDER, table_1.price_tier)
    lines = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    assert sum((line.price_at_order * line.qty for line in lines), Decimal("0")) == order.total
    event = (await db_session.scalars(select(OrderEvent))).one()
    assert (event.order_id, event.type, event.to_status) == (order.id, OrderEventType.CREATED, OrderStatus.SUBMITTED)

    assert await db_session.scalar(select(func.count()).select_from(Hall)) == 2
    assert await db_session.scalar(select(func.count()).select_from(Category)) == 4
    assert await db_session.scalar(select(func.count()).select_from(Message)) == 2
    assert await db_session.scalar(select(func.count()).select_from(CartItem)) == 2


async def test_seed_restores_reference_values(db_session: AsyncSession) -> None:
    """Повторный запуск возвращает эталон: цену, флаги позиции, аллергены, открытый визит."""
    await apply_seed(db_session)
    item_id = await db_session.scalar(select(MenuItem.id).where(MenuItem.external_id == "demo-d01"))
    extra_allergen = await db_session.scalar(select(Allergen.id).where(Allergen.code == "sesame"))
    await db_session.execute(
        update(MenuItemPrice)
        .where(MenuItemPrice.menu_item_id == item_id, MenuItemPrice.price_tier == DEFAULT_PRICE_TIER)
        .values(price=Decimal("99.99"))
    )
    await db_session.execute(update(MenuItem).where(MenuItem.id == item_id).values(is_hidden=True))
    db_session.add(MenuItemAllergen(tenant_id=data.DEMO_TENANT_ID, menu_item_id=item_id, allergen_id=extra_allergen))
    await db_session.execute(update(Visit).values(status=VisitStatus.CLOSED, closed_at=func.now(), closed_by="staff"))
    await db_session.flush()

    await apply_seed(db_session)
    db_session.expire_all()

    price = await db_session.scalar(
        select(MenuItemPrice.price).where(
            MenuItemPrice.menu_item_id == item_id, MenuItemPrice.price_tier == DEFAULT_PRICE_TIER
        )
    )
    assert price == Decimal("6.50")
    assert await db_session.scalar(select(MenuItem.is_hidden).where(MenuItem.id == item_id)) is False
    links = await db_session.scalar(
        select(func.count()).select_from(MenuItemAllergen).where(MenuItemAllergen.menu_item_id == item_id)
    )
    assert links == 0
    visit = (await db_session.scalars(select(Visit))).one()
    assert (visit.status, visit.closed_at, visit.closed_by) == (VisitStatus.OPEN, None, None)
    assert await row_counts(db_session) == EXPECTED_COUNTS


async def test_seed_does_not_touch_foreign_table_with_same_token(db_session: AsyncSession) -> None:
    """Токен глобально уникален: стол другого заведения с демо-токеном сид не перезаписывает."""
    other = await create_tenant(db_session, name="Другое заведение")
    await create_table(db_session, other.id, name="Чужой стол", qr_token=data.TABLES[0].qr_token)

    with pytest.raises(SeedError, match="tables"):
        async with db_session.begin_nested():
            await apply_seed(db_session)

    table = (await db_session.scalars(select(Table).where(Table.qr_token == data.TABLES[0].qr_token))).one()
    assert (table.tenant_id, table.name) == (other.id, "Чужой стол")


# ---------------------------------------------------------------- python -m app.seed с фиксацией


@pytest.fixture
def committed_seed(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Чистая схема до и после теста: ``main`` фиксирует данные, другим тестам они не нужны."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("APP_MODE", "single")
    reset_schema(migrated_database)
    alembic_command(migrated_database, "upgrade", "head")
    yield migrated_database
    reset_schema(migrated_database)
    alembic_command(migrated_database, "upgrade", "head")


async def _committed_counts(database_url: str) -> dict[str, int]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session:
            return await row_counts(session)
    finally:
        await engine.dispose()


def test_cli_twice_commits_same_data(committed_seed: str, capsys: pytest.CaptureFixture[str]) -> None:
    url = committed_seed
    assert seed_cli.main(["--database-url", url]) == 0
    first = run_in_thread(lambda: asyncio.run(_committed_counts(url)))
    assert seed_cli.main(["--database-url", url]) == 0
    second = run_in_thread(lambda: asyncio.run(_committed_counts(url)))

    assert first == second == EXPECTED_COUNTS
    out = capsys.readouterr().out
    for table in data.TABLES:
        assert f"/t/{table.qr_token}" in out


def test_cli_without_schema_fails_with_hint(committed_seed: str, capsys: pytest.CaptureFixture[str]) -> None:
    reset_schema(committed_seed)
    assert seed_cli.main(["--database-url", committed_seed]) == 1
    assert "alembic upgrade head" in capsys.readouterr().err


def test_cli_wrong_password_is_not_shown(committed_seed: str, capsys: pytest.CaptureFixture[str]) -> None:
    wrong = "Wrong-Seed-Pa55-q7"
    url = make_url(committed_seed).set(password=wrong).render_as_string(hide_password=False)
    assert seed_cli.main(["--database-url", url]) == 1
    captured = capsys.readouterr()
    assert wrong not in captured.err + captured.out
    assert "Не удалось загрузить демо-данные" in captured.err
