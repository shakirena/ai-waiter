"""Инварианты ``Base.metadata`` без БД (ADR-7.2, 7.3, 7.4, 7.8, DEC-006): идут на Windows и Linux.

Проверки общие для всех таблиц модели: новая таблица без ``tenant_id``, с простым FK на таблицу
заведения, с деньгами не в ``NUMERIC(10,2)`` или с именем ограничения не по соглашению ломает тест.
"""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)

import app.models  # noqa: F401 — регистрирует все таблицы
from app.db.base import Base
from app.models.checks import (
    sql_between,
    sql_in,
    sql_length,
    sql_match,
    sql_not_in,
    sql_not_match,
    sql_text_array,
)
from app.models.enums import (
    ABSOLUTE_PATH_PATTERN,
    ALLERGEN_CODE_PATTERN,
    CONFIRMED_STATUSES,
    CURRENCY_PATTERN,
    PRICE_TIER_PATTERN,
    QR_TOKEN_PATTERN,
    ActorType,
    Lang,
    MessageRole,
    OrderEventType,
    OrderStatus,
    TableType,
    VisitClosedBy,
    VisitStatus,
    WeightUnit,
)
from app.models.menu import Allergen
from app.models.reference import EU14_ALLERGEN_CODES, EU14_ALLERGENS, default_allergen_rows

TABLES = Base.metadata.tables
TENANT_TABLES = [table for name, table in TABLES.items() if name != "tenants"]
PG_IDENTIFIER_MAX = 63

# Ожидаемые таблицы по ревизиям (дополняются вместе с новой ревизией).
EXPECTED_TABLES = {
    "tenants",
    "halls",
    "tables",
    "categories",
    "menu_items",
    "menu_item_prices",
    "menu_item_meta",
    "allergens",
    "menu_item_allergens",
    "visits",
    "messages",
    "cart_items",
    "orders",
    "order_items",
    "order_events",
}

# Явный список CHECK по таблицам (короткие имена: ck_<table>_<name>).
EXPECTED_CHECKS: dict[str, set[str]] = {
    "tenants": {"name", "currency", "languages", "settings"},
    "halls": {"name"},
    "tables": {"name", "type", "price_tier", "external_id", "qr_token"},
    "categories": {"external_id", "name_az", "name_ru"},
    "menu_items": {"external_id", "currency"},
    "menu_item_prices": {"price_tier", "price"},
    "menu_item_meta": {
        "name_az",
        "name_ru",
        "description_az",
        "description_ru",
        "ingredients_az",
        "ingredients_ru",
        "spice_level",
        "prep_minutes",
        "weight_amount",
        "weight_unit",
        "weight",
        "photo_path",
    },
    "allergens": {"code", "name_az", "name_ru"},
    "menu_item_allergens": set(),
    "visits": {"status", "lang", "closed_by", "closed_state"},
    "messages": {
        "role",
        "text",
        "content",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
        "cost_usd",
        "latency_ms",
        "content_or_redacted",
        "redacted_empty",
    },
    "cart_items": {"qty", "comment", "price_tier", "price_at_add"},
    "orders": {
        "status",
        "price_tier",
        "total",
        "currency",
        "pos_total",
        "reject_reason_length",
        "pos_ref",
        "pos_error",
        "confirmed_at",
        "reject_reason",
    },
    "order_items": {"qty", "price_at_order", "comment"},
    "order_events": {"type", "from_status", "to_status", "actor_type", "payload", "status_change"},
}

# Numeric-колонки, которые не являются деньгами гостя NUMERIC(10,2) (ADR-7.4).
NUMERIC_EXCEPTIONS: dict[tuple[str, str], tuple[int, int]] = {
    ("menu_item_meta", "weight_amount"): (8, 2),  # вес/объём порции, не деньги
    ("messages", "cost_usd"): (12, 6),  # стоимость вызова ИИ в долях цента (NFR-7)
}


def _table_ids() -> list[str]:
    return sorted(TABLES)


def _checks(table: Table) -> dict[str, CheckConstraint]:
    return {str(c.name): c for c in table.constraints if isinstance(c, CheckConstraint)}


def _fks(table: Table) -> list[ForeignKeyConstraint]:
    return [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]


def _uniques(table: Table) -> list[tuple[str, ...]]:
    return [tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)]


def test_expected_tables_registered() -> None:
    assert EXPECTED_TABLES <= set(TABLES)


@pytest.mark.parametrize("table", TENANT_TABLES, ids=lambda t: t.name)
def test_tenant_id_not_null_with_fk_to_tenants(table: Table) -> None:
    column = table.c.tenant_id
    assert not column.nullable
    assert isinstance(column.type, Uuid)
    [fk] = [fk for fk in _fks(table) if fk.referred_table.name == "tenants"]
    assert [c.name for c in fk.columns] == ["tenant_id"]
    assert fk.ondelete == "RESTRICT"


def test_tenants_has_no_tenant_id() -> None:
    assert "tenant_id" not in TABLES["tenants"].c


@pytest.mark.parametrize("table", TENANT_TABLES, ids=lambda t: t.name)
def test_tenant_tables_with_id_have_unique_tenant_id_id(table: Table) -> None:
    if "id" in table.c:
        assert ("tenant_id", "id") in _uniques(table)


@pytest.mark.parametrize("table", TENANT_TABLES, ids=lambda t: t.name)
def test_references_inside_tenant_are_composite(table: Table) -> None:
    """Каждый FK на таблицу заведения — ``(tenant_id, x_id) → parent (tenant_id, id)``."""
    for fk in _fks(table):
        if fk.referred_table.name == "tenants":
            continue
        assert fk.column_keys[0] == "tenant_id", fk.name
        assert [element.column.name for element in fk.elements] == ["tenant_id", "id"], fk.name
        assert fk.ondelete in {"RESTRICT", "CASCADE"}, fk.name


@pytest.mark.parametrize("name", _table_ids())
def test_primary_keys_and_references_are_uuid(name: str) -> None:
    table = TABLES[name]
    for column in table.c:
        if column.name == "id" or (column.name.endswith("_id") and column.name != "external_id"):
            assert isinstance(column.type, Uuid), f"{name}.{column.name}"
    if "id" in table.c:
        assert table.c.id.primary_key
        assert "gen_random_uuid()" in str(table.c.id.server_default.arg)


@pytest.mark.parametrize("name", _table_ids())
def test_constraint_names_follow_convention(name: str) -> None:
    table = TABLES[name]
    for constraint in table.constraints:
        constraint_name = str(constraint.name)
        assert len(constraint_name) <= PG_IDENTIFIER_MAX, constraint_name
        if isinstance(constraint, PrimaryKeyConstraint):
            assert constraint_name == f"pk_{name}"
        elif isinstance(constraint, ForeignKeyConstraint):
            columns = "_".join(c.name for c in constraint.columns)
            assert constraint_name == f"fk_{name}_{columns}_{constraint.referred_table.name}"
        elif isinstance(constraint, UniqueConstraint):
            assert constraint_name == f"uq_{name}_{'_'.join(constraint.columns.keys())}"
        elif isinstance(constraint, CheckConstraint):
            assert constraint_name.startswith(f"ck_{name}_")
    for index in table.indexes:
        assert str(index.name).startswith(("ix_", "uq_")), index.name
        assert len(str(index.name)) <= PG_IDENTIFIER_MAX


@pytest.mark.parametrize("name", _table_ids())
def test_datetimes_are_timestamptz(name: str) -> None:
    for column in TABLES[name].c:
        if isinstance(column.type, DateTime):
            assert column.type.timezone, f"{name}.{column.name}"
        if column.name.endswith("_at"):
            assert isinstance(column.type, DateTime), f"{name}.{column.name}"


@pytest.mark.parametrize("name", _table_ids())
def test_numeric_columns_are_money_or_listed_exceptions(name: str) -> None:
    for column in TABLES[name].c:
        if not isinstance(column.type, Numeric):
            continue
        expected = NUMERIC_EXCEPTIONS.get((name, column.name), (10, 2))
        assert (column.type.precision, column.type.scale) == expected, f"{name}.{column.name}"
        assert column.type.asdecimal


@pytest.mark.parametrize("name", _table_ids())
def test_timestamps_present(name: str) -> None:
    columns = TABLES[name].c
    assert "created_at" in columns


@pytest.mark.parametrize(("name", "expected"), sorted(EXPECTED_CHECKS.items()))
def test_expected_checks_present(name: str, expected: set[str]) -> None:
    assert set(_checks(TABLES[name])) == {f"ck_{name}_{short}" for short in expected}


def _check_text(table: str, short: str) -> str:
    return str(_checks(TABLES[table])[f"ck_{table}_{short}"].sqltext)


def test_check_texts_built_from_enums_and_patterns() -> None:
    assert _check_text("tables", "type") == sql_in("type", TableType)
    for value in TableType:
        assert f"'{value}'" in _check_text("tables", "type")
    assert _check_text("tables", "price_tier") == sql_match("price_tier", PRICE_TIER_PATTERN)
    assert _check_text("tables", "qr_token") == sql_match("qr_token", QR_TOKEN_PATTERN)
    assert _check_text("tenants", "currency") == sql_match("currency", CURRENCY_PATTERN)
    assert sql_text_array(Lang) in _check_text("tenants", "languages")


def test_tenant_defaults() -> None:
    tenants = TABLES["tenants"]
    assert str(tenants.c.currency.server_default.arg) == "AZN"
    assert str(tenants.c.timezone.server_default.arg) == "Asia/Baku"
    assert str(tenants.c.languages.server_default.arg) == "'{az,ru}'::text[]"
    assert str(tenants.c.settings.server_default.arg) == "'{}'::jsonb"


def test_table_defaults_and_uniques() -> None:
    tables = TABLES["tables"]
    assert str(tables.c.type.server_default.arg) == TableType.TABLE
    assert str(tables.c.price_tier.server_default.arg) == "default"
    assert str(tables.c.is_active.server_default.arg) == "true"
    assert tables.c.hall_id.nullable
    assert tables.c.external_id.nullable
    assert ("qr_token",) in _uniques(tables)
    assert ("tenant_id", "external_id") in _uniques(tables)
    assert {index.name for index in tables.indexes} == {"ix_tables_tenant_id_hall_id"}
    assert ("tenant_id", "name") in _uniques(TABLES["halls"])


def test_sort_keys_use_c_collation() -> None:
    for table in TABLES.values():
        if "sort_key" in table.c:
            assert isinstance(table.c.sort_key.type, Text)
            assert table.c.sort_key.type.collation == "C", table.name


# ------------------------------------------------------------ построители CHECK


def test_sql_builders_render_expected_text() -> None:
    assert sql_in("type", ["a", "b"]) == "type IN ('a', 'b')"
    assert sql_text_array(["az", "ru"]) == "ARRAY['az', 'ru']::text[]"
    assert sql_match("code", "^[a-z]$") == "code ~ '^[a-z]$'"
    assert sql_length("name", 100, 1) == "char_length(name) BETWEEN 1 AND 100"
    assert sql_length("name_az", 200) == "char_length(name_az) <= 200"
    assert sql_between("spice_level", 0, 3) == "spice_level BETWEEN 0 AND 3"
    assert sql_not_match("photo_path", "^/") == "photo_path !~ '^/'"
    assert sql_not_in("status", ["rejected"]) == "status NOT IN ('rejected')"
    assert sql_not_in("type", ["a", "b"]) == "type NOT IN ('a', 'b')"


@pytest.mark.parametrize("value", ["it's", "nul\x00"])
def test_sql_builders_reject_unsafe_literals(value: str) -> None:
    with pytest.raises(ValueError, match="недопустимый символ"):
        sql_in("type", [value])
    with pytest.raises(ValueError, match="недопустимый символ"):
        sql_match("type", value)
    with pytest.raises(ValueError, match="недопустимый символ"):
        sql_not_in("type", [value])


@pytest.mark.parametrize("column", ["Name", "name; DROP", "1col", ""])
def test_sql_builders_reject_bad_column(column: str) -> None:
    with pytest.raises(ValueError, match="имя колонки"):
        sql_length(column, 10)


def test_sql_in_requires_values() -> None:
    with pytest.raises(ValueError, match="без значений"):
        sql_in("type", [])


# ------------------------------------------------------------ меню (#50)


def _fk(table: str, referred: str) -> ForeignKeyConstraint:
    [fk] = [fk for fk in _fks(TABLES[table]) if fk.referred_table.name == referred]
    return fk


@pytest.mark.parametrize(
    ("table", "referred", "ondelete"),
    [
        ("menu_items", "categories", "RESTRICT"),
        ("menu_item_prices", "menu_items", "CASCADE"),
        ("menu_item_meta", "menu_items", "CASCADE"),
        ("menu_item_allergens", "menu_items", "CASCADE"),
        ("menu_item_allergens", "allergens", "RESTRICT"),
    ],
)
def test_menu_on_delete_rules(table: str, referred: str, ondelete: str) -> None:
    """ADR-7.3: CASCADE только для строк, принадлежащих позиции; данные кассы — RESTRICT."""
    assert _fk(table, referred).ondelete == ondelete


def test_menu_primary_keys() -> None:
    def pk(name: str) -> list[str]:
        return [c.name for c in TABLES[name].primary_key.columns]

    assert pk("menu_item_prices") == ["menu_item_id", "price_tier"]
    assert pk("menu_item_meta") == ["menu_item_id"]
    assert pk("menu_item_allergens") == ["menu_item_id", "allergen_id"]
    assert pk("categories") == pk("menu_items") == pk("allergens") == ["id"]


def test_menu_uniques_and_indexes() -> None:
    assert ("tenant_id", "external_id") in _uniques(TABLES["categories"])
    assert ("tenant_id", "external_id") in _uniques(TABLES["menu_items"])
    assert ("tenant_id", "code") in _uniques(TABLES["allergens"])
    assert {i.name for i in TABLES["menu_items"].indexes} == {"ix_menu_items_tenant_id_category_id"}
    assert {i.name for i in TABLES["menu_item_allergens"].indexes} == {"ix_menu_item_allergens_tenant_id_allergen_id"}


def test_menu_defaults() -> None:
    meta = TABLES["menu_item_meta"].c
    assert str(meta.allergens_verified.server_default.arg) == "false"
    assert str(meta.visible_to_ai.server_default.arg) == "true"
    assert str(meta.tags.server_default.arg) == "'{}'::text[]"
    items = TABLES["menu_items"].c
    assert str(items.is_available.server_default.arg) == "true"
    assert str(items.is_hidden.server_default.arg) == "false"
    assert str(TABLES["categories"].c.is_hidden.server_default.arg) == "false"
    assert str(TABLES["allergens"].c.sort_order.server_default.arg) == "0"
    assert "updated_at" not in TABLES["menu_item_allergens"].c


def test_menu_check_texts() -> None:
    assert _check_text("menu_item_meta", "spice_level") == sql_between("spice_level", 0, 3)
    assert _check_text("menu_item_meta", "prep_minutes") == sql_between("prep_minutes", 1, 240)
    assert _check_text("menu_item_meta", "weight_unit") == sql_in("weight_unit", WeightUnit)
    assert _check_text("menu_item_meta", "photo_path").startswith(sql_not_match("photo_path", ABSOLUTE_PATH_PATTERN))
    assert _check_text("menu_item_prices", "price") == "price >= 0"
    assert _check_text("menu_item_prices", "price_tier") == sql_match("price_tier", PRICE_TIER_PATTERN)
    assert _check_text("menu_items", "currency") == sql_match("currency", CURRENCY_PATTERN)
    assert _check_text("allergens", "code") == sql_match("code", ALLERGEN_CODE_PATTERN)


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("menu/plov.jpg", True),
        ("plov.webp", True),
        ("/etc/passwd", False),
        (r"\\server\share\a.jpg", False),
        ("C:/photos/a.jpg", False),
        (r"c:\photos\a.jpg", False),
        ("menu/../secret.jpg", False),
    ],
)
def test_photo_path_pattern_semantics(path: str, allowed: bool) -> None:
    """Тот же шаблон, что в CHECK (в Python и PostgreSQL он значит одно); в БД — ``test_menu.py``."""
    rejected = re.search(ABSOLUTE_PATH_PATTERN, path) is not None or ".." in path
    assert rejected is not allowed


# ------------------------------------------------------------ справочник аллергенов


def test_eu14_allergens_reference() -> None:
    assert len(EU14_ALLERGENS) == 14
    assert EU14_ALLERGEN_CODES == tuple(a.code for a in EU14_ALLERGENS)
    assert len(set(EU14_ALLERGEN_CODES)) == 14
    for allergen in EU14_ALLERGENS:
        assert re.match(ALLERGEN_CODE_PATTERN, allergen.code)
        assert 1 <= len(allergen.name_az) <= 100
        assert 1 <= len(allergen.name_ru) <= 100


def test_default_allergen_rows_for_tenant() -> None:
    tenant_id = uuid.uuid4()
    rows = default_allergen_rows(tenant_id)
    assert [row["code"] for row in rows] == list(EU14_ALLERGEN_CODES)
    assert {row["tenant_id"] for row in rows} == {tenant_id}
    orders = [row["sort_order"] for row in rows]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)
    assert set(rows[0]) == {"tenant_id", "code", "name_az", "name_ru", "sort_order"}
    # Чистая функция: новый список при каждом вызове, исходные данные не меняются.
    rows[0]["name_ru"] = "изменено"
    assert default_allergen_rows(tenant_id)[0]["name_ru"] == EU14_ALLERGENS[0].name_ru
    allergen = Allergen(**rows[1])
    assert allergen.code == EU14_ALLERGEN_CODES[1]


# ------------------------------------------------------------ визит (#51)


def _index(table: str, name: str) -> Index:
    [index] = [i for i in TABLES[table].indexes if i.name == name]
    return index


def _index_columns(table: str, name: str) -> list[str]:
    return [c.name for c in _index(table, name).columns]


def _where(table: str, name: str) -> str:
    return str(_index(table, name).dialect_options["postgresql"]["where"])


@pytest.mark.parametrize(
    ("table", "referred", "ondelete"),
    [
        ("visits", "tables", "RESTRICT"),
        ("messages", "visits", "CASCADE"),
        ("cart_items", "visits", "CASCADE"),
        ("cart_items", "menu_items", "RESTRICT"),
    ],
)
def test_visit_on_delete_rules(table: str, referred: str, ondelete: str) -> None:
    """ADR-7.3: сообщения и корзина принадлежат визиту (CASCADE), стол и позиция меню — RESTRICT."""
    assert _fk(table, referred).ondelete == ondelete


def test_visit_indexes() -> None:
    """ADR-7.5: один открытый визит на стол — частичный уникальный индекс; подметание — частичный индекс."""
    assert {i.name for i in TABLES["visits"].indexes} == {
        "uq_visits_open_table",
        "ix_visits_tenant_id_table_id_opened_at",
        "ix_visits_open_last_activity",
    }
    assert _index("visits", "uq_visits_open_table").unique
    assert _index_columns("visits", "uq_visits_open_table") == ["table_id"]
    assert _where("visits", "uq_visits_open_table") == sql_in("status", [VisitStatus.OPEN])
    assert _index_columns("visits", "ix_visits_open_last_activity") == ["last_activity_at"]
    assert _where("visits", "ix_visits_open_last_activity") == sql_in("status", [VisitStatus.OPEN])
    assert _index_columns("visits", "ix_visits_tenant_id_table_id_opened_at") == ["tenant_id", "table_id", "opened_at"]


def test_message_indexes_and_columns() -> None:
    messages = TABLES["messages"]
    assert {i.name for i in messages.indexes} == {
        "ix_messages_tenant_id_visit_id_created_at",
        "ix_messages_retention",
        "ix_messages_tenant_id_created_at",
    }
    assert _where("messages", "ix_messages_retention") == "redacted_at IS NULL"
    assert _index_columns("messages", "ix_messages_retention") == ["created_at"]
    # Журнал диалога: только created_at, сообщение не редактируется (кроме обезличивания).
    assert "updated_at" not in messages.c
    for column in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "cost_usd"):
        assert not messages.c[column].nullable, column
        assert str(messages.c[column].server_default.arg) == "0", column
    for column in ("text", "content", "model", "latency_ms", "redacted_at"):
        assert messages.c[column].nullable, column
    # None в Python пишется как SQL NULL, а не JSON null: иначе обезличивание нарушит CHECK.
    assert messages.c.content.type.none_as_null


def test_cart_item_uniques_and_defaults() -> None:
    cart = TABLES["cart_items"]
    assert ("tenant_id", "visit_id", "menu_item_id", "comment") in _uniques(cart)
    assert str(cart.c.comment.server_default.arg) == ""
    assert not cart.c.comment.nullable
    assert not cart.c.price_tier.nullable
    assert cart.c.price_tier.server_default is None
    assert {i.name for i in cart.indexes} == set()


def test_visit_defaults_and_soft_staff_reference() -> None:
    visits = TABLES["visits"]
    assert str(visits.c.status.server_default.arg) == VisitStatus.OPEN
    assert visits.c.lang.server_default is None
    for column in ("opened_at", "last_activity_at"):
        assert str(visits.c[column].server_default.arg) == "now()"
    # ADR-7.7: ссылки на staff_users нет до #19.
    assert not visits.c.closed_by_staff_id.foreign_keys
    assert visits.c.closed_by_staff_id.nullable


def test_visit_check_texts() -> None:
    assert _check_text("visits", "status") == sql_in("status", VisitStatus)
    assert _check_text("visits", "lang") == sql_in("lang", Lang)
    assert _check_text("visits", "closed_by") == sql_in("closed_by", VisitClosedBy)
    assert _check_text("messages", "role") == sql_in("role", MessageRole)
    assert _check_text("messages", "text") == sql_length("text", 8000)
    assert _check_text("messages", "content") == "jsonb_typeof(content) = 'array'"
    assert _check_text("cart_items", "qty") == sql_between("qty", 1, 99)
    assert _check_text("cart_items", "comment") == sql_length("comment", 200)
    assert _check_text("cart_items", "price_tier") == sql_match("price_tier", PRICE_TIER_PATTERN)
    assert _check_text("cart_items", "price_at_add") == "price_at_add >= 0"
    closed_state = _check_text("visits", "closed_state")
    assert sql_in("status", [VisitStatus.OPEN]) in closed_state
    assert sql_in("status", [VisitStatus.CLOSED]) in closed_state


def test_message_roles_are_claude_api_roles() -> None:
    """``tool_result`` передаётся блоками в ``user``; ролей ``tool``/``system`` в сообщениях Claude API нет."""
    assert [role.value for role in MessageRole] == ["user", "assistant"]


# ------------------------------------------------------------ заказ (#52)


@pytest.mark.parametrize(
    ("table", "referred", "ondelete"),
    [
        ("orders", "visits", "RESTRICT"),
        ("order_items", "orders", "CASCADE"),
        ("order_items", "menu_items", "RESTRICT"),
        ("order_events", "orders", "RESTRICT"),
    ],
)
def test_order_on_delete_rules(table: str, referred: str, ondelete: str) -> None:
    """ADR-7.3, 7.6: строки заказа принадлежат заказу; заказы и журнал не удаляются."""
    assert _fk(table, referred).ondelete == ondelete


def test_order_indexes() -> None:
    assert {i.name for i in TABLES["orders"].indexes} == {
        "ix_orders_tenant_id_visit_id",
        "ix_orders_tenant_id_status_created_at",
        "ix_orders_pending_confirm",
        "ix_orders_pos_queue",
    }
    assert _index_columns("orders", "ix_orders_tenant_id_status_created_at") == ["tenant_id", "status", "created_at"]
    assert _index_columns("orders", "ix_orders_pending_confirm") == ["created_at"]
    assert _where("orders", "ix_orders_pending_confirm") == sql_in(
        "status", [OrderStatus.SUBMITTED, OrderStatus.EDITED]
    )
    assert _index_columns("orders", "ix_orders_pos_queue") == ["tenant_id", "confirmed_at", "id"]
    assert _where("orders", "ix_orders_pos_queue") == sql_in("status", [OrderStatus.CONFIRMED, OrderStatus.SENT_TO_POS])
    assert {i.name for i in TABLES["order_events"].indexes} == {"ix_order_events_tenant_id_order_id_created_at"}
    assert {i.name for i in TABLES["order_items"].indexes} == set()


def test_order_uniques_and_types() -> None:
    orders = TABLES["orders"]
    assert ("tenant_id", "idempotency_key") in _uniques(orders)
    assert ("idempotency_key",) not in _uniques(orders)  # не глобально: нет межарендного оракула
    assert isinstance(orders.c.idempotency_key.type, Uuid)
    assert ("tenant_id", "order_id", "menu_item_id", "comment") in _uniques(TABLES["order_items"])
    # ADR-7.7: ссылки на staff_users нет до #19; actor_id — мягкая ссылка навсегда.
    assert not orders.c.confirmed_by_staff_id.foreign_keys
    assert not TABLES["order_events"].c.actor_id.foreign_keys


def test_order_defaults() -> None:
    orders = TABLES["orders"].c
    assert str(orders.status.server_default.arg) == OrderStatus.SUBMITTED
    for column in ("price_tier", "total", "currency"):
        assert not orders[column].nullable, column
        assert orders[column].server_default is None, column
    items = TABLES["order_items"].c
    assert str(items.comment.server_default.arg) == ""
    assert str(items.removed_by_staff.server_default.arg) == "false"
    assert not items.name_snapshot.nullable
    events = TABLES["order_events"].c
    assert str(events.payload.server_default.arg) == "'{}'::jsonb"
    assert "updated_at" not in events


def test_order_check_texts() -> None:
    assert _check_text("orders", "status") == sql_in("status", OrderStatus)
    assert _check_text("orders", "price_tier") == sql_match("price_tier", PRICE_TIER_PATTERN)
    assert _check_text("orders", "currency") == sql_match("currency", CURRENCY_PATTERN)
    assert _check_text("orders", "total") == "total >= 0"
    assert _check_text("orders", "pos_total") == "pos_total >= 0"
    assert _check_text("orders", "reject_reason_length") == sql_length("reject_reason", 500, 1)
    assert _check_text("orders", "pos_ref") == sql_length("pos_ref", 64)
    assert _check_text("orders", "pos_error") == sql_length("pos_error", 1000)
    confirmed = [s for s in OrderStatus if s in CONFIRMED_STATUSES]
    assert _check_text("orders", "confirmed_at") == f"{sql_not_in('status', confirmed)} OR confirmed_at IS NOT NULL"
    assert _check_text("orders", "reject_reason") == "status NOT IN ('rejected') OR reject_reason IS NOT NULL"
    assert _check_text("order_items", "qty") == sql_between("qty", 1, 99)
    assert _check_text("order_items", "price_at_order") == "price_at_order >= 0"
    assert _check_text("order_items", "comment") == sql_length("comment", 200)
    assert _check_text("order_events", "type") == sql_in("type", OrderEventType)
    assert _check_text("order_events", "from_status") == sql_in("from_status", OrderStatus)
    assert _check_text("order_events", "to_status") == sql_in("to_status", OrderStatus)
    assert _check_text("order_events", "actor_type") == sql_in("actor_type", ActorType)
    assert _check_text("order_events", "payload") == "jsonb_typeof(payload) = 'object'"
    assert _check_text("order_events", "status_change") == "type NOT IN ('status_changed') OR to_status IS NOT NULL"


def test_order_event_types_include_manual_pos_entry() -> None:
    assert [t.value for t in OrderEventType] == [
        "created",
        "status_changed",
        "item_removed",
        "item_qty_changed",
        "pos_ack",
        "pos_error",
        "pos_total_mismatch",
        "manual_pos_entry",
    ]
    assert [a.value for a in ActorType] == ["guest", "staff", "connector", "system"]
