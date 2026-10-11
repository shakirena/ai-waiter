"""Ревизии по отдельности на настоящем PostgreSQL (ADR-7.10): ``downgrade -1`` с ревизии удаляет
ровно её таблицы, предыдущие остаются; CHECK в БД совпадают с перечислениями (ADR-7.2);
кодировка сервера проверяется в ``0001`` (ADR-7.13).

Общий цикл upgrade/downgrade base/upgrade и ``alembic check`` — ``test_alembic.py``.
Каждый тест возвращает схему в ``head``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models.enums import Lang, MessageRole, TableType, VisitClosedBy, VisitStatus, WeightUnit
from tests.db.conftest import BACKEND_DIR, alembic_command, run_in_thread

pytestmark = pytest.mark.db

# Таблицы, которые создаёт ревизия (ADR-7.10).
REVISION_TABLES: dict[str, set[str]] = {
    "0001": {"tenants", "halls", "tables"},
    "0002": {"categories", "menu_items", "menu_item_prices", "menu_item_meta", "allergens", "menu_item_allergens"},
    "0003": {"visits", "messages", "cart_items"},
}


def _load_revision(revision: str) -> ModuleType:
    [path] = (BACKEND_DIR / "alembic" / "versions").glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"db_revision_{revision}", Path(path))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _query(database_url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return [tuple(row) for row in await connection.execute(text(sql))]
    finally:
        await engine.dispose()


def query(database_url: str, sql: str) -> list[tuple[object, ...]]:
    return run_in_thread(lambda: asyncio.run(_query(database_url, sql)))


def public_tables(database_url: str) -> set[str]:
    return {str(row[0]) for row in query(database_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


@pytest.fixture
def restore_head(migrated_database: str) -> Iterator[str]:
    yield migrated_database
    alembic_command(migrated_database, "upgrade", "head")


@pytest.mark.parametrize("revision", list(REVISION_TABLES))
def test_downgrade_one_step_drops_only_revision_tables(restore_head: str, revision: str) -> None:
    """AC-2/AC-3: ``downgrade -1`` с ревизии полностью удаляет её таблицы."""
    url = restore_head
    alembic_command(url, "downgrade", revision)
    before = public_tables(url)
    assert REVISION_TABLES[revision] <= before

    alembic_command(url, "downgrade", "-1")
    after = public_tables(url)
    assert before - after == REVISION_TABLES[revision]
    assert not REVISION_TABLES[revision] & after

    alembic_command(url, "upgrade", revision)
    assert REVISION_TABLES[revision] <= public_tables(url)


# CHECK вида «колонка IN (...)» и перечисление, из которого он построен.
ENUM_CHECKS: dict[str, type[StrEnum]] = {
    "ck_tables_type": TableType,
    "ck_menu_item_meta_weight_unit": WeightUnit,
    "ck_visits_status": VisitStatus,
    "ck_visits_lang": Lang,
    "ck_visits_closed_by": VisitClosedBy,
    "ck_messages_role": MessageRole,
}


@pytest.mark.parametrize(("constraint", "enum"), sorted(ENUM_CHECKS.items()), ids=list(sorted(ENUM_CHECKS)))
def test_check_constraint_values_match_enums(migrated_database: str, constraint: str, enum: type[StrEnum]) -> None:
    """ADR-7.2: alembic check не сравнивает CHECK — значения в БД сверяются с перечислениями."""
    [(definition,)] = query(
        migrated_database,
        f"SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = '{constraint}'",  # noqa: S608
    )
    assert sorted(re.findall(r"'([^']*)'::text", str(definition))) == sorted(enum)


def test_database_is_utf8_and_check_passes(migrated_database: str) -> None:
    [(encoding,)] = query(migrated_database, "SHOW server_encoding")
    assert encoding == "UTF8"
    module = _load_revision("0001")

    async def run() -> None:
        engine = create_async_engine(migrated_database, poolclass=NullPool)
        try:
            async with engine.connect() as connection:

                def check(sync_connection: Connection) -> None:
                    module.check_server_encoding(sync_connection)

                await connection.run_sync(check)
        finally:
            await engine.dispose()

    run_in_thread(lambda: asyncio.run(run()))
