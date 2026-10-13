"""Фикстуры тестов с PostgreSQL (ADR-7.11, DEC-008). Модули в ``tests/db/`` помечены ``pytest.mark.db``.

- Подключение — только ``TEST_DATABASE_URL`` (окружение процесса, затем корневой ``.env``), никогда
  ``DATABASE_URL``: тесты пересоздают схему ``public`` и не должны задеть рабочую БД.
- Имя БД обязано оканчиваться на ``_test``, иначе прогон прерывается (``pytest.exit``).
- Нет переменной: локально db-тесты пропускаются, при ``CI=true`` — ошибка (пустой прогон не «зелёный»).
- Схема создаётся миграциями (``alembic upgrade head``) один раз за сессию в синхронной фикстуре;
  async ``env.py`` сам вызывает ``asyncio.run``, поэтому команды Alembic выполняются в отдельном
  потоке — никогда из работающего цикла событий pytest-asyncio.
- Изоляция: каждый тест — внешняя транзакция и ``join_transaction_mode="create_savepoint"``;
  ``commit()`` тестируемого кода фиксирует только SAVEPOINT, после теста всё откатывается.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import make_url, text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
ENV_VAR = "TEST_DATABASE_URL"


def read_test_database_url() -> str | None:
    """``TEST_DATABASE_URL`` из окружения, иначе из корневого ``.env``. ``DATABASE_URL`` не читается."""
    value = os.environ.get(ENV_VAR)
    if not value:
        value = dotenv_values(REPO_ROOT / ".env").get(ENV_VAR)
    return value or None


def check_test_database_url(url: str) -> str | None:
    """Текст ошибки, если строка подключения не годится для тестов, иначе ``None``.
    Значение (с паролем) в текст не попадает."""
    try:
        parsed = make_url(url)
    except ArgumentError:
        return f"{ENV_VAR}: некорректная строка подключения"
    if parsed.drivername != "postgresql+asyncpg":
        return f"{ENV_VAR}: нужна схема postgresql+asyncpg://"
    if not (parsed.database or "").endswith("_test"):
        return (
            f"{ENV_VAR}: имя базы данных должно оканчиваться на _test — тесты пересоздают схему public "
            "и не должны работать с рабочей БД"
        )
    return None


def run_in_thread[T](func: Callable[[], T]) -> T:
    """Выполнить синхронную функцию в отдельном потоке (там нет цикла событий) и вернуть результат."""
    result: list[T] = []
    errors: list[BaseException] = []

    def target() -> None:
        try:
            result.append(func())
        except BaseException as exc:  # передаётся в вызывающий поток
            errors.append(exc)

    thread = threading.Thread(target=target, name="alembic")
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


def alembic_config(database_url: str) -> Config:
    """Конфигурация Alembic из ``backend/alembic.ini`` с явной строкой подключения, без настройки логов."""
    cfg = Config(BACKEND_DIR / "alembic.ini")
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    return cfg


async def _reset_schema(database_url: str) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def reset_schema(database_url: str) -> None:
    """Пустая схема ``public`` (владелец БД может её пересоздать: PG15+, ADR-7.13)."""
    run_in_thread(lambda: asyncio.run(_reset_schema(database_url)))


def alembic_command(database_url: str, name: str, *args: object) -> None:
    """``alembic.command.<name>(cfg, *args)`` в отдельном потоке."""
    cfg = alembic_config(database_url)
    run_in_thread(lambda: getattr(command, name)(cfg, *args))


def require_test_database_url() -> str:
    """Строка подключения к тестовой БД или skip (локально) / fail (``CI=true``) / exit (не ``*_test``)."""
    url = read_test_database_url()
    if url is None:
        hint = "README, шаг «5. База данных»"
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail(f"{ENV_VAR} не задан: в CI тесты с PostgreSQL (маркер db) обязательны ({hint})", pytrace=False)
        pytest.skip(f"{ENV_VAR} не задан: тесты с PostgreSQL (маркер db) пропущены ({hint})")
    problem = check_test_database_url(url)
    if problem is not None:
        pytest.exit(problem, returncode=2)
    return url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return require_test_database_url()


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    """Схема из миграций: ``DROP SCHEMA public CASCADE; CREATE SCHEMA public;`` и ``upgrade head``."""
    reset_schema(test_database_url)
    alembic_command(test_database_url, "upgrade", "head")
    return test_database_url


@asynccontextmanager
async def isolated_session(database_url: str) -> AsyncIterator[AsyncSession]:
    """Сессия во внешней транзакции, которая откатывается при выходе (основа ``db_session``)."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    async with isolated_session(migrated_database) as session:
        yield session


@pytest.fixture
def db(db_session: AsyncSession) -> AsyncSession:
    """Короткое имя фикстуры из issue #48 — та же сессия, что ``db_session``."""
    return db_session
