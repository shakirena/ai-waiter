"""AC-1 (#48), ADR-7.10: Alembic на настоящем PostgreSQL — upgrade/downgrade/upgrade и alembic check.

Тест не зависит от числа ревизий: после ``downgrade base`` в схеме нет таблиц, кроме
``alembic_version``, после ``upgrade head`` текущая ревизия совпадает с head. На пустой цепочке
(до ревизии 0001 из #49) Alembic не создаёт даже ``alembic_version`` — обе команды проходят без шагов.
"""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.db.conftest import alembic_command, alembic_config, run_in_thread

pytestmark = pytest.mark.db


async def _public_tables(database_url: str) -> set[str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = await connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
            return set(rows)
    finally:
        await engine.dispose()


async def _current_revisions(database_url: str) -> set[str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            # Пока в цепочке нет ревизий, Alembic не создаёт alembic_version (нет шагов миграции).
            if await connection.scalar(text("SELECT to_regclass('public.alembic_version')")) is None:
                return set()
            rows = await connection.scalars(text("SELECT version_num FROM alembic_version"))
            return set(rows)
    finally:
        await engine.dispose()


def _heads(database_url: str) -> set[str]:
    return set(ScriptDirectory.from_config(alembic_config(database_url)).get_heads())


def test_upgrade_downgrade_upgrade(migrated_database: str) -> None:
    url = migrated_database
    assert run_in_thread(lambda: asyncio.run(_current_revisions(url))) == _heads(url)

    alembic_command(url, "downgrade", "base")
    assert run_in_thread(lambda: asyncio.run(_public_tables(url))) <= {"alembic_version"}
    assert run_in_thread(lambda: asyncio.run(_current_revisions(url))) == set()

    alembic_command(url, "upgrade", "head")
    assert run_in_thread(lambda: asyncio.run(_current_revisions(url))) == _heads(url)


def test_models_match_migrations(migrated_database: str) -> None:
    """``alembic check``: autogenerate не находит различий между моделями и схемой после head."""
    alembic_command(migrated_database, "check")


def test_env_accepts_ready_connection(migrated_database: str) -> None:
    """Источник подключения №1 в env.py: готовое синхронное соединение из ``config.attributes``."""

    def upgrade_with_connection(connection: Connection) -> None:
        cfg = alembic_config(migrated_database)
        del cfg.attributes["database_url"]
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
        command.current(cfg)

    async def run() -> None:
        engine = create_async_engine(migrated_database, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(upgrade_with_connection)
        finally:
            await engine.dispose()

    run_in_thread(lambda: asyncio.run(run()))
    assert run_in_thread(lambda: asyncio.run(_current_revisions(migrated_database))) == _heads(migrated_database)
