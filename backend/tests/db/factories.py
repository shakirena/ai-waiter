"""Построители строк для db-тестов модели и проверка нарушенного ограничения по имени.

Каждый построитель добавляет объект в сессию и делает ``flush`` (значения по умолчанию сервера
возвращаются через RETURNING). Нарушение ограничения проверяется во вложенной транзакции
(``begin_nested``): откатывается только SAVEPOINT, данные теста остаются.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Hall, Table, Tenant


def qr_token() -> str:
    """Токен как в #9/#27: 128 бит в base64url (22 символа)."""
    return secrets.token_urlsafe(16)


def violated_constraint(error: IntegrityError) -> str | None:
    """Имя нарушенного ограничения из исключения asyncpg (``constraint_name``)."""
    cause = error.orig.__cause__ if error.orig is not None else None
    return getattr(cause, "constraint_name", None)


async def expect_violation(session: AsyncSession, constraint: str, action: Callable[[], Awaitable[Any]]) -> None:
    """``action`` отклоняется БД именно ограничением ``constraint``; сессия остаётся рабочей."""
    with pytest.raises(IntegrityError) as info:
        async with session.begin_nested():
            await action()
            await session.flush()
    assert violated_constraint(info.value) == constraint


async def expect_insert_violation(session: AsyncSession, constraint: str, *objects: object) -> None:
    async def insert() -> None:
        session.add_all(objects)

    await expect_violation(session, constraint, insert)


async def add[T](session: AsyncSession, obj: T) -> T:
    session.add(obj)
    await session.flush()
    return obj


async def create_tenant(session: AsyncSession, **values: Any) -> Tenant:
    values.setdefault("name", "Тестовое заведение")
    return await add(session, Tenant(**values))


async def create_hall(session: AsyncSession, tenant_id: uuid.UUID, **values: Any) -> Hall:
    values.setdefault("name", f"Зал {secrets.token_hex(3)}")
    return await add(session, Hall(tenant_id=tenant_id, **values))


def build_table(tenant_id: uuid.UUID, **values: Any) -> Table:
    values.setdefault("name", "Стол 1")
    values.setdefault("qr_token", qr_token())
    return Table(tenant_id=tenant_id, **values)


async def create_table(session: AsyncSession, tenant_id: uuid.UUID, **values: Any) -> Table:
    return await add(session, build_table(tenant_id, **values))
