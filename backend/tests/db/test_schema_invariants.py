"""FR-9, AC-7 (#54): инварианты схемы на реальной БД после ``alembic upgrade head``.

Схема читается из ``information_schema``/``pg_catalog``, а не из моделей (модели проверяет
``tests/test_models_metadata.py``): так ловится и миграция, разошедшаяся с моделью.

- ``tenant_id`` (ТЗ 7, NFR-4, ADR-7.3): в каждой таблице заведения есть ``tenant_id NOT NULL``, и он
  первая колонка хотя бы одного полного (не частичного) индекса — обычного, UNIQUE или PK.
- Деньги (ADR-7.4): явный список денежных колонок — ``numeric(10,2)``; любая другая ``numeric``-колонка
  тоже ``numeric(10,2)``, кроме коротких явных исключений; ``real``/``double precision``/``money`` запрещены.
- Время: ни одной колонки ``timestamp without time zone``; все колонки ``*_at`` — ``timestamptz``.

Функции ``*_violations`` возвращают список нарушений (пустой — всё в порядке) и принимают имя схемы,
поэтому негативные тесты проверяют их на временных таблицах в отдельной схеме внутри транзакции,
которая откатывается.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.db

SCHEMA = "public"

# Таблицы без tenant_id. Список закрыт: новая таблица заведения без tenant_id делает тест красным.
TENANT_EXEMPT_TABLES: dict[str, str] = {
    "tenants": "сама таблица заведений: её id и есть tenant_id остальных таблиц (ADR-7.3)",
    "alembic_version": "служебная таблица Alembic с номером ревизии, данных заведения нет",
}

# Денежные колонки гостя (ADR-7.4): (таблица, колонка). Переименование колонки делает тест красным,
# а не проверку пустой.
MONEY_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        ("menu_item_prices", "price"),
        ("cart_items", "price_at_add"),
        ("orders", "total"),
        ("orders", "pos_total"),
        ("order_items", "price_at_order"),
    }
)
MONEY_TYPE = (10, 2)

# numeric-колонки, которые не являются деньгами гостя: (таблица, колонка) → (precision, scale).
NUMERIC_EXCEPTIONS: dict[tuple[str, str], tuple[int, int]] = {
    # Оценка стоимости вызова ИИ в USD (NFR-7), доли цента; numeric(10,2) округлил бы её до нуля (ADR-7.4).
    ("messages", "cost_usd"): (12, 6),
    # Вес/объём порции в g/ml/pcs (FR-16), не деньги.
    ("menu_item_meta", "weight_amount"): (8, 2),
}

# Типы с плавающей точкой и PostgreSQL money запрещены для любых колонок (деньги — только Decimal).
FORBIDDEN_TYPES = frozenset({"real", "double precision", "money"})

TIMESTAMPTZ = "timestamp with time zone"


# ---------------------------------------------------------------- функции проверки


async def tenant_violations(
    connection: AsyncConnection, schema: str = SCHEMA, exempt: frozenset[str] = frozenset(TENANT_EXEMPT_TABLES)
) -> list[str]:
    """Таблицы схемы без ``tenant_id NOT NULL`` или без полного индекса, где ``tenant_id`` — первая колонка.

    Учитываются любые индексы из ``pg_index`` (обычные, UNIQUE, PK), кроме частичных (``indpred``) и
    недействительных: частичный индекс покрывает не все строки.
    """
    rows = await connection.execute(
        text(
            """
            SELECT c.relname AS table_name,
                   a.attnum IS NOT NULL AS has_column,
                   coalesce(a.attnotnull, false) AS not_null,
                   EXISTS (
                       SELECT 1 FROM pg_index i
                       WHERE i.indrelid = c.oid
                         AND i.indkey[0] = a.attnum
                         AND i.indpred IS NULL
                         AND i.indisvalid
                   ) AS indexed
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attribute a
              ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
            WHERE n.nspname = :schema AND c.relkind IN ('r', 'p')
            ORDER BY c.relname
            """
        ),
        {"schema": schema},
    )
    violations: list[str] = []
    for table, has_column, not_null, indexed in rows:
        if table in exempt:
            continue
        if not has_column:
            violations.append(f"{table}: нет колонки tenant_id")
            continue
        if not not_null:
            violations.append(f"{table}.tenant_id: допускает NULL")
        if not indexed:
            violations.append(f"{table}.tenant_id: нет полного индекса, где tenant_id — первая колонка")
    return violations


async def _columns(connection: AsyncConnection, schema: str) -> list[tuple[str, str, str, int | None, int | None]]:
    """(таблица, колонка, data_type, numeric_precision, numeric_scale) всех колонок таблиц схемы."""
    rows = await connection.execute(
        text(
            """
            SELECT c.table_name, c.column_name, c.data_type, c.numeric_precision, c.numeric_scale
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = :schema AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name, c.ordinal_position
            """
        ),
        {"schema": schema},
    )
    return [tuple(row) for row in rows]  # type: ignore[misc]


def _numeric_type(precision: int | None, scale: int | None) -> str:
    return "numeric" if precision is None else f"numeric({precision},{scale})"


async def money_column_violations(
    connection: AsyncConnection, schema: str = SCHEMA, money_columns: frozenset[tuple[str, str]] = MONEY_COLUMNS
) -> list[str]:
    """Колонки явного денежного списка, которых нет или тип которых не ``numeric(10,2)``."""
    found = {
        (table, column): (data_type, p, s) for table, column, data_type, p, s in await _columns(connection, schema)
    }
    violations: list[str] = []
    for table, column in sorted(money_columns):
        if (table, column) not in found:
            violations.append(f"{table}.{column}: денежной колонки нет в схеме")
            continue
        data_type, precision, scale = found[(table, column)]
        actual = _numeric_type(precision, scale) if data_type == "numeric" else data_type
        if (data_type, precision, scale) != ("numeric", *MONEY_TYPE):
            violations.append(f"{table}.{column}: {actual}, ожидается numeric(10,2)")
    return violations


async def numeric_violations(
    connection: AsyncConnection,
    schema: str = SCHEMA,
    exceptions: dict[tuple[str, str], tuple[int, int]] = NUMERIC_EXCEPTIONS,
) -> list[str]:
    """``numeric``-колонки не ``numeric(10,2)`` (кроме исключений с их точным типом) и колонки
    запрещённых типов (``real``, ``double precision``, ``money``)."""
    violations: list[str] = []
    for table, column, data_type, precision, scale in await _columns(connection, schema):
        if data_type in FORBIDDEN_TYPES:
            violations.append(f"{table}.{column}: тип {data_type} запрещён (деньги — numeric(10,2), Decimal)")
            continue
        if data_type != "numeric":
            continue
        expected = exceptions.get((table, column), MONEY_TYPE)
        if (precision, scale) != expected:
            violations.append(
                f"{table}.{column}: {_numeric_type(precision, scale)}, ожидается {_numeric_type(*expected)}"
            )
    return violations


async def timestamp_violations(connection: AsyncConnection, schema: str = SCHEMA) -> list[str]:
    """Колонки ``timestamp without time zone`` и колонки ``*_at`` любого типа, кроме ``timestamptz``."""
    violations: list[str] = []
    for table, column, data_type, _, _ in await _columns(connection, schema):
        if data_type == "timestamp without time zone":
            violations.append(f"{table}.{column}: timestamp without time zone, ожидается timestamptz")
        elif column.endswith("_at") and data_type != TIMESTAMPTZ:
            violations.append(f"{table}.{column}: {data_type}, ожидается timestamptz")
    return violations


# ---------------------------------------------------------------- фикстуры


@pytest.fixture
async def connection(migrated_database: str) -> AsyncIterator[AsyncConnection]:
    """Соединение во внешней транзакции, которая откатывается после теста (вместе с временным DDL)."""
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                yield conn
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


PROBE = "schema_invariants_probe"


@pytest.fixture
async def probe(connection: AsyncConnection) -> AsyncConnection:
    """Пустая временная схема для негативных тестов; удаляется откатом транзакции."""
    await connection.execute(text(f"CREATE SCHEMA {PROBE}"))
    return connection


async def _create(connection: AsyncConnection, *ddl: str) -> None:
    for statement in ddl:
        await connection.execute(text(statement.format(s=PROBE)))


def _report(violations: list[str]) -> str:
    return "нарушения инвариантов схемы:\n" + "\n".join(violations)


# ---------------------------------------------------------------- реальная схема: tenant_id


async def test_every_tenant_table_has_indexed_not_null_tenant_id(connection: AsyncConnection) -> None:
    violations = await tenant_violations(connection)
    assert violations == [], _report(violations)


async def test_tenant_check_covers_all_tables(connection: AsyncConnection) -> None:
    """Проверка не пустая: схема public содержит таблицы ревизий 0001..0004, исключения существуют
    и в них действительно нет tenant_id (иначе исключение лишнее)."""
    tables = set(await connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = :s"), {"s": SCHEMA}))
    known = {
        "tenants", "halls", "tables",
        "categories", "menu_items", "menu_item_prices", "menu_item_meta", "allergens", "menu_item_allergens",
        "visits", "messages", "cart_items",
        "orders", "order_items", "order_events",
    }  # fmt: skip
    assert known <= tables, f"нет таблиц: {sorted(known - tables)}"
    missing_exempt = set(TENANT_EXEMPT_TABLES) - tables
    assert not missing_exempt, f"исключения ссылаются на несуществующие таблицы: {sorted(missing_exempt)}"
    with_tenant = set(
        await connection.scalars(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = :s AND column_name = 'tenant_id'"
            ),
            {"s": SCHEMA},
        )
    )
    assert not (set(TENANT_EXEMPT_TABLES) & with_tenant), "в таблице-исключении есть tenant_id — уберите исключение"


# ---------------------------------------------------------------- реальная схема: деньги


async def test_money_columns_exist_and_are_numeric_10_2(connection: AsyncConnection) -> None:
    assert MONEY_COLUMNS, "список денежных колонок пуст — проверка ничего не проверяет"
    violations = await money_column_violations(connection)
    assert violations == [], _report(violations)


async def test_every_numeric_column_is_money_or_listed_exception(connection: AsyncConnection) -> None:
    violations = await numeric_violations(connection)
    assert violations == [], _report(violations)


async def test_numeric_exceptions_exist_with_exact_type(connection: AsyncConnection) -> None:
    """Исключения не устаревают молча: каждая колонка есть в схеме и имеет ровно указанный тип."""
    found = {(t, c): (p, s) for t, c, data_type, p, s in await _columns(connection, SCHEMA) if data_type == "numeric"}
    for key, expected in NUMERIC_EXCEPTIONS.items():
        assert key in found, f"{key[0]}.{key[1]}: исключения нет в схеме (или тип не numeric)"
        assert found[key] == expected, f"{key[0]}.{key[1]}: {_numeric_type(*found[key])}, в исключениях {expected}"
    assert not (set(NUMERIC_EXCEPTIONS) & MONEY_COLUMNS), "денежная колонка не может быть исключением"


# ---------------------------------------------------------------- реальная схема: время


async def test_time_columns_are_timestamptz(connection: AsyncConnection) -> None:
    violations = await timestamp_violations(connection)
    assert violations == [], _report(violations)


async def test_created_at_and_updated_at_are_timestamptz(connection: AsyncConnection) -> None:
    """Известные колонки времени: created_at есть в каждой таблице, кроме alembic_version; все они
    и все updated_at — timestamptz."""
    columns = await _columns(connection, SCHEMA)
    tables = {table for table, *_ in columns} - {"alembic_version"}
    created = {table: data_type for table, column, data_type, _, _ in columns if column == "created_at"}
    updated = {table: data_type for table, column, data_type, _, _ in columns if column == "updated_at"}
    assert tables - set(created) == set(), f"нет created_at: {sorted(tables - set(created))}"
    assert updated, "в схеме нет ни одной колонки updated_at"
    wrong = {f"{t}.created_at": d for t, d in created.items() if d != TIMESTAMPTZ}
    wrong |= {f"{t}.updated_at": d for t, d in updated.items() if d != TIMESTAMPTZ}
    assert wrong == {}, f"не timestamptz: {wrong}"


# ---------------------------------------------------------------- функции ловят нарушения


async def test_tenant_check_detects_violations(probe: AsyncConnection) -> None:
    await _create(
        probe,
        "CREATE TABLE {s}.no_column (id int PRIMARY KEY)",
        "CREATE TABLE {s}.nullable (id int PRIMARY KEY, tenant_id uuid)",
        "CREATE INDEX ON {s}.nullable (tenant_id)",
        "CREATE TABLE {s}.no_index (id int PRIMARY KEY, tenant_id uuid NOT NULL)",
        "CREATE TABLE {s}.not_leading (id int PRIMARY KEY, tenant_id uuid NOT NULL)",
        "CREATE INDEX ON {s}.not_leading (id, tenant_id)",
        "CREATE TABLE {s}.partial (id int PRIMARY KEY, tenant_id uuid NOT NULL, ok boolean)",
        "CREATE INDEX ON {s}.partial (tenant_id) WHERE ok",
        # Разрешённые варианты: tenant_id первый в обычном индексе, UNIQUE или PK.
        "CREATE TABLE {s}.good_index (id int PRIMARY KEY, tenant_id uuid NOT NULL)",
        "CREATE INDEX ON {s}.good_index (tenant_id, id)",
        "CREATE TABLE {s}.good_unique (id int PRIMARY KEY, tenant_id uuid NOT NULL, UNIQUE (tenant_id, id))",
        "CREATE TABLE {s}.good_pk (tenant_id uuid NOT NULL, id int, PRIMARY KEY (tenant_id, id))",
        "CREATE TABLE {s}.tenants (id uuid PRIMARY KEY)",
    )
    violations = await tenant_violations(probe, PROBE)
    assert violations == [
        "no_column: нет колонки tenant_id",
        "no_index.tenant_id: нет полного индекса, где tenant_id — первая колонка",
        "not_leading.tenant_id: нет полного индекса, где tenant_id — первая колонка",
        "nullable.tenant_id: допускает NULL",
        "partial.tenant_id: нет полного индекса, где tenant_id — первая колонка",
    ]


async def test_money_check_detects_wrong_type_and_missing_column(probe: AsyncConnection) -> None:
    await _create(
        probe,
        "CREATE TABLE {s}.orders (total numeric(12,2), pos_total numeric(10,2), fee double precision)",
    )
    columns = frozenset({("orders", "total"), ("orders", "pos_total"), ("orders", "fee"), ("orders", "gone")})
    violations = await money_column_violations(probe, PROBE, columns)
    assert violations == [
        "orders.fee: double precision, ожидается numeric(10,2)",
        "orders.gone: денежной колонки нет в схеме",
        "orders.total: numeric(12,2), ожидается numeric(10,2)",
    ]


async def test_numeric_check_detects_unlisted_numeric_and_floats(probe: AsyncConnection) -> None:
    await _create(
        probe,
        "CREATE TABLE {s}.t (ok numeric(10,2), wide numeric(12,2), free numeric, "
        "f real, d double precision, m money, cost_usd numeric(12,6))",
        "CREATE TABLE {s}.messages (cost_usd numeric(12,6))",
    )
    # messages.cost_usd — исключение и проходит; то же имя колонки в другой таблице исключением не является.
    violations = await numeric_violations(probe, PROBE)
    assert violations == [
        "t.wide: numeric(12,2), ожидается numeric(10,2)",
        "t.free: numeric, ожидается numeric(10,2)",
        "t.f: тип real запрещён (деньги — numeric(10,2), Decimal)",
        "t.d: тип double precision запрещён (деньги — numeric(10,2), Decimal)",
        "t.m: тип money запрещён (деньги — numeric(10,2), Decimal)",
        "t.cost_usd: numeric(12,6), ожидается numeric(10,2)",
    ]


async def test_timestamp_check_detects_naive_and_non_timestamp_time_columns(probe: AsyncConnection) -> None:
    await _create(
        probe,
        "CREATE TABLE {s}.t (created_at timestamptz, updated_at timestamp, happened timestamp(3), "
        "closed_at date, seen_at text, day date)",
    )
    violations = await timestamp_violations(probe, PROBE)
    assert violations == [
        "t.updated_at: timestamp without time zone, ожидается timestamptz",
        "t.happened: timestamp without time zone, ожидается timestamptz",
        "t.closed_at: date, ожидается timestamptz",
        "t.seen_at: text, ожидается timestamptz",
    ]


async def test_checks_pass_on_valid_probe_tables(probe: AsyncConnection) -> None:
    """Положительный контроль: корректная таблица не даёт ложных нарушений."""
    await _create(
        probe,
        "CREATE TABLE {s}.ok (tenant_id uuid NOT NULL, id int, price numeric(10,2), "
        "created_at timestamptz NOT NULL, PRIMARY KEY (tenant_id, id))",
    )
    assert await tenant_violations(probe, PROBE) == []
    assert await numeric_violations(probe, PROBE) == []
    assert await timestamp_violations(probe, PROBE) == []
    assert await money_column_violations(probe, PROBE, frozenset({("ok", "price")})) == []
