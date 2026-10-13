"""AC-1 (#48): фикстура db, откат данных теста, Database на настоящем PostgreSQL."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import Database
from tests.conftest import make_settings
from tests.db.conftest import isolated_session

pytestmark = pytest.mark.db

PROBE_TABLE = "probe_rollback_48"


async def _table_exists(database_url: str, name: str) -> bool:
    """Проверка через отдельное соединение — вне транзакции теста."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            found = await connection.scalar(text("SELECT to_regclass(:name)"), {"name": f"public.{name}"})
    finally:
        await engine.dispose()
    return found is not None


async def test_select_one(db: AsyncSession) -> None:
    assert await db.scalar(text("SELECT 1")) == 1


async def test_database_is_utf8(db: AsyncSession) -> None:
    assert await db.scalar(text("SHOW server_encoding")) == "UTF8"


async def test_committed_data_is_rolled_back_after_test(migrated_database: str) -> None:
    """Таблица и строка, «зафиксированные» кодом теста, исчезают после выхода из фикстуры."""
    async with isolated_session(migrated_database) as session:
        await session.execute(text(f"CREATE TABLE {PROBE_TABLE} (id integer PRIMARY KEY, note text NOT NULL)"))
        await session.execute(text(f"INSERT INTO {PROBE_TABLE} VALUES (1, 'тест')"))  # noqa: S608 — константа
        await session.commit()  # фиксирует только SAVEPOINT
        assert await session.scalar(text(f"SELECT note FROM {PROBE_TABLE}")) == "тест"  # noqa: S608
        assert not await _table_exists(migrated_database, PROBE_TABLE), "до отката данные не видны снаружи"
    assert not await _table_exists(migrated_database, PROBE_TABLE)


async def test_rollback_inside_test_keeps_outer_transaction(db: AsyncSession) -> None:
    await db.execute(text("CREATE TEMPORARY TABLE probe_tmp (id integer)"))
    await db.commit()
    await db.execute(text("INSERT INTO probe_tmp VALUES (1)"))
    await db.rollback()  # откат до SAVEPOINT: таблица, созданная до commit(), остаётся
    assert await db.scalar(text("SELECT count(*) FROM probe_tmp")) == 0


async def test_database_ping_and_session_on_real_postgres(migrated_database: str) -> None:
    database = Database(make_settings(database_url=migrated_database))
    try:
        await database.start()
        assert await database.ping() is True
        async with database.session() as session:
            assert await session.scalar(text("SELECT current_setting('application_name')")) == "ai-waiter"
            assert await session.scalar(text("SELECT current_setting('TimeZone')")) == "UTC"
    finally:
        await database.stop()


async def test_database_ping_fails_without_leaking_password(
    migrated_database: str, caplog: pytest.LogCaptureFixture
) -> None:
    wrong_password = "wrong-pw-48-x9"  # заведомо неверный пароль
    url = make_url(migrated_database).set(password=wrong_password, database="missing_db_48_test")
    database = Database(make_settings(database_url=url.render_as_string(hide_password=False)))
    try:
        with caplog.at_level(logging.WARNING, logger="app.db.session"):
            assert await database.ping() is False
    finally:
        await database.stop()
    assert caplog.records, "ошибка подключения должна попасть в лог"
    assert all(wrong_password not in record.getMessage() for record in caplog.records)
