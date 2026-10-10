"""Окружение Alembic: async-движок asyncpg (ADR-7.10).

Источник подключения (первый найденный):

1. ``config.attributes["connection"]`` — готовое синхронное ``Connection`` (тесты);
2. ``config.attributes["database_url"]`` — строка подключения (тесты, утилиты);
3. ``get_settings().database_url`` — ``DATABASE_URL`` из окружения или ``.env``, как у приложения.

Онлайн-режим — ``NullPool`` и ``connection.run_sync``; офлайн-режим (``--sql``) генерирует SQL
без подключения к БД. ``config.attributes["configure_logger"] = False`` отключает настройку
логов из ``alembic.ini`` (тесты не должны перенастраивать логирование процесса).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401 — регистрирует все таблицы в Base.metadata
from app.db.base import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    # disable_existing_loggers=False: не глушить логгеры приложения, созданные до миграций.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    url = config.attributes.get("database_url")
    if url:
        return str(url)
    from app.core.config import get_settings

    return get_settings().database_url.get_secret_value()


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
        **kwargs,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    """``alembic upgrade head --sql``: SQL в stdout, без подключения к БД."""
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
