"""#60 (ADR-60.1), #71 (ADR-60.2): ``app.seed.guard`` без PostgreSQL — запросы на ``AsyncMock``-сессии.

Поведение на настоящей базе (пустая / только демо / демо + другое) — ``tests/db/test_seed.py``.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.seed import guard
from app.seed.data import DEMO_TENANT_ID


def _session(result: object) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = result
    return session


def _compiled(session: AsyncMock) -> tuple[str, dict[str, Any]]:
    session.scalar.assert_awaited_once()
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).split()), compiled.params


@pytest.mark.parametrize("result", [True, False])
async def test_foreign_tenants_exist_query(result: bool) -> None:
    session = _session(result)
    assert await guard.foreign_tenants_exist(session) is result

    sql, params = _compiled(session)
    assert "EXISTS" in sql
    assert "FROM tenants" in sql
    assert re.search(r"tenants\.id (!=|<>) ", sql)
    assert list(params.values()) == [DEMO_TENANT_ID]
    session.execute.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize("result", [True, False])
async def test_demo_tenant_exists_query(result: bool) -> None:
    session = _session(result)
    assert await guard.demo_tenant_exists(session) is result

    sql, params = _compiled(session)
    assert "EXISTS" in sql
    assert "FROM tenants" in sql
    assert re.search(r"tenants\.id = ", sql)
    assert not re.search(r"tenants\.id (!=|<>) ", sql)
    assert list(params.values()) == [DEMO_TENANT_ID]
    session.commit.assert_not_called()


@pytest.mark.parametrize("check", [guard.foreign_tenants_exist, guard.demo_tenant_exists])
async def test_none_result_is_false(check: Callable[[AsyncSession], Awaitable[bool]]) -> None:
    assert await check(_session(None)) is False


async def test_ensure_seed_target_raises_when_foreign_tenants_exist() -> None:
    with pytest.raises(guard.ForeignTenantsError) as info:
        await guard.ensure_seed_target(_session(True))
    assert str(info.value) == guard.FOREIGN_TENANTS_REFUSAL
    assert isinstance(info.value, RuntimeError)


async def test_ensure_seed_target_passes_for_empty_or_demo_only_base() -> None:
    session = _session(False)
    assert await guard.ensure_seed_target(session) is None
    session.scalar.assert_awaited_once()


async def test_database_error_is_not_caught() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = OSError("connection refused")
    with pytest.raises(OSError, match="connection refused"):
        await guard.ensure_seed_target(session)
    with pytest.raises(OSError):
        await guard.demo_tenant_exists(session)


def test_refusal_text_is_russian_without_connection_details() -> None:
    text = guard.FOREIGN_TENANTS_REFUSAL
    assert re.search(r"[А-Яа-яЁё]", text)
    assert "ничего не записано" in text
    assert "--database-url" in text
    assert "DATABASE_URL" in text
    assert "postgresql" not in text.lower()
    assert "@" not in text
    assert not re.search(r"\d", text)
