"""Построители строк для db-тестов модели и проверка нарушенного ограничения по имени.

Каждый построитель добавляет объект в сессию и делает ``flush`` (значения по умолчанию сервера
возвращаются через RETURNING). Нарушение ограничения проверяется во вложенной транзакции
(``begin_nested``): откатывается только SAVEPOINT, данные теста остаются.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import Allergen, Category, MenuItem
from app.models.tenant import Hall, Table, Tenant
from app.models.visit import CartItem, Message, Visit


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


async def create_category(session: AsyncSession, tenant_id: uuid.UUID, **values: Any) -> Category:
    values.setdefault("external_id", f"c{secrets.token_hex(4)}")
    values.setdefault("pos_name", "Горячие блюда")
    return await add(session, Category(tenant_id=tenant_id, **values))


def build_menu_item(tenant_id: uuid.UUID, category_id: uuid.UUID, **values: Any) -> MenuItem:
    values.setdefault("external_id", f"m{secrets.token_hex(4)}")
    values.setdefault("pos_name", "Плов")
    values.setdefault("currency", "AZN")
    return MenuItem(tenant_id=tenant_id, category_id=category_id, **values)


async def create_menu_item(
    session: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID | None = None, **values: Any
) -> MenuItem:
    if category_id is None:
        category_id = (await create_category(session, tenant_id)).id
    return await add(session, build_menu_item(tenant_id, category_id, **values))


async def create_allergen(session: AsyncSession, tenant_id: uuid.UUID, **values: Any) -> Allergen:
    values.setdefault("code", "gluten")
    values.setdefault("name_az", "Qlüten")
    values.setdefault("name_ru", "Глютен")
    return await add(session, Allergen(tenant_id=tenant_id, **values))


def build_visit(tenant_id: uuid.UUID, table_id: uuid.UUID, **values: Any) -> Visit:
    values.setdefault("lang", "ru")
    return Visit(tenant_id=tenant_id, table_id=table_id, **values)


async def create_visit(
    session: AsyncSession, tenant_id: uuid.UUID, table_id: uuid.UUID | None = None, **values: Any
) -> Visit:
    if table_id is None:
        table_id = (await create_table(session, tenant_id)).id
    return await add(session, build_visit(tenant_id, table_id, **values))


def build_cart_item(tenant_id: uuid.UUID, visit_id: uuid.UUID, menu_item_id: uuid.UUID, **values: Any) -> CartItem:
    values.setdefault("qty", 1)
    values.setdefault("price_tier", "default")
    values.setdefault("price_at_add", Decimal("12.50"))
    return CartItem(tenant_id=tenant_id, visit_id=visit_id, menu_item_id=menu_item_id, **values)


def build_message(tenant_id: uuid.UUID, visit_id: uuid.UUID, **values: Any) -> Message:
    values.setdefault("role", "user")
    values.setdefault("text", "Что у вас есть из супов?")
    values.setdefault("content", [{"type": "text", "text": values["text"]}])
    return Message(tenant_id=tenant_id, visit_id=visit_id, **values)
