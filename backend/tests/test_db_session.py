"""Database (ADR-7.9) без PostgreSQL: ленивый движок, параметры пула, ping и маскирование пароля."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import SERVER_SETTINGS, Database
from tests.conftest import make_settings

SECRET_URL = "postgresql+asyncpg://ai_waiter:pw-s3cret@db.invalid:5432/ai_waiter"


class _FakeConnection:
    def __init__(self, executed: list[str]) -> None:
        self.executed = executed

    async def execute(self, statement: Any) -> None:
        self.executed.append(str(statement))


class _FakeEngine:
    """Подменяет AsyncEngine: ``connect()`` либо выполняет запрос, либо бросает ошибку."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.executed: list[str] = []
        self.disposed = 0

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[_FakeConnection]:
        if self.error is not None:
            raise self.error
        yield _FakeConnection(self.executed)

    async def dispose(self) -> None:
        self.disposed += 1


def _database(url: str = SECRET_URL, **overrides: Any) -> Database:
    return Database(make_settings(database_url=url, **overrides))


def test_engine_is_created_lazily_once_with_pool_settings() -> None:
    db = _database(db_pool_size=7, db_max_overflow=3)
    assert db._engine is None
    engine = db.engine
    assert isinstance(engine, AsyncEngine)
    assert db.engine is engine
    assert engine.pool.size() == 7
    assert engine.pool._max_overflow == 3  # type: ignore[attr-defined]
    assert engine.pool._pre_ping is True  # type: ignore[attr-defined]
    assert engine.url.drivername == "postgresql+asyncpg"
    assert "pw-s3cret" not in repr(engine)


def test_engine_passes_server_settings() -> None:
    assert SERVER_SETTINGS == {"application_name": "ai-waiter", "timezone": "UTC"}


def test_sessionmaker_does_not_expire_on_commit() -> None:
    db = _database()
    maker = db.sessionmaker
    assert db.sessionmaker is maker
    assert maker.kw["expire_on_commit"] is False
    assert maker.kw["bind"] is db.engine


async def test_start_does_not_create_engine() -> None:
    db = _database()
    await db.start()
    assert db._engine is None


async def test_stop_without_engine_is_noop() -> None:
    db = _database()
    await db.stop()
    assert db._engine is None


async def test_stop_disposes_engine_and_allows_restart() -> None:
    db = _database()
    fake = _FakeEngine()
    db._engine = fake  # type: ignore[assignment]
    _ = db.sessionmaker
    await db.stop()
    await db.stop()
    assert fake.disposed == 1
    assert db._engine is None
    assert db._sessionmaker is None


async def test_session_yields_async_session_and_closes_it() -> None:
    db = _database()
    async with db.session() as session:
        assert isinstance(session, AsyncSession)
        assert session.bind is db.engine
    await db.stop()


async def test_ping_ok() -> None:
    db = _database()
    fake = _FakeEngine()
    db._engine = fake  # type: ignore[assignment]
    assert await db.ping() is True
    assert fake.executed == ["SELECT 1"]


async def test_ping_failure_returns_false_and_masks_password(caplog: pytest.LogCaptureFixture) -> None:
    db = _database()
    try:
        raise OSError(f"cannot connect to {SECRET_URL}")
    except OSError as cause:
        error = ConnectionError("password pw-s3cret rejected")
        error.__cause__ = cause
    db._engine = _FakeEngine(error)  # type: ignore[assignment]
    with caplog.at_level(logging.WARNING, logger="app.db.session"):
        assert await db.ping() is False
    [record] = caplog.records
    message = record.getMessage()
    assert "pw-s3cret" not in message
    assert "ConnectionError: password *** rejected" in message
    assert "OSError" in message
    assert record.exc_info is None
    assert getattr(record, "component", None) == "database"


async def test_ping_does_not_swallow_cancellation() -> None:
    db = _database()
    db._engine = _FakeEngine(asyncio.CancelledError())  # type: ignore[assignment]
    with pytest.raises(asyncio.CancelledError):
        await db.ping()


def test_describe_error_masks_url_encoded_password() -> None:
    db = _database("postgresql+asyncpg://u:p%40ss%2Fword@db.invalid/x")
    text = db.describe_error(RuntimeError("raw p@ss/word, quoted p%40ss%2Fword"))
    assert "p@ss/word" not in text
    assert "p%40ss%2Fword" not in text
    assert text == "RuntimeError: raw ***, quoted ***"


def test_describe_error_without_password_and_empty_message() -> None:
    db = _database("postgresql+asyncpg://u@db.invalid/x")
    try:
        try:
            raise ValueError("inner")
        except ValueError:
            raise TimeoutError from None
    except TimeoutError as exc:
        assert db.describe_error(exc) == "TimeoutError"


def test_describe_error_follows_implicit_context_once() -> None:
    db = _database()
    try:
        try:
            raise KeyError("first")
        except KeyError:
            raise RuntimeError("second")  # noqa: B904 — проверяется неявный __context__
    except RuntimeError as exc:
        exc.__context__.__context__ = exc  # type: ignore[union-attr]  — цикл не зацикливает обход
        assert db.describe_error(exc) == "RuntimeError: second <- KeyError: 'first'"
