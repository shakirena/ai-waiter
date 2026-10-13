"""Платформа и заведение: tenants, halls, tables (#49).

Revision ID: 0001
Revises:
Create Date: 2026-10-10 23:16:23.899629

Перед созданием таблиц проверяется кодировка сервера: БД должна быть в UTF8 (ADR-7.13),
иначе кириллица и азербайджанская латиница искажаются, а дамп не переносится на Linux.
Межарендные ссылки исключены составными FK ``(tenant_id, x_id)`` (ADR-7.3).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REQUIRED_SERVER_ENCODING = "UTF8"


def check_server_encoding(connection: sa.Connection) -> None:
    """``RuntimeError`` с понятным текстом, если БД создана не в UTF8 (ADR-7.13)."""
    encoding = connection.execute(sa.text("SHOW server_encoding")).scalar_one()
    if str(encoding).upper() != REQUIRED_SERVER_ENCODING:
        raise RuntimeError(
            f"База данных создана в кодировке {encoding}, нужна {REQUIRED_SERVER_ENCODING}. "
            "Пересоздайте БД: CREATE DATABASE ... ENCODING 'UTF8' LOCALE 'C' TEMPLATE template0 "
            "(README, шаг «5. База данных»)."
        )


def upgrade() -> None:
    if not context.is_offline_mode():
        check_server_encoding(op.get_bind())

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), server_default="AZN", nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Asia/Baku", nullable=False),
        sa.Column(
            "languages", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{az,ru}'::text[]"), nullable=False
        ),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "cardinality(languages) >= 1 AND languages <@ ARRAY['az', 'ru']::text[]", name=op.f("ck_tenants_languages")
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_tenants_currency")),
        sa.CheckConstraint("jsonb_typeof(settings) = 'object'", name=op.f("ck_tenants_settings")),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 200", name=op.f("ck_tenants_name")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
    )
    op.create_table(
        "halls",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_key", sa.Text(collation="C"), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 100", name=op.f("ck_halls_name")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_halls_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_halls")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_halls_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_halls_tenant_id_name")),
    )
    op.create_table(
        "tables",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("hall_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), server_default="table", nullable=False),
        sa.Column("price_tier", sa.Text(), server_default="default", nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("qr_token", sa.Text(), nullable=False),
        sa.Column("token_issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price_tier ~ '^[a-z][a-z0-9_]{0,31}$'", name=op.f("ck_tables_price_tier")),
        sa.CheckConstraint("qr_token ~ '^[A-Za-z0-9_-]{22,64}$'", name=op.f("ck_tables_qr_token")),
        sa.CheckConstraint("type IN ('table', 'cabin')", name=op.f("ck_tables_type")),
        sa.CheckConstraint("char_length(external_id) BETWEEN 1 AND 64", name=op.f("ck_tables_external_id")),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 100", name=op.f("ck_tables_name")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "hall_id"],
            ["halls.tenant_id", "halls.id"],
            name=op.f("fk_tables_tenant_id_hall_id_halls"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_tables_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tables")),
        sa.UniqueConstraint("qr_token", name=op.f("uq_tables_qr_token")),
        sa.UniqueConstraint("tenant_id", "external_id", name=op.f("uq_tables_tenant_id_external_id")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_tables_tenant_id_id")),
    )
    op.create_index(op.f("ix_tables_tenant_id_hall_id"), "tables", ["tenant_id", "hall_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tables_tenant_id_hall_id"), table_name="tables")
    op.drop_table("tables")
    op.drop_table("halls")
    op.drop_table("tenants")
