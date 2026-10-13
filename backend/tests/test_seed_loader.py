"""Загрузчик сид-данных ``app.seed.loader`` (#53, ADR-7.12) без PostgreSQL.

Сессия подменяется ``AsyncMock``: каждый запрос компилируется диалектом PostgreSQL, тест проверяет
текст и параметры. Так без БД (в том числе в Windows-матрице CI) проверяется контракт загрузчика:

- порядок запросов: родитель раньше дочерних строк, заказ после визита;
- идемпотентность: ``ON CONFLICT`` по естественным ключам ADR-7.12, ``DO UPDATE`` для эталонных
  данных и ``DO NOTHING`` для истории (заказ, строки, событие, связи с аллергенами);
- защита чужих строк: ``WHERE tenant_id`` в ``DO UPDATE`` и ``SeedError`` с остановкой загрузки;
- дочерние строки ссылаются на ``RETURNING id`` (ключ существующей строки), а не на константы сида.

Совпадение ``ON CONFLICT`` с настоящими уникальными индексами и итоговые счётчики строк
проверяются только на реальной схеме — ``tests/db/test_seed.py``.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Delete, Insert, Select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ActorType, OrderEventType, OrderStatus, VisitStatus
from app.models.menu import MenuItemPrice
from app.models.reference import EU14_ALLERGEN_CODES
from app.seed import data, loader
from app.seed.loader import SeededTable, SeedError, apply_seed

DIALECT = postgresql.dialect()


@dataclass
class Call:
    """Один запрос к сессии: вид, таблица, SQL, параметры и что вернула «БД»."""

    kind: str
    table: str
    sql: str
    params: dict[str, Any]
    returned: uuid.UUID | None = None


@dataclass
class FakeDatabase:
    """Подмена ``AsyncSession.execute``: ``RETURNING id`` выдаёт новые UUID (как будто строки уже
    были с другими ключами), ``foreign`` — таблицы, где строка с ключом сида принадлежит другому
    заведению (``DO UPDATE … WHERE`` ничего не вернул), ``existing_order_id`` — ответ SELECT заказа."""

    foreign: frozenset[str] = frozenset()
    existing_order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    calls: list[Call] = field(default_factory=list)
    summary: loader.SeedSummary | None = None

    def session(self) -> AsyncSession:
        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=self._execute)
        return session

    async def _execute(self, statement: Any) -> MagicMock:
        compiled = statement.compile(dialect=DIALECT)
        sql = " ".join(str(compiled).split())
        result = MagicMock()
        if isinstance(statement, Select):
            call = Call("select", "orders", sql, dict(compiled.params), self.existing_order_id)
            result.scalar_one.return_value = self.existing_order_id
        else:
            kind = "insert" if isinstance(statement, Insert) else "delete"
            assert isinstance(statement, Insert | Delete), type(statement)
            table = statement.table.name  # type: ignore[union-attr]
            returned = None
            if "RETURNING" in sql and table not in self.foreign:
                returned = uuid.uuid4()
            call = Call(kind, table, sql, dict(compiled.params), returned)
            result.scalar_one_or_none.return_value = returned
        self.calls.append(call)
        return result

    def of(self, table: str, kind: str = "insert") -> list[Call]:
        return [call for call in self.calls if call.table == table and call.kind == kind]

    def tables_in_order(self) -> list[str]:
        """Таблицы в порядке первого обращения."""
        return list(dict.fromkeys(call.table for call in self.calls))


async def _seed(database: FakeDatabase) -> loader.SeedSummary:
    database.summary = await apply_seed(database.session())
    return database.summary


@pytest.fixture(scope="module")
def database() -> FakeDatabase:
    """Один прогон ``apply_seed`` на модуль: компиляция ~120 запросов заметна под coverage, а
    тесты только читают записанные вызовы."""
    seeded = FakeDatabase()
    asyncio.run(_seed(seeded))
    return seeded


def _conflict(sql: str) -> str:
    """Часть ``ON CONFLICT …`` без ``RETURNING``."""
    match = re.search(r"ON CONFLICT (.*?)(?: RETURNING .*)?$", sql)
    assert match is not None, sql
    return match.group(1)


def _conflict_target(sql: str) -> str | None:
    match = re.match(r"\(([^)]*)\) DO UPDATE", _conflict(sql))
    return match.group(1) if match else None


def _updated_columns(sql: str) -> set[str]:
    match = re.search(r"DO UPDATE SET (.*?)(?: WHERE .*)?$", _conflict(sql))
    assert match is not None, sql
    return {part.split(" = ")[0] for part in match.group(1).split(", ")}


def _ids(calls: Iterable[Call]) -> list[uuid.UUID | None]:
    return [call.returned for call in calls]


# ---------------------------------------------------------------- порядок и объём


def test_parents_are_written_before_children(database: FakeDatabase) -> None:
    """Каждая таблица впервые затрагивается после всех таблиц, на которые она ссылается."""
    assert database.tables_in_order() == [
        "tenants",
        "allergens",
        "halls",
        "tables",
        "categories",
        "menu_items",
        "menu_item_prices",
        "menu_item_meta",
        "menu_item_allergens",
        "visits",
        "messages",
        "cart_items",
        "orders",
        "order_items",
        "order_events",
    ]
    # Заказ ищется по ключу идемпотентности после вставки и до его строк.
    kinds = [(call.kind, call.table) for call in database.calls]
    select_at = kinds.index(("select", "orders"))
    assert kinds[select_at - 1] == ("insert", "orders")
    assert kinds[select_at + 1] == ("insert", "order_items")


def test_statement_count_matches_dataset(database: FakeDatabase) -> None:
    """Один запрос на строку данных сида, одно удаление лишних связей на блюдо — без лишних
    обращений (повторный запуск делает ровно то же самое)."""
    expected = {
        ("insert", "tenants"): 1,
        ("insert", "allergens"): len(EU14_ALLERGEN_CODES),
        ("insert", "halls"): len(data.HALLS),
        ("insert", "tables"): len(data.TABLES),
        ("insert", "categories"): len(data.CATEGORIES),
        ("insert", "menu_items"): len(data.DISHES),
        ("insert", "menu_item_prices"): sum(len(dish.prices) for dish in data.DISHES),
        ("insert", "menu_item_meta"): len(data.DISHES),
        ("delete", "menu_item_allergens"): len(data.DISHES),
        ("insert", "menu_item_allergens"): sum(len(dish.allergens) for dish in data.DISHES),
        ("insert", "visits"): 1,
        ("insert", "messages"): len(data.VISIT.messages),
        ("insert", "cart_items"): len(data.VISIT.cart),
        ("insert", "orders"): 1,
        ("select", "orders"): 1,
        ("insert", "order_items"): len(data.ORDER.lines),
        ("insert", "order_events"): 1,
    }
    counts: dict[tuple[str, str], int] = {}
    for call in database.calls:
        counts[(call.kind, call.table)] = counts.get((call.kind, call.table), 0) + 1
    assert counts == expected

    second = FakeDatabase()
    asyncio.run(_seed(second))
    assert [(c.kind, c.table, c.sql) for c in second.calls] == [(c.kind, c.table, c.sql) for c in database.calls]


# ---------------------------------------------------------------- идемпотентность (ADR-7.12)

UPSERT_KEYS: dict[str, str] = {
    "tenants": "id",
    "allergens": "tenant_id, code",
    "halls": "tenant_id, name",
    "tables": "qr_token",
    "categories": "tenant_id, external_id",
    "menu_items": "tenant_id, external_id",
    "menu_item_prices": "menu_item_id, price_tier",
    "menu_item_meta": "menu_item_id",
    "visits": "id",
    "messages": "id",
    "cart_items": "tenant_id, visit_id, menu_item_id, comment",
}
HISTORY_TABLES = ("orders", "order_items", "order_events", "menu_item_allergens")


@pytest.mark.parametrize(("table", "key"), sorted(UPSERT_KEYS.items()))
def test_reference_rows_are_upserted_by_natural_key(database: FakeDatabase, table: str, key: str) -> None:
    calls = database.of(table)
    assert calls
    assert {_conflict_target(call.sql) for call in calls} == {key}


@pytest.mark.parametrize("table", HISTORY_TABLES)
def test_history_rows_are_insert_only(database: FakeDatabase, table: str) -> None:
    """Заказ, строки, событие ``created`` (журнал append-only, ADR-7.6) и связи с аллергенами —
    ``ON CONFLICT DO NOTHING``; ``UPDATE`` этих таблиц сид не выполняет."""
    calls = database.of(table)
    assert calls
    assert {_conflict(call.sql) for call in calls} == {"DO NOTHING"}
    assert not any(f"UPDATE {table}" in call.sql for call in database.calls)


def test_only_allergen_links_are_deleted(database: FakeDatabase) -> None:
    """Единственный DELETE — лишние связи демо-позиции с аллергенами: по заведению и позиции."""
    tenant_id = database.of("tenants")[0].returned
    deletes = [call for call in database.calls if call.kind == "delete"]
    assert {call.table for call in deletes} == {"menu_item_allergens"}
    item_ids = _ids(database.of("menu_items"))
    for call, item_id, dish in zip(deletes, item_ids, data.DISHES, strict=True):
        assert "menu_item_allergens.tenant_id = " in call.sql
        assert "menu_item_allergens.menu_item_id = " in call.sql
        assert "menu_item_allergens.allergen_id NOT IN" in call.sql
        assert call.params["tenant_id_1"] == tenant_id
        assert call.params["menu_item_id_1"] == item_id
        assert len(call.params["allergen_id_1"]) == len(dish.allergens)


def test_dish_without_allergens_drops_all_links(database: FakeDatabase) -> None:
    """У блюда с пустым эталонным списком удаляются все связи (``NOT IN ()``), вставок нет."""
    dish = next(d for d in data.DISHES if not d.allergens)
    position = [d.external_id for d in data.DISHES].index(dish.external_id)
    delete = database.of("menu_item_allergens", "delete")[position]
    assert delete.params["allergen_id_1"] == []
    item_id = database.of("menu_items")[position].returned
    assert not [c for c in database.of("menu_item_allergens") if c.params["menu_item_id"] == item_id]


def test_updated_at_is_refreshed_explicitly(database: FakeDatabase) -> None:
    """``onupdate`` ORM на Core-UPSERT не срабатывает: ``updated_at = now()`` задаётся явно там, где
    колонка есть, и не появляется в таблицах без неё."""
    for table in UPSERT_KEYS:
        sql = database.of(table)[0].sql
        has_column = table != "messages"
        assert ("updated_at = now()" in sql) is has_column, table


def test_reference_upsert_restores_every_seed_column(database: FakeDatabase) -> None:
    """``DO UPDATE`` переписывает все поля сида, кроме ключа: повторный запуск возвращает эталон."""
    assert _updated_columns(database.of("menu_items")[0].sql) == {
        "category_id",
        "pos_name",
        "currency",
        "station",
        "sort_key",
        "is_available",
        "is_hidden",
        "synced_at",
        "updated_at",
    }
    assert _updated_columns(database.of("visits")[0].sql) == {
        "table_id",
        "status",
        "lang",
        "last_activity_at",
        "closed_at",
        "closed_by",
        "closed_by_staff_id",
        "updated_at",
    }
    assert _updated_columns(database.of("menu_item_prices")[0].sql) == {"price", "updated_at"}


# ---------------------------------------------------------------- чужие строки


@pytest.mark.parametrize("table", ["tables", "visits", "messages"])
def test_global_keys_are_guarded_by_tenant(database: FakeDatabase, table: str) -> None:
    """Ключ без ``tenant_id`` (токен стола, фиксированный id визита и сообщений): ``DO UPDATE``
    меняет строку, только если она принадлежит демо-заведению."""
    tenant_id = database.of("tenants")[0].returned
    for call in database.of(table):
        assert f"WHERE {table}.tenant_id = " in _conflict(call.sql)
        assert call.params["tenant_id_1"] == tenant_id


@pytest.mark.parametrize("table", ["tables", "visits", "messages"])
async def test_foreign_row_raises_seed_error_and_stops(table: str) -> None:
    """Строка с ключом сида у другого заведения: ``SeedError`` с именем таблицы, следующих
    запросов нет (вызывающий откатывает транзакцию, частичной загрузки нет)."""
    database = FakeDatabase(foreign=frozenset({table}))
    with pytest.raises(SeedError, match=table):
        await _seed(database)
    assert database.calls[-1].table == table
    assert database.calls[-1].returned is None
    assert not database.of("orders")


async def test_upsert_without_id_column_returns_none() -> None:
    """Таблица без ``id`` (цены): запрос без ``RETURNING``, результат ``None`` — это не ошибка."""
    database = FakeDatabase()
    session = database.session()
    result = await loader._upsert(
        session,
        MenuItemPrice,
        {"tenant_id": uuid.uuid4(), "menu_item_id": uuid.uuid4(), "price_tier": "default", "price": Decimal("1.00")},
        ["menu_item_id", "price_tier"],
        ["price"],
    )
    assert result is None
    assert "RETURNING" not in database.calls[0].sql


# ---------------------------------------------------------------- ссылки на существующие строки


def test_children_reference_ids_returned_by_database(database: FakeDatabase) -> None:
    """Дочерние строки берут ``RETURNING id`` родителя (строка могла существовать с другим id)."""
    summary = database.summary
    assert summary is not None
    tenant_id = database.of("tenants")[0].returned
    assert summary.tenant_id == tenant_id

    for call in database.calls:
        if call.table != "tenants" and "tenant_id" in call.params:
            assert call.params["tenant_id"] == tenant_id, call.table

    halls = dict(zip((hall.key for hall in data.HALLS), _ids(database.of("halls")), strict=True))
    for call, table in zip(database.of("tables"), data.TABLES, strict=True):
        assert call.params["hall_id"] == halls[table.hall]

    categories = dict(zip((c.external_id for c in data.CATEGORIES), _ids(database.of("categories")), strict=True))
    items = dict(zip((d.external_id for d in data.DISHES), _ids(database.of("menu_items")), strict=True))
    for call, dish in zip(database.of("menu_items"), data.DISHES, strict=True):
        assert call.params["category_id"] == categories[dish.category]
    assert {call.params["menu_item_id"] for call in database.of("menu_item_prices")} == set(items.values())
    assert [call.params["menu_item_id"] for call in database.of("menu_item_meta")] == list(items.values())

    tables = dict(zip((t.qr_token for t in data.TABLES), _ids(database.of("tables")), strict=True))
    [visit] = database.of("visits")
    assert visit.params["table_id"] == tables[data.VISIT.table_token]
    for call in database.of("messages") + database.of("cart_items") + database.of("orders"):
        assert call.params["visit_id"] == visit.returned
    for call, line in zip(database.of("cart_items"), data.VISIT.cart, strict=True):
        assert call.params["menu_item_id"] == items[line.dish]


async def test_order_children_attach_to_order_found_by_idempotency_key() -> None:
    """Заказ мог быть создан раньше с другим id по тому же ключу: строки и событие ``created``
    ссылаются на найденный заказ, а не на ``data.ORDER.id``."""
    existing = uuid.uuid4()
    database = FakeDatabase(existing_order_id=existing)
    await _seed(database)
    [lookup] = [call for call in database.calls if call.kind == "select"]
    assert "orders.tenant_id = " in lookup.sql
    assert "orders.idempotency_key = " in lookup.sql
    assert lookup.params["idempotency_key_1"] == data.ORDER.idempotency_key
    assert {call.params["order_id"] for call in database.of("order_items")} == {existing}
    [event] = database.of("order_events")
    assert event.params["order_id"] == existing
    assert existing != data.ORDER.id


# ---------------------------------------------------------------- значения


def test_visit_is_reopened_and_messages_unredacted(database: FakeDatabase) -> None:
    [visit] = database.of("visits")
    assert visit.params["id"] == data.VISIT.id
    assert visit.params["status"] == VisitStatus.OPEN
    assert (visit.params["closed_at"], visit.params["closed_by"], visit.params["closed_by_staff_id"]) == (
        None,
        None,
        None,
    )
    for call, message in zip(database.of("messages"), data.VISIT.messages, strict=True):
        assert call.params["id"] == message.id
        assert call.params["redacted_at"] is None
        assert call.params["content"] == [{"type": "text", "text": message.text}]


def test_cart_and_order_use_visit_table_price_tier(database: FakeDatabase) -> None:
    """Корзина и заказ — по тарифу стола визита; деньги — ``Decimal``; снимок — кассовое название."""
    tier = data.table_by_token(data.VISIT.table_token).price_tier
    for call, line in zip(database.of("cart_items"), data.VISIT.cart, strict=True):
        dish = data.dish_by_external_id(line.dish)
        assert call.params["price_tier"] == tier
        assert call.params["price_at_add"] == data.price_for(dish, tier)
        assert isinstance(call.params["price_at_add"], Decimal)
        assert (call.params["qty"], call.params["comment"]) == (line.qty, line.comment)

    [order] = database.of("orders")
    assert order.params["id"] == data.ORDER.id
    assert order.params["status"] == OrderStatus.SUBMITTED
    assert order.params["price_tier"] == tier
    assert order.params["total"] == data.order_total(data.ORDER, tier)
    assert isinstance(order.params["total"], Decimal)
    assert order.params["currency"] == data.TENANT.currency

    for call, line in zip(database.of("order_items"), data.ORDER.lines, strict=True):
        dish = data.dish_by_external_id(line.dish)
        assert call.params["id"] == line.id
        assert call.params["name_snapshot"] == dish.pos_name
        assert call.params["price_at_order"] == data.price_for(dish, tier)

    [event] = database.of("order_events")
    assert event.params["id"] == data.ORDER.created_event_id
    assert (event.params["type"], event.params["to_status"], event.params["actor_type"]) == (
        OrderEventType.CREATED,
        OrderStatus.SUBMITTED,
        ActorType.GUEST,
    )


def test_tables_keep_seed_tokens_and_tenant_is_fixed(database: FakeDatabase) -> None:
    [tenant] = database.of("tenants")
    assert tenant.params["id"] == data.DEMO_TENANT_ID
    assert tenant.params["settings"] == {}
    assert [call.params["qr_token"] for call in database.of("tables")] == [t.qr_token for t in data.TABLES]
    assert [call.params["code"] for call in database.of("allergens")] == list(EU14_ALLERGEN_CODES)


def test_summary_lists_every_table_with_activity_flag(database: FakeDatabase) -> None:
    summary = database.summary
    assert summary is not None
    assert summary.tables == tuple(SeededTable(t.name, t.qr_token, t.is_active) for t in data.TABLES)
    assert any(not table.is_active for table in summary.tables)
