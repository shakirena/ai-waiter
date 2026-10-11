"""AC-2 (#49): tenants, halls, tables на настоящем PostgreSQL — уникальности, CHECK, значения
по умолчанию, ON DELETE RESTRICT. Межарендные ссылки — ``test_tenant_isolation.py``, удаление
таблиц ``downgrade -1`` — ``test_migrations.py``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import DEFAULT_PRICE_TIER, TableType
from app.models.tenant import Hall, Table, Tenant
from tests.db.factories import (
    build_table,
    create_hall,
    create_table,
    create_tenant,
    expect_insert_violation,
    expect_violation,
)

pytestmark = pytest.mark.db


async def test_tenant_defaults(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    assert tenant.currency == "AZN"
    assert tenant.timezone == "Asia/Baku"
    assert tenant.languages == ["az", "ru"]
    assert tenant.settings == {}
    assert tenant.id.version == 7
    assert tenant.created_at.tzinfo is not None
    assert tenant.created_at <= datetime.now(UTC)


async def test_tenant_text_and_cyrillic_roundtrip(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session, name="Şəki çayxanası — «Чайхана»", settings={"escalate_after_minutes": 7})
    db_session.expunge(tenant)
    loaded = await db_session.scalar(select(Tenant).where(Tenant.id == tenant.id))
    assert loaded is not None
    assert loaded.name == "Şəki çayxanası — «Чайхана»"
    assert loaded.settings == {"escalate_after_minutes": 7}


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"name": ""}, "ck_tenants_name"),
        ({"name": "x" * 201}, "ck_tenants_name"),
        ({"currency": "azn"}, "ck_tenants_currency"),
        ({"currency": "AZNX"}, "ck_tenants_currency"),
        ({"languages": []}, "ck_tenants_languages"),
        ({"languages": ["az", "en"]}, "ck_tenants_languages"),
        ({"settings": []}, "ck_tenants_settings"),
        ({"settings": "строка"}, "ck_tenants_settings"),
    ],
)
async def test_tenant_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    values.setdefault("name", "Заведение")
    await expect_insert_violation(db_session, constraint, Tenant(**values))


async def test_tenant_languages_subset_accepted(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session, languages=["ru"])
    assert tenant.languages == ["ru"]


async def test_hall_name_unique_within_tenant(db_session: AsyncSession) -> None:
    first = await create_tenant(db_session)
    second = await create_tenant(db_session)
    await create_hall(db_session, first.id, name="Основной")
    await create_hall(db_session, second.id, name="Основной")
    await expect_insert_violation(db_session, "uq_halls_tenant_id_name", Hall(tenant_id=first.id, name="Основной"))
    await expect_insert_violation(db_session, "ck_halls_name", Hall(tenant_id=first.id, name=""))


async def test_table_defaults(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    assert table.price_tier == DEFAULT_PRICE_TIER
    assert table.is_active is True
    assert table.type == TableType.TABLE
    assert table.type in set(TableType)
    assert table.hall_id is None
    assert table.external_id is None
    assert table.token_issued_at.tzinfo is not None


async def test_cabin_type_accepted(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    cabin = await create_table(db_session, tenant.id, type=TableType.CABIN, price_tier="vip")
    assert (cabin.type, cabin.price_tier) == ("cabin", "vip")


async def test_qr_token_unique_across_all_tenants(db_session: AsyncSession) -> None:
    """AC-2: повтор qr_token отклоняется уникальным индексом на всю таблицу — и в другом заведении."""
    first = await create_tenant(db_session)
    second = await create_tenant(db_session)
    table = await create_table(db_session, first.id)
    await expect_insert_violation(
        db_session, "uq_tables_qr_token", build_table(first.id, name="Стол 2", qr_token=table.qr_token)
    )
    await expect_insert_violation(db_session, "uq_tables_qr_token", build_table(second.id, qr_token=table.qr_token))


async def test_external_id_unique_within_tenant_only(db_session: AsyncSession) -> None:
    """AC-2: повтор external_id внутри заведения отклоняется, в другом заведении принимается."""
    first = await create_tenant(db_session)
    second = await create_tenant(db_session)
    await create_table(db_session, first.id, external_id="12")
    await expect_insert_violation(
        db_session, "uq_tables_tenant_id_external_id", build_table(first.id, name="Стол 2", external_id="12")
    )
    other = await create_table(db_session, second.id, external_id="12")
    assert other.external_id == "12"


async def test_null_external_ids_do_not_conflict(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    await create_table(db_session, tenant.id)
    await create_table(db_session, tenant.id, name="Стол 2")
    count = await db_session.scalar(select(func.count()).select_from(Table).where(Table.tenant_id == tenant.id))
    assert count == 2


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"type": "cabinet"}, "ck_tables_type"),
        ({"type": "bar"}, "ck_tables_type"),
        ({"price_tier": "VIP"}, "ck_tables_price_tier"),
        ({"price_tier": "1vip"}, "ck_tables_price_tier"),
        ({"price_tier": ""}, "ck_tables_price_tier"),
        ({"external_id": ""}, "ck_tables_external_id"),
        ({"external_id": "x" * 65}, "ck_tables_external_id"),
        ({"qr_token": "short"}, "ck_tables_qr_token"),
        ({"qr_token": "a" * 21}, "ck_tables_qr_token"),
        ({"qr_token": "a" * 65}, "ck_tables_qr_token"),
        ({"qr_token": "a" * 21 + "+"}, "ck_tables_qr_token"),
        ({"name": ""}, "ck_tables_name"),
    ],
)
async def test_table_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    await expect_insert_violation(db_session, constraint, build_table(tenant.id, **values))


async def test_qr_token_reissue_updates_token(db_session: AsyncSession) -> None:
    """FR-1: перевыпуск — UPDATE qr_token; старый токен больше не находится."""
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    old = table.qr_token
    new = "N" * 43
    await db_session.execute(update(Table).where(Table.id == table.id).values(qr_token=new))
    assert await db_session.scalar(select(Table.id).where(Table.qr_token == old)) is None
    assert await db_session.scalar(select(Table.id).where(Table.qr_token == new)) == table.id


async def test_delete_restricted_while_referenced(db_session: AsyncSession) -> None:
    """ON DELETE RESTRICT: зал со столами и заведение с залами не удаляются."""
    tenant = await create_tenant(db_session)
    hall = await create_hall(db_session, tenant.id)
    await create_table(db_session, tenant.id, hall_id=hall.id)
    tenant_with_hall = await create_tenant(db_session)
    await create_hall(db_session, tenant_with_hall.id)

    async def delete_hall() -> None:
        await db_session.execute(delete(Hall).where(Hall.id == hall.id))

    async def delete_tenant() -> None:
        await db_session.execute(delete(Tenant).where(Tenant.id == tenant_with_hall.id))

    await expect_violation(db_session, "fk_tables_tenant_id_hall_id_halls", delete_hall)
    await expect_violation(db_session, "fk_halls_tenant_id_tenants", delete_tenant)
