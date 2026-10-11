"""AC-3 (#50): меню на настоящем PostgreSQL — уникальности в границах заведения, скрытие без
удаления, CHECK, значения по умолчанию, ON DELETE. Межарендные ссылки — ``test_tenant_isolation.py``."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import Allergen, Category, MenuItem, MenuItemAllergen, MenuItemMeta, MenuItemPrice
from app.models.reference import EU14_ALLERGEN_CODES, default_allergen_rows
from tests.db.factories import (
    add,
    build_menu_item,
    create_allergen,
    create_category,
    create_menu_item,
    create_tenant,
    expect_insert_violation,
    expect_violation,
)

pytestmark = pytest.mark.db


async def _count(session: AsyncSession, model: type, menu_item_id: uuid.UUID) -> int:
    column = model.menu_item_id  # type: ignore[attr-defined]
    return int(await session.scalar(select(func.count()).select_from(model).where(column == menu_item_id)) or 0)


async def _menu_item_with_data(session: AsyncSession, tenant_id: uuid.UUID) -> MenuItem:
    """Позиция '157' с ценами default/vip, мета (allergens_verified не задан) и аллергеном."""
    item = await create_menu_item(session, tenant_id, external_id="157", pos_name="Toyuq plov")
    session.add_all(
        [
            MenuItemPrice(tenant_id=tenant_id, menu_item_id=item.id, price_tier="default", price=Decimal("12.50")),
            MenuItemPrice(tenant_id=tenant_id, menu_item_id=item.id, price_tier="vip", price=Decimal("15.00")),
            MenuItemMeta(tenant_id=tenant_id, menu_item_id=item.id, name_ru="Плов с курицей"),
        ]
    )
    allergen = await create_allergen(session, tenant_id)
    await add(session, MenuItemAllergen(tenant_id=tenant_id, menu_item_id=item.id, allergen_id=allergen.id))
    return item


async def test_ac3_scenario(db_session: AsyncSession) -> None:
    """AC-3 целиком: дубли внутри заведения отклоняются, в другом — принимаются, скрытие ничего не удаляет."""
    tenant = await create_tenant(db_session)
    other = await create_tenant(db_session)
    item = await _menu_item_with_data(db_session, tenant.id)

    meta = await db_session.get(MenuItemMeta, item.id)
    assert meta is not None
    assert meta.allergens_verified is False
    assert meta.visible_to_ai is True
    assert meta.tags == []

    await expect_insert_violation(
        db_session,
        "uq_menu_items_tenant_id_external_id",
        build_menu_item(tenant.id, item.category_id, external_id="157"),
    )
    await expect_insert_violation(
        db_session,
        "pk_menu_item_prices",
        MenuItemPrice(tenant_id=tenant.id, menu_item_id=item.id, price_tier="vip", price=Decimal("1.00")),
    )
    foreign = await create_menu_item(db_session, other.id, external_id="157")
    assert foreign.external_id == "157"

    item_id = item.id
    await db_session.execute(update(MenuItem).where(MenuItem.id == item_id).values(is_hidden=True))
    db_session.expire_all()
    hidden = await db_session.get(MenuItem, item_id)
    assert hidden is not None
    assert hidden.is_hidden is True
    assert await _count(db_session, MenuItemPrice, item_id) == 2
    assert await _count(db_session, MenuItemMeta, item_id) == 1
    assert await _count(db_session, MenuItemAllergen, item_id) == 1


async def test_prices_are_decimal_with_two_places(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    item = await _menu_item_with_data(db_session, tenant.id)
    tenant_id, item_id = tenant.id, item.id
    db_session.expire_all()
    prices = (
        await db_session.scalars(
            select(MenuItemPrice.price).where(MenuItemPrice.menu_item_id == item_id).order_by(MenuItemPrice.price)
        )
    ).all()
    assert prices == [Decimal("12.50"), Decimal("15.00")]
    assert all(isinstance(price, Decimal) for price in prices)
    zero = await add(
        db_session, MenuItemPrice(tenant_id=tenant_id, menu_item_id=item_id, price_tier="staff", price=Decimal("0"))
    )
    assert zero.price == Decimal("0")


async def test_menu_item_defaults(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    item = await create_menu_item(db_session, tenant.id)
    assert item.is_available is True
    assert item.is_hidden is False
    assert item.sort_key == ""
    assert item.synced_at.tzinfo is not None
    category = await db_session.get(Category, item.category_id)
    assert category is not None
    assert category.is_hidden is False


async def test_category_external_id_unique_within_tenant(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    other = await create_tenant(db_session)
    await create_category(db_session, tenant.id, external_id="01")
    await expect_insert_violation(
        db_session,
        "uq_categories_tenant_id_external_id",
        Category(tenant_id=tenant.id, external_id="01", pos_name="Дубль"),
    )
    assert (await create_category(db_session, other.id, external_id="01")).external_id == "01"


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"price": Decimal("-0.01")}, "ck_menu_item_prices_price"),
        ({"price_tier": "VIP"}, "ck_menu_item_prices_price_tier"),
    ],
)
async def test_price_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    item = await create_menu_item(db_session, tenant.id)
    values = {"price_tier": "default", "price": Decimal("1.00"), **values}
    await expect_insert_violation(
        db_session, constraint, MenuItemPrice(tenant_id=tenant.id, menu_item_id=item.id, **values)
    )


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"spice_level": -1}, "ck_menu_item_meta_spice_level"),
        ({"spice_level": 4}, "ck_menu_item_meta_spice_level"),
        ({"prep_minutes": 0}, "ck_menu_item_meta_prep_minutes"),
        ({"prep_minutes": 241}, "ck_menu_item_meta_prep_minutes"),
        ({"weight_amount": Decimal("0"), "weight_unit": "g"}, "ck_menu_item_meta_weight_amount"),
        ({"weight_amount": Decimal("250")}, "ck_menu_item_meta_weight"),
        ({"weight_unit": "g"}, "ck_menu_item_meta_weight"),
        ({"weight_amount": Decimal("1"), "weight_unit": "kg"}, "ck_menu_item_meta_weight_unit"),
        ({"photo_path": "/etc/passwd"}, "ck_menu_item_meta_photo_path"),
        ({"photo_path": "\\\\server\\share\\a.jpg"}, "ck_menu_item_meta_photo_path"),
        ({"photo_path": "C:/photos/a.jpg"}, "ck_menu_item_meta_photo_path"),
        ({"photo_path": "d:\\photos\\a.jpg"}, "ck_menu_item_meta_photo_path"),
        ({"photo_path": "menu/../../secret"}, "ck_menu_item_meta_photo_path"),
        ({"name_ru": "x" * 201}, "ck_menu_item_meta_name_ru"),
        ({"description_az": "x" * 2001}, "ck_menu_item_meta_description_az"),
        ({"ingredients_ru": "x" * 2001}, "ck_menu_item_meta_ingredients_ru"),
    ],
)
async def test_meta_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    item = await create_menu_item(db_session, tenant.id)
    await expect_insert_violation(
        db_session, constraint, MenuItemMeta(tenant_id=tenant.id, menu_item_id=item.id, **values)
    )


@pytest.mark.parametrize("spice_level", [0, 3])
async def test_meta_valid_values_accepted(db_session: AsyncSession, spice_level: int) -> None:
    tenant = await create_tenant(db_session)
    item = await create_menu_item(db_session, tenant.id)
    meta = await add(
        db_session,
        MenuItemMeta(
            tenant_id=tenant.id,
            menu_item_id=item.id,
            spice_level=spice_level,
            prep_minutes=240,
            weight_amount=Decimal("350.5"),
            weight_unit="g",
            photo_path="menu/plov-1.jpg",
            tags=["hot", "halal"],
            name_az="Toyuq plovu",
        ),
    )
    assert (meta.spice_level, meta.weight_amount, meta.tags) == (spice_level, Decimal("350.5"), ["hot", "halal"])
    assert meta.allergens_verified is False


async def test_meta_is_one_to_one(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    item = await create_menu_item(db_session, tenant.id)
    await add(db_session, MenuItemMeta(tenant_id=tenant.id, menu_item_id=item.id))
    await expect_insert_violation(
        db_session, "pk_menu_item_meta", MenuItemMeta(tenant_id=tenant.id, menu_item_id=item.id)
    )


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"currency": "azn"}, "ck_menu_items_currency"),
        ({"external_id": ""}, "ck_menu_items_external_id"),
        ({"external_id": "x" * 65}, "ck_menu_items_external_id"),
    ],
)
async def test_menu_item_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    category = await create_category(db_session, tenant.id)
    await expect_insert_violation(db_session, constraint, build_menu_item(tenant.id, category.id, **values))


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"code": "Gluten"}, "ck_allergens_code"),
        ({"code": "tree-nuts"}, "ck_allergens_code"),
        ({"name_az": ""}, "ck_allergens_name_az"),
        ({"name_ru": "x" * 101}, "ck_allergens_name_ru"),
    ],
)
async def test_allergen_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    values = {"code": "gluten", "name_az": "Qlüten", "name_ru": "Глютен", **values}
    await expect_insert_violation(db_session, constraint, Allergen(tenant_id=tenant.id, **values))


async def test_allergen_code_unique_within_tenant(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    other = await create_tenant(db_session)
    await create_allergen(db_session, tenant.id, code="milk")
    await expect_insert_violation(
        db_session,
        "uq_allergens_tenant_id_code",
        Allergen(tenant_id=tenant.id, code="milk", name_az="Süd", name_ru="Молоко"),
    )
    assert (await create_allergen(db_session, other.id, code="milk")).code == "milk"


async def test_default_allergen_rows_insert_for_two_tenants(db_session: AsyncSession) -> None:
    """Справочник ЕС копируется каждому заведению: одинаковые коды в разных заведениях не конфликтуют."""
    first = await create_tenant(db_session)
    second = await create_tenant(db_session)
    await db_session.execute(insert(Allergen).values(default_allergen_rows(first.id)))
    db_session.add_all(Allergen(**row) for row in default_allergen_rows(second.id))
    await db_session.flush()
    for tenant_id in (first.id, second.id):
        codes = (
            await db_session.scalars(
                select(Allergen.code).where(Allergen.tenant_id == tenant_id).order_by(Allergen.sort_order)
            )
        ).all()
        assert tuple(codes) == EU14_ALLERGEN_CODES
    ids = (await db_session.scalars(select(Allergen.id).where(Allergen.tenant_id == first.id))).all()
    assert all(allergen_id.version == 7 for allergen_id in ids)


async def test_deleting_menu_item_cascades_owned_rows(db_session: AsyncSession) -> None:
    """ADR-7.3: цены, мета и аллергены позиции — CASCADE; сам аллерген справочника остаётся."""
    tenant = await create_tenant(db_session)
    item = await _menu_item_with_data(db_session, tenant.id)
    await db_session.execute(delete(MenuItem).where(MenuItem.id == item.id))
    for model in (MenuItemPrice, MenuItemMeta, MenuItemAllergen):
        assert await _count(db_session, model, item.id) == 0
    remaining = await db_session.scalar(
        select(func.count()).select_from(Allergen).where(Allergen.tenant_id == tenant.id)
    )
    assert remaining == 1


async def test_restrict_on_category_and_allergen(db_session: AsyncSession) -> None:
    """Категория с позициями и аллерген, привязанный к позиции, не удаляются (RESTRICT)."""
    tenant = await create_tenant(db_session)
    item = await _menu_item_with_data(db_session, tenant.id)
    [allergen_id] = (
        await db_session.scalars(select(MenuItemAllergen.allergen_id).where(MenuItemAllergen.menu_item_id == item.id))
    ).all()

    async def delete_category() -> None:
        await db_session.execute(delete(Category).where(Category.id == item.category_id))

    async def delete_allergen() -> None:
        await db_session.execute(delete(Allergen).where(Allergen.id == allergen_id))

    await expect_violation(db_session, "fk_menu_items_tenant_id_category_id_categories", delete_category)
    await expect_violation(db_session, "fk_menu_item_allergens_tenant_id_allergen_id_allergens", delete_allergen)


async def test_sort_key_uses_byte_order(db_session: AsyncSession) -> None:
    """``COLLATE "C"``: сортировка побайтная, одинаковая на Windows и Linux (ADR-7.13)."""
    tenant = await create_tenant(db_session)
    for key in ("b", "B", "a", "_"):
        await create_category(db_session, tenant.id, sort_key=key)
    keys = (
        await db_session.scalars(
            select(Category.sort_key).where(Category.tenant_id == tenant.id).order_by(Category.sort_key)
        )
    ).all()
    assert keys == ["B", "_", "a", "b"]
