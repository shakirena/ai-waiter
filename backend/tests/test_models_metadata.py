"""Инварианты ``Base.metadata`` без БД (ADR-7.2, 7.3, 7.4, 7.8, DEC-006): идут на Windows и Linux.

Проверки общие для всех таблиц модели: новая таблица без ``tenant_id``, с простым FK на таблицу
заведения, с деньгами не в ``NUMERIC(10,2)`` или с именем ограничения не по соглашению ломает тест.
"""

from __future__ import annotations

import pytest
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)

import app.models  # noqa: F401 — регистрирует все таблицы
from app.db.base import Base
from app.models.checks import sql_between, sql_in, sql_length, sql_match, sql_text_array
from app.models.enums import (
    CURRENCY_PATTERN,
    PRICE_TIER_PATTERN,
    QR_TOKEN_PATTERN,
    Lang,
    TableType,
)

TABLES = Base.metadata.tables
TENANT_TABLES = [table for name, table in TABLES.items() if name != "tenants"]
PG_IDENTIFIER_MAX = 63

# Ожидаемые таблицы по ревизиям (дополняются вместе с новой ревизией).
EXPECTED_TABLES = {"tenants", "halls", "tables"}

# Явный список CHECK по таблицам (короткие имена: ck_<table>_<name>).
EXPECTED_CHECKS: dict[str, set[str]] = {
    "tenants": {"name", "currency", "languages", "settings"},
    "halls": {"name"},
    "tables": {"name", "type", "price_tier", "external_id", "qr_token"},
}

# Numeric-колонки, которые не являются деньгами гостя NUMERIC(10,2) (ADR-7.4).
NUMERIC_EXCEPTIONS: dict[tuple[str, str], tuple[int, int]] = {}


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


@pytest.mark.parametrize("value", ["it's", "nul\x00"])
def test_sql_builders_reject_unsafe_literals(value: str) -> None:
    with pytest.raises(ValueError, match="недопустимый символ"):
        sql_in("type", [value])
    with pytest.raises(ValueError, match="недопустимый символ"):
        sql_match("type", value)


@pytest.mark.parametrize("column", ["Name", "name; DROP", "1col", ""])
def test_sql_builders_reject_bad_column(column: str) -> None:
    with pytest.raises(ValueError, match="имя колонки"):
        sql_length(column, 10)


def test_sql_in_requires_values() -> None:
    with pytest.raises(ValueError, match="без значений"):
        sql_in("type", [])
