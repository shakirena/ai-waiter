"""Меню: ``Category``, ``MenuItem``, ``MenuItemPrice``, ``MenuItemMeta``, ``Allergen``,
``MenuItemAllergen``.

Колонки — docs/arch/feature-7-data-model.md, «Словарь данных → Меню». Ревизия Alembic ``0002_menu``.

Разделение владения данными: ``categories``/``menu_items``/``menu_item_prices`` пишет только
синхронизация (коннектор или файловый импорт), ``menu_item_meta``/``menu_item_allergens`` —
только админ (FR-16). Синхронизация никогда не удаляет строки, а ставит ``is_hidden``
(INT-2). ``allergens_verified = false`` означает «неизвестно» даже при пустом списке (AI-2).

ON DELETE (ADR-7.3): ``CASCADE`` только для строк, принадлежащих позиции (цены, мета,
аллергены позиции); остальное — ``RESTRICT``. Все ссылки внутри заведения — составные FK
``(tenant_id, x_id)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.checks import sql_between, sql_in, sql_length, sql_match, sql_not_match
from app.models.enums import (
    ABSOLUTE_PATH_PATTERN,
    ALLERGEN_CODE_PATTERN,
    CURRENCY_PATTERN,
    PRICE_TIER_PATTERN,
    WeightUnit,
)
from app.models.tenant import SORT_KEY_TYPE

EXTERNAL_ID_MAX = 64
NAME_MAX = 200
DESCRIPTION_MAX = 2000
ALLERGEN_NAME_MAX = 100
SPICE_LEVEL_MAX = 3
PREP_MINUTES_MAX = 240


class Category(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Категория из кассы; ``name_az``/``name_ru`` заполняет админ (FR-16), ``pos_name`` — нет."""

    __tablename__ = "categories"
    __extra_table_args__ = (
        UniqueConstraint("tenant_id", "external_id"),
        CheckConstraint(sql_length("external_id", EXTERNAL_ID_MAX, 1), name="external_id"),
        CheckConstraint(sql_length("name_az", NAME_MAX), name="name_az"),
        CheckConstraint(sql_length("name_ru", NAME_MAX), name="name_ru"),
    )

    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    pos_name: Mapped[str] = mapped_column(Text, nullable=False)
    name_az: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_key: Mapped[str] = mapped_column(SORT_KEY_TYPE, nullable=False, server_default="")
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MenuItem(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Позиция из кассы: название, валюта, наличие (стоп-лист, FR-17) админом не редактируются."""

    __tablename__ = "menu_items"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "external_id"),
        Index(None, "tenant_id", "category_id"),
        CheckConstraint(sql_length("external_id", EXTERNAL_ID_MAX, 1), name="external_id"),
        CheckConstraint(sql_match("currency", CURRENCY_PATTERN), name="currency"),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    pos_name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    station: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_key: Mapped[str] = mapped_column(SORT_KEY_TYPE, nullable=False, server_default="")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MenuItemPrice(TenantMixin, TimestampMixin, Base):
    """Цена позиции по тарифу (``default``, ``vip``, ...). Наличие ``default`` проверяет синхронизация."""

    __tablename__ = "menu_item_prices"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(sql_match("price_tier", PRICE_TIER_PATTERN), name="price_tier"),
        CheckConstraint("price >= 0", name="price"),
    )

    menu_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    price_tier: Mapped[str] = mapped_column(Text, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)


class MenuItemMeta(TenantMixin, TimestampMixin, Base):
    """Данные админа о позиции (1:1, FR-16). Нет строки — значения по умолчанию."""

    __tablename__ = "menu_item_meta"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(sql_length("name_az", NAME_MAX), name="name_az"),
        CheckConstraint(sql_length("name_ru", NAME_MAX), name="name_ru"),
        CheckConstraint(sql_length("description_az", DESCRIPTION_MAX), name="description_az"),
        CheckConstraint(sql_length("description_ru", DESCRIPTION_MAX), name="description_ru"),
        CheckConstraint(sql_length("ingredients_az", DESCRIPTION_MAX), name="ingredients_az"),
        CheckConstraint(sql_length("ingredients_ru", DESCRIPTION_MAX), name="ingredients_ru"),
        CheckConstraint(sql_between("spice_level", 0, SPICE_LEVEL_MAX), name="spice_level"),
        CheckConstraint(sql_between("prep_minutes", 1, PREP_MINUTES_MAX), name="prep_minutes"),
        CheckConstraint("weight_amount > 0", name="weight_amount"),
        CheckConstraint(sql_in("weight_unit", WeightUnit), name="weight_unit"),
        CheckConstraint("(weight_amount IS NULL) = (weight_unit IS NULL)", name="weight"),
        CheckConstraint(
            f"{sql_not_match('photo_path', ABSOLUTE_PATH_PATTERN)} AND strpos(photo_path, '..') = 0",
            name="photo_path",
        ),
    )

    menu_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name_az: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_az: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingredients_az: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingredients_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    allergens_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    spice_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    prep_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    weight_amount: Mapped[Decimal | None] = mapped_column(Numeric(8, 2, asdecimal=True), nullable=True)
    weight_unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    visible_to_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())


class Allergen(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Справочник аллергенов заведения (FR-16a); по умолчанию — 14 ЕС (``app.models.reference``)."""

    __tablename__ = "allergens"
    __extra_table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint(sql_match("code", ALLERGEN_CODE_PATTERN), name="code"),
        CheckConstraint(sql_length("name_az", ALLERGEN_NAME_MAX, 1), name="name_az"),
        CheckConstraint(sql_length("name_ru", ALLERGEN_NAME_MAX, 1), name="name_ru"),
    )

    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_az: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))


class MenuItemAllergen(TenantMixin, Base):
    """Аллерген позиции (данные админа). Аллерген чужого заведения привязать нельзя (составной FK)."""

    __tablename__ = "menu_item_allergens"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "allergen_id"],
            ["allergens.tenant_id", "allergens.id"],
            ondelete="RESTRICT",
        ),
        Index(None, "tenant_id", "allergen_id"),
    )

    menu_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    allergen_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=10
    )
