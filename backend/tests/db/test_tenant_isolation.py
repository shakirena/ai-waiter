"""Межарендные ссылки отвергает сама БД (ADR-7.3, DEC-006): составные FK ``(tenant_id, x_id)``
на ``UNIQUE (tenant_id, id)`` родителя. Ошибка сервиса не может молча связать строку одного
заведения с родителем другого."""

from __future__ import annotations

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Table
from tests.db.factories import (
    build_table,
    create_hall,
    create_table,
    create_tenant,
    expect_insert_violation,
    expect_violation,
)

pytestmark = pytest.mark.db


async def test_table_cannot_reference_hall_of_other_tenant(db_session: AsyncSession) -> None:
    """AC-2: стол со ссылкой на зал другого заведения отклоняется составным FK."""
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_hall = await create_hall(db_session, other.id)
    await expect_insert_violation(
        db_session, "fk_tables_tenant_id_hall_id_halls", build_table(own.id, hall_id=foreign_hall.id)
    )


async def test_table_hall_of_same_tenant_and_null_hall_accepted(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    hall = await create_hall(db_session, tenant.id)
    in_hall = await create_table(db_session, tenant.id, hall_id=hall.id)
    without_hall = await create_table(db_session, tenant.id, name="Стол 2")
    assert in_hall.hall_id == hall.id
    assert without_hall.hall_id is None


async def test_moving_table_to_hall_of_other_tenant_rejected(db_session: AsyncSession) -> None:
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    table = await create_table(db_session, own.id)
    foreign_hall = await create_hall(db_session, other.id)

    async def move() -> None:
        await db_session.execute(update(Table).where(Table.id == table.id).values(hall_id=foreign_hall.id))

    await expect_violation(db_session, "fk_tables_tenant_id_hall_id_halls", move)


async def test_changing_tenant_of_table_in_hall_rejected(db_session: AsyncSession) -> None:
    """Смена ``tenant_id`` у стола в зале тоже ломает составной FK."""
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    hall = await create_hall(db_session, own.id)
    table = await create_table(db_session, own.id, hall_id=hall.id)

    async def move() -> None:
        await db_session.execute(update(Table).where(Table.id == table.id).values(tenant_id=other.id))

    await expect_violation(db_session, "fk_tables_tenant_id_hall_id_halls", move)
