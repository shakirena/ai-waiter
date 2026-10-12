"""Межарендные ссылки отвергает сама БД (ADR-7.3, DEC-006): составные FK ``(tenant_id, x_id)``
на ``UNIQUE (tenant_id, id)`` родителя. Ошибка сервиса не может молча связать строку одного
заведения с родителем другого."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import MenuItemAllergen, MenuItemMeta, MenuItemPrice
from app.models.tenant import Table
from tests.db.factories import (
    add,
    build_cart_item,
    build_menu_item,
    build_message,
    build_order,
    build_order_event,
    build_order_item,
    build_table,
    build_visit,
    create_allergen,
    create_category,
    create_hall,
    create_menu_item,
    create_order,
    create_table,
    create_tenant,
    create_visit,
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


# ------------------------------------------------------------ меню (#50)


async def test_menu_item_cannot_reference_category_of_other_tenant(db_session: AsyncSession) -> None:
    """AC-3: ссылка на категорию другого заведения отклоняется составным FK."""
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_category = await create_category(db_session, other.id)
    await expect_insert_violation(
        db_session,
        "fk_menu_items_tenant_id_category_id_categories",
        build_menu_item(own.id, foreign_category.id),
    )


@pytest.mark.parametrize(
    ("model", "values", "constraint"),
    [
        (
            MenuItemPrice,
            {"price_tier": "default", "price": Decimal("1.00")},
            "fk_menu_item_prices_tenant_id_menu_item_id_menu_items",
        ),
        (MenuItemMeta, {}, "fk_menu_item_meta_tenant_id_menu_item_id_menu_items"),
    ],
    ids=["price", "meta"],
)
async def test_price_and_meta_cannot_reference_menu_item_of_other_tenant(
    db_session: AsyncSession, model: type, values: dict[str, object], constraint: str
) -> None:
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_item = await create_menu_item(db_session, other.id)
    await expect_insert_violation(
        db_session, constraint, model(tenant_id=own.id, menu_item_id=foreign_item.id, **values)
    )


async def test_menu_item_cannot_get_allergen_of_other_tenant(db_session: AsyncSession) -> None:
    """AC-3: аллерген другого заведения привязать нельзя."""
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    item = await create_menu_item(db_session, own.id)
    foreign_allergen = await create_allergen(db_session, other.id)
    await expect_insert_violation(
        db_session,
        "fk_menu_item_allergens_tenant_id_allergen_id_allergens",
        MenuItemAllergen(tenant_id=own.id, menu_item_id=item.id, allergen_id=foreign_allergen.id),
    )
    own_allergen = await create_allergen(db_session, own.id)
    link = await add(db_session, MenuItemAllergen(tenant_id=own.id, menu_item_id=item.id, allergen_id=own_allergen.id))
    assert link.created_at.tzinfo is not None


async def test_allergen_link_cannot_reference_menu_item_of_other_tenant(db_session: AsyncSession) -> None:
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_item = await create_menu_item(db_session, other.id)
    allergen = await create_allergen(db_session, own.id)
    await expect_insert_violation(
        db_session,
        "fk_menu_item_allergens_tenant_id_menu_item_id_menu_items",
        MenuItemAllergen(tenant_id=own.id, menu_item_id=foreign_item.id, allergen_id=allergen.id),
    )


# ------------------------------------------------------------ визит (#51)


async def test_visit_cannot_reference_table_of_other_tenant(db_session: AsyncSession) -> None:
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_table = await create_table(db_session, other.id)
    await expect_insert_violation(
        db_session, "fk_visits_tenant_id_table_id_tables", build_visit(own.id, foreign_table.id)
    )


async def test_cart_item_cannot_reference_menu_item_of_other_tenant(db_session: AsyncSession) -> None:
    """AC-4: строка корзины со ссылкой на позицию меню другого заведения отклоняется составным FK."""
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    visit = await create_visit(db_session, own.id)
    foreign_item = await create_menu_item(db_session, other.id)
    await expect_insert_violation(
        db_session,
        "fk_cart_items_tenant_id_menu_item_id_menu_items",
        build_cart_item(own.id, visit.id, foreign_item.id),
    )


async def test_cart_item_cannot_reference_visit_of_other_tenant(db_session: AsyncSession) -> None:
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_visit = await create_visit(db_session, other.id)
    item = await create_menu_item(db_session, own.id)
    await expect_insert_violation(
        db_session,
        "fk_cart_items_tenant_id_visit_id_visits",
        build_cart_item(own.id, foreign_visit.id, item.id),
    )


async def test_message_cannot_reference_visit_of_other_tenant(db_session: AsyncSession) -> None:
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_visit = await create_visit(db_session, other.id)
    await expect_insert_violation(
        db_session, "fk_messages_tenant_id_visit_id_visits", build_message(own.id, foreign_visit.id)
    )


# ------------------------------------------------------------ заказ (#52)


async def test_order_cannot_reference_visit_of_other_tenant(db_session: AsyncSession) -> None:
    """AC-5: заказ на визит другого заведения отклоняется составным FK."""
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_visit = await create_visit(db_session, other.id)
    await expect_insert_violation(
        db_session, "fk_orders_tenant_id_visit_id_visits", build_order(own.id, foreign_visit.id)
    )


async def test_order_item_cannot_reference_menu_item_of_other_tenant(db_session: AsyncSession) -> None:
    """AC-5: позиция заказа на блюдо другого заведения отклоняется составным FK."""
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    order = await create_order(db_session, own.id)
    foreign_item = await create_menu_item(db_session, other.id)
    await expect_insert_violation(
        db_session,
        "fk_order_items_tenant_id_menu_item_id_menu_items",
        build_order_item(own.id, order.id, foreign_item.id),
    )


async def test_order_item_cannot_reference_order_of_other_tenant(db_session: AsyncSession) -> None:
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_order = await create_order(db_session, other.id)
    item = await create_menu_item(db_session, own.id)
    await expect_insert_violation(
        db_session,
        "fk_order_items_tenant_id_order_id_orders",
        build_order_item(own.id, foreign_order.id, item.id),
    )


async def test_order_event_cannot_reference_order_of_other_tenant(db_session: AsyncSession) -> None:
    own = await create_tenant(db_session)
    other = await create_tenant(db_session)
    foreign_order = await create_order(db_session, other.id)
    await expect_insert_violation(
        db_session, "fk_order_events_tenant_id_order_id_orders", build_order_event(own.id, foreign_order.id)
    )
