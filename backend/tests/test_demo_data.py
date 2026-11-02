"""#71 (ADR-60.2): ``DemoDataMonitor`` — состояние проверки демо-заведения и запись в лог только при смене."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

import app.api.demo_data as demo_data_module
from app.api.demo_data import (
    DEMO_CHECK_FAILED,
    DEMO_FOUND_WARNING,
    DEMO_GONE_INFO,
    DemoDataMonitor,
    DemoDataState,
)
from app.db.session import Database
from tests.conftest import make_settings
from tests.doubles import FakeDatabase, FakeSession

SECRET_URL = "postgresql+asyncpg://ai_waiter:pw-s3cret@db.invalid/ai_waiter"


class DemoQuery:
    """Подмена ``demo_tenant_exists``: очередь результатов (``bool`` или исключение), задержка."""

    def __init__(self, *results: bool | BaseException, delay: float = 0.0) -> None:
        self.results = list(results)
        self.delay = delay
        self.sessions: list[object] = []

    async def __call__(self, session: object) -> bool:
        self.sessions.append(session)
        if self.delay:
            await asyncio.sleep(self.delay)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def query(monkeypatch: pytest.MonkeyPatch) -> DemoQuery:
    q = DemoQuery()
    monkeypatch.setattr(demo_data_module, "demo_tenant_exists", q)
    return q


def _demo_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [rec for rec in caplog.records if rec.name == "app.api.demo_data"]


@pytest.fixture(autouse=True)
def _capture(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.api.demo_data")


def test_initial_state_is_none() -> None:
    assert DemoDataMonitor(2.0).state is None


async def test_found_logs_one_warning_and_repeat_is_silent(query: DemoQuery, caplog: pytest.LogCaptureFixture) -> None:
    query.results = [True, True]
    monitor = DemoDataMonitor(2.0)
    database = FakeDatabase()
    assert await monitor.refresh(database) is DemoDataState.FOUND  # type: ignore[arg-type]
    assert await monitor.refresh(database) is DemoDataState.FOUND  # type: ignore[arg-type]
    assert monitor.state is DemoDataState.FOUND
    records = _demo_records(caplog)
    assert [(rec.levelno, rec.getMessage()) for rec in records] == [(logging.WARNING, DEMO_FOUND_WARNING)]
    assert records[0].component == "demo_data"  # type: ignore[attr-defined]
    assert records[0].exc_info is None


async def test_found_then_absent_logs_info(query: DemoQuery, caplog: pytest.LogCaptureFixture) -> None:
    query.results = [True, False, False]
    monitor = DemoDataMonitor(2.0)
    database = FakeDatabase()
    for _ in range(3):
        await monitor.refresh(database)  # type: ignore[arg-type]
    assert monitor.state is DemoDataState.ABSENT
    records = _demo_records(caplog)
    assert [(rec.levelno, rec.getMessage()) for rec in records] == [
        (logging.WARNING, DEMO_FOUND_WARNING),
        (logging.INFO, DEMO_GONE_INFO),
    ]
    assert all(rec.component == "demo_data" for rec in records)  # type: ignore[attr-defined]


async def test_first_absent_is_silent(query: DemoQuery, caplog: pytest.LogCaptureFixture) -> None:
    query.results = [False, False]
    monitor = DemoDataMonitor(2.0)
    assert await monitor.refresh(FakeDatabase()) is DemoDataState.ABSENT  # type: ignore[arg-type]
    assert await monitor.refresh(FakeDatabase()) is DemoDataState.ABSENT  # type: ignore[arg-type]
    assert _demo_records(caplog) == []


async def test_unknown_then_absent_is_silent(query: DemoQuery, caplog: pytest.LogCaptureFixture) -> None:
    query.results = [ConnectionError("down"), ConnectionError("down"), False]
    monitor = DemoDataMonitor(2.0)
    database = FakeDatabase()
    for _ in range(3):
        await monitor.refresh(database)  # type: ignore[arg-type]
    assert monitor.state is DemoDataState.ABSENT
    records = _demo_records(caplog)
    assert [rec.levelno for rec in records] == [logging.WARNING], "одна запись о сбое, о восстановлении — нет"


async def test_found_after_unknown_logs_warning(query: DemoQuery, caplog: pytest.LogCaptureFixture) -> None:
    query.results = [ConnectionError("down"), True]
    monitor = DemoDataMonitor(2.0)
    database = FakeDatabase()
    await monitor.refresh(database)  # type: ignore[arg-type]
    await monitor.refresh(database)  # type: ignore[arg-type]
    assert [rec.getMessage() for rec in _demo_records(caplog)][-1] == DEMO_FOUND_WARNING


async def test_exception_is_unknown_with_masked_password(query: DemoQuery, caplog: pytest.LogCaptureFixture) -> None:
    """Настоящий ``Database`` с фиктивным URL: текст ошибки через ``describe_error``, пароль → ``***``."""
    database = Database(make_settings(database_url=SECRET_URL))

    @asynccontextmanager
    async def session() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    database.session = session  # type: ignore[method-assign]
    query.results = [ConnectionRefusedError(f"cannot connect: {SECRET_URL}")]
    monitor = DemoDataMonitor(2.0)
    assert await monitor.refresh(database) is DemoDataState.UNKNOWN
    [record] = _demo_records(caplog)
    message = record.getMessage()
    assert record.levelno == logging.WARNING
    assert message.startswith(DEMO_CHECK_FAILED.split("%s")[0])
    assert "ConnectionRefusedError" in message
    assert "***" in message
    assert "pw-s3cret" not in message
    assert record.exc_info is None
    assert record.component == "demo_data"  # type: ignore[attr-defined]


async def test_session_error_is_unknown(caplog: pytest.LogCaptureFixture) -> None:
    """Ошибка при открытии сессии (а не в запросе) — тоже ``UNKNOWN``, наружу не выходит."""

    class _BrokenDatabase(FakeDatabase):
        @asynccontextmanager
        async def session(self) -> AsyncIterator[FakeSession]:
            raise OSError("no connection")
            yield FakeSession()  # pragma: no cover

    monitor = DemoDataMonitor(2.0)
    assert await monitor.refresh(_BrokenDatabase()) is DemoDataState.UNKNOWN  # type: ignore[arg-type]
    [record] = _demo_records(caplog)
    assert "OSError: no connection" in record.getMessage()


async def test_timeout_is_unknown(query: DemoQuery, caplog: pytest.LogCaptureFixture) -> None:
    query.results = [True]
    query.delay = 5.0
    monitor = DemoDataMonitor(0.05)
    assert await monitor.refresh(FakeDatabase()) is DemoDataState.UNKNOWN  # type: ignore[arg-type]
    [record] = _demo_records(caplog)
    assert record.levelno == logging.WARNING
    assert "таймаут" in record.getMessage()
    assert "0.05" in record.getMessage()


async def test_driver_timeout_error_uses_describe_error(query: DemoQuery, caplog: pytest.LogCaptureFixture) -> None:
    """``TimeoutError`` от драйвера (наш таймаут не истёк) — текст ошибки, а не «превышен таймаут»."""
    query.results = [TimeoutError("connect timed out")]
    monitor = DemoDataMonitor(2.0)
    assert await monitor.refresh(FakeDatabase()) is DemoDataState.UNKNOWN  # type: ignore[arg-type]
    [record] = _demo_records(caplog)
    assert "TimeoutError: connect timed out" in record.getMessage()


async def test_cancelled_error_propagates(query: DemoQuery) -> None:
    query.results = [asyncio.CancelledError()]
    monitor = DemoDataMonitor(2.0)
    with pytest.raises(asyncio.CancelledError):
        await monitor.refresh(FakeDatabase())  # type: ignore[arg-type]
    assert monitor.state is None


async def test_session_is_closed_after_check(query: DemoQuery) -> None:
    query.results = [False]
    database = FakeDatabase()
    await DemoDataMonitor(2.0).refresh(database)  # type: ignore[arg-type]
    assert query.sessions == database.sessions
    assert all(session.closed for session in database.sessions)


def test_log_texts_have_no_connection_details() -> None:
    for text in (DEMO_FOUND_WARNING, DEMO_CHECK_FAILED, DEMO_GONE_INFO):
        assert "postgresql" not in text
        assert "@" not in text
    assert "APP_ENV=prod" in DEMO_FOUND_WARNING
    assert "DATABASE_URL" in DEMO_FOUND_WARNING
