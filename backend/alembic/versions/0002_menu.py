"""Меню: categories, menu_items, menu_item_prices, menu_item_meta, allergens, menu_item_allergens (#50).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11 09:43:33.775162

Ссылки внутри заведения — составные FK ``(tenant_id, x_id)``; CASCADE только для строк,
принадлежащих позиции (цены, мета, аллергены позиции), остальное RESTRICT (ADR-7.3).
Справочник аллергенов миграция не заполняет: строки создаются при создании заведения
(``app.models.reference.default_allergen_rows``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "allergens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_az", sa.Text(), nullable=False),
        sa.Column("name_ru", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{0,31}$'", name=op.f("ck_allergens_code")),
        sa.CheckConstraint("char_length(name_az) BETWEEN 1 AND 100", name=op.f("ck_allergens_name_az")),
        sa.CheckConstraint("char_length(name_ru) BETWEEN 1 AND 100", name=op.f("ck_allergens_name_ru")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_allergens_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_allergens")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_allergens_tenant_id_code")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_allergens_tenant_id_id")),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("pos_name", sa.Text(), nullable=False),
        sa.Column("name_az", sa.Text(), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("sort_key", sa.Text(collation="C"), server_default="", nullable=False),
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(external_id) BETWEEN 1 AND 64", name=op.f("ck_categories_external_id")),
        sa.CheckConstraint("char_length(name_az) <= 200", name=op.f("ck_categories_name_az")),
        sa.CheckConstraint("char_length(name_ru) <= 200", name=op.f("ck_categories_name_ru")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_categories_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("tenant_id", "external_id", name=op.f("uq_categories_tenant_id_external_id")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_categories_tenant_id_id")),
    )
    op.create_table(
        "menu_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("pos_name", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("station", sa.Text(), nullable=True),
        sa.Column("sort_key", sa.Text(collation="C"), server_default="", nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_menu_items_currency")),
        sa.CheckConstraint("char_length(external_id) BETWEEN 1 AND 64", name=op.f("ck_menu_items_external_id")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            name=op.f("fk_menu_items_tenant_id_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_menu_items_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_items")),
        sa.UniqueConstraint("tenant_id", "external_id", name=op.f("uq_menu_items_tenant_id_external_id")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_menu_items_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_menu_items_tenant_id_category_id"), "menu_items", ["tenant_id", "category_id"], unique=False
    )
    op.create_table(
        "menu_item_allergens",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("allergen_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "allergen_id"],
            ["allergens.tenant_id", "allergens.id"],
            name=op.f("fk_menu_item_allergens_tenant_id_allergen_id_allergens"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            name=op.f("fk_menu_item_allergens_tenant_id_menu_item_id_menu_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_menu_item_allergens_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("menu_item_id", "allergen_id", name=op.f("pk_menu_item_allergens")),
    )
    op.create_index(
        op.f("ix_menu_item_allergens_tenant_id_allergen_id"),
        "menu_item_allergens",
        ["tenant_id", "allergen_id"],
        unique=False,
    )
    op.create_table(
        "menu_item_meta",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("name_az", sa.Text(), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("description_az", sa.Text(), nullable=True),
        sa.Column("description_ru", sa.Text(), nullable=True),
        sa.Column("ingredients_az", sa.Text(), nullable=True),
        sa.Column("ingredients_ru", sa.Text(), nullable=True),
        sa.Column("allergens_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("spice_level", sa.SmallInteger(), nullable=True),
        sa.Column("prep_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("weight_amount", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("weight_unit", sa.Text(), nullable=True),
        sa.Column("photo_path", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("visible_to_ai", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "photo_path !~ '^([/\\\\]|[A-Za-z]:)' AND strpos(photo_path, '..') = 0",
            name=op.f("ck_menu_item_meta_photo_path"),
        ),
        sa.CheckConstraint("weight_unit IN ('g', 'ml', 'pcs')", name=op.f("ck_menu_item_meta_weight_unit")),
        sa.CheckConstraint("(weight_amount IS NULL) = (weight_unit IS NULL)", name=op.f("ck_menu_item_meta_weight")),
        sa.CheckConstraint("char_length(description_az) <= 2000", name=op.f("ck_menu_item_meta_description_az")),
        sa.CheckConstraint("char_length(description_ru) <= 2000", name=op.f("ck_menu_item_meta_description_ru")),
        sa.CheckConstraint("char_length(ingredients_az) <= 2000", name=op.f("ck_menu_item_meta_ingredients_az")),
        sa.CheckConstraint("char_length(ingredients_ru) <= 2000", name=op.f("ck_menu_item_meta_ingredients_ru")),
        sa.CheckConstraint("char_length(name_az) <= 200", name=op.f("ck_menu_item_meta_name_az")),
        sa.CheckConstraint("char_length(name_ru) <= 200", name=op.f("ck_menu_item_meta_name_ru")),
        sa.CheckConstraint("prep_minutes BETWEEN 1 AND 240", name=op.f("ck_menu_item_meta_prep_minutes")),
        sa.CheckConstraint("spice_level BETWEEN 0 AND 3", name=op.f("ck_menu_item_meta_spice_level")),
        sa.CheckConstraint("weight_amount > 0", name=op.f("ck_menu_item_meta_weight_amount")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            name=op.f("fk_menu_item_meta_tenant_id_menu_item_id_menu_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_menu_item_meta_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("menu_item_id", name=op.f("pk_menu_item_meta")),
    )
    op.create_index(
        op.f("ix_menu_item_meta_tenant_id_menu_item_id"),
        "menu_item_meta",
        ["tenant_id", "menu_item_id"],
        unique=False,
    )
    op.create_table(
        "menu_item_prices",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("price_tier", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price_tier ~ '^[a-z][a-z0-9_]{0,31}$'", name=op.f("ck_menu_item_prices_price_tier")),
        sa.CheckConstraint("price >= 0", name=op.f("ck_menu_item_prices_price")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            name=op.f("fk_menu_item_prices_tenant_id_menu_item_id_menu_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_menu_item_prices_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("menu_item_id", "price_tier", name=op.f("pk_menu_item_prices")),
    )
    op.create_index(
        op.f("ix_menu_item_prices_tenant_id_menu_item_id"),
        "menu_item_prices",
        ["tenant_id", "menu_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_menu_item_prices_tenant_id_menu_item_id"), table_name="menu_item_prices")
    op.drop_table("menu_item_prices")
    op.drop_index(op.f("ix_menu_item_meta_tenant_id_menu_item_id"), table_name="menu_item_meta")
    op.drop_table("menu_item_meta")
    op.drop_index(op.f("ix_menu_item_allergens_tenant_id_allergen_id"), table_name="menu_item_allergens")
    op.drop_table("menu_item_allergens")
    op.drop_index(op.f("ix_menu_items_tenant_id_category_id"), table_name="menu_items")
    op.drop_table("menu_items")
    op.drop_table("categories")
    op.drop_table("allergens")
