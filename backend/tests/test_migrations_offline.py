"""Миграции без БД (ADR-7.10, ADR-7.11): офлайн-генерация SQL (``alembic upgrade head --sql``),
линейная цепочка ревизий и проверка кодировки сервера в ``0001``. Идут на Windows и Linux."""

from __future__ import annotations

import importlib.util
import io
import itertools
import re
from pathlib import Path
from types import ModuleType

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.conftest import FAKE_DATABASE_URL

BACKEND_DIR = Path(__file__).resolve().parents[1]
INI = BACKEND_DIR / "alembic.ini"
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"

# Ревизии по порядку и таблицы, которые создаёт каждая (ADR-7.10).
REVISION_TABLES: dict[str, set[str]] = {
    "0001": {"tenants", "halls", "tables"},
    "0002": {"categories", "menu_items", "menu_item_prices", "menu_item_meta", "allergens", "menu_item_allergens"},
    "0003": {"visits", "messages", "cart_items"},
    "0004": {"orders", "order_items", "order_events"},
}


def _config() -> tuple[Config, io.StringIO]:
    buffer = io.StringIO()
    cfg = Config(INI, output_buffer=buffer)
    cfg.attributes.update({"configure_logger": False, "database_url": FAKE_DATABASE_URL})
    return cfg, buffer


def _offline(func_name: str, *args: str) -> str:
    cfg, buffer = _config()
    getattr(command, func_name)(cfg, *args, sql=True)
    return buffer.getvalue()


def _created_tables(sql: str) -> set[str]:
    return set(re.findall(r"CREATE TABLE (\w+) \(", sql)) - {"alembic_version"}


def _dropped_tables(sql: str) -> set[str]:
    return set(re.findall(r"DROP TABLE (\w+);", sql)) - {"alembic_version"}


def _load_revision(revision: str) -> ModuleType:
    [path] = VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"revision_{revision}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chain_is_linear_and_ordered() -> None:
    script = ScriptDirectory.from_config(Config(INI))
    revisions = [rev.revision for rev in reversed(list(script.walk_revisions()))]
    assert revisions[: len(REVISION_TABLES)] == list(REVISION_TABLES)
    assert script.get_bases() == ["0001"]
    assert len(script.get_heads()) == 1
    for previous, current in itertools.pairwise(revisions):
        assert script.get_revision(current).down_revision == previous


def test_offline_upgrade_head_creates_all_tables() -> None:
    sql = _offline("upgrade", "head")
    expected = set().union(*REVISION_TABLES.values())
    assert expected <= _created_tables(sql)
    # Офлайн-режим не может проверить кодировку сервера — проверка пропускается, SQL генерируется.
    assert "server_encoding" not in sql


@pytest.mark.parametrize("revision", list(REVISION_TABLES))
def test_each_revision_creates_and_drops_its_tables(revision: str) -> None:
    module = _load_revision(revision)
    down = module.down_revision or "base"
    up_sql = _offline("upgrade", f"{down}:{revision}")
    assert _created_tables(up_sql) == REVISION_TABLES[revision]
    down_sql = _offline("downgrade", f"{revision}:{down}")
    assert _dropped_tables(down_sql) == REVISION_TABLES[revision]


def test_offline_sql_contains_composite_fk_and_global_qr_unique() -> None:
    sql = _offline("upgrade", "0001")
    assert "CONSTRAINT fk_tables_tenant_id_hall_id_halls FOREIGN KEY(tenant_id, hall_id) REFERENCES halls" in sql
    assert "CONSTRAINT uq_tables_qr_token UNIQUE (qr_token)" in sql
    assert "CONSTRAINT uq_halls_tenant_id_id UNIQUE (tenant_id, id)" in sql
    assert "ck_tables_type CHECK (type IN ('table', 'cabin'))" in sql


class _Result:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class _Connection:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        self.statements: list[str] = []

    def execute(self, statement: object) -> _Result:
        self.statements.append(str(statement))
        return _Result(self.encoding)


@pytest.mark.parametrize("encoding", ["UTF8", "utf8"])
def test_server_encoding_utf8_accepted(encoding: str) -> None:
    module = _load_revision("0001")
    connection = _Connection(encoding)
    module.check_server_encoding(connection)
    assert connection.statements == ["SHOW server_encoding"]


@pytest.mark.parametrize("encoding", ["WIN1251", "SQL_ASCII"])
def test_server_encoding_other_rejected_with_clear_message(encoding: str) -> None:
    module = _load_revision("0001")
    with pytest.raises(RuntimeError, match=rf"кодировке {encoding}, нужна UTF8"):
        module.check_server_encoding(_Connection(encoding))


def test_offline_sql_contains_partial_open_visit_index() -> None:
    """ADR-7.5: один открытый визит на стол — частичный уникальный индекс."""
    sql = _offline("upgrade", "0002:0003")
    assert "CREATE UNIQUE INDEX uq_visits_open_table ON visits (table_id) WHERE status IN ('open')" in sql
    assert "CREATE INDEX ix_messages_retention ON messages (created_at) WHERE redacted_at IS NULL" in sql
    assert "cost_usd NUMERIC(12, 6) DEFAULT 0 NOT NULL" in sql


def test_offline_sql_creates_and_drops_append_only_trigger() -> None:
    """ADR-7.6: триггер создаётся после order_events, downgrade удаляет его и функцию до таблицы."""
    up_sql = _offline("upgrade", "0003:0004")
    assert "CREATE FUNCTION order_events_append_only() RETURNS trigger LANGUAGE plpgsql" in up_sql
    assert "USING ERRCODE = 'restrict_violation'" in up_sql
    assert "CREATE TRIGGER trg_order_events_append_only BEFORE UPDATE OR DELETE ON order_events" in up_sql
    assert up_sql.index("CREATE TABLE order_events") < up_sql.index("CREATE TRIGGER trg_order_events_append_only")
    assert "CONSTRAINT uq_orders_tenant_id_idempotency_key UNIQUE (tenant_id, idempotency_key)" in up_sql

    down_sql = _offline("downgrade", "0004:0003")
    trigger = down_sql.index("DROP TRIGGER trg_order_events_append_only ON order_events")
    function = down_sql.index("DROP FUNCTION order_events_append_only()")
    assert trigger < function < down_sql.index("DROP TABLE order_events")
    # Обратный порядок: сначала дочерние таблицы, заказы — последними.
    assert down_sql.index("DROP TABLE order_items") < down_sql.index("DROP TABLE orders")
    assert down_sql.index("DROP TABLE order_events") < down_sql.index("DROP TABLE orders")


def test_offline_upgrade_head_has_all_fifteen_tables_and_trigger() -> None:
    """ADR-7.11: офлайн-SQL всей цепочки содержит 15 таблиц модели и триггер журнала."""
    sql = _offline("upgrade", "head")
    assert len(_created_tables(sql)) == 15
    assert "CREATE TRIGGER trg_order_events_append_only" in sql
