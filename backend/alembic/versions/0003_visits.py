"""Визит: visits, messages, cart_items (#51).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11 20:46:45.058255

Не больше одного открытого визита на стол — частичный уникальный индекс ``uq_visits_open_table``
(ADR-7.5); корзина визита — строки ``cart_items``, отдельной таблицы нет. ``messages`` и
``cart_items`` принадлежат визиту (CASCADE), ссылки на стол и позицию меню — RESTRICT (ADR-7.3).
``messages.cost_usd`` — NUMERIC(12,6), исключение из правила денег NUMERIC(10,2) (ADR-7.4).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visits",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("lang", sa.Text(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Text(), nullable=True),
        sa.Column("closed_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(status IN ('open') AND closed_at IS NULL AND closed_by IS NULL) OR "
            "(status IN ('closed') AND closed_at IS NOT NULL AND closed_by IS NOT NULL)",
            name=op.f("ck_visits_closed_state"),
        ),
        sa.CheckConstraint("closed_by IN ('staff', 'pos', 'timeout')", name=op.f("ck_visits_closed_by")),
        sa.CheckConstraint("lang IN ('az', 'ru')", name=op.f("ck_visits_lang")),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_visits_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "table_id"],
            ["tables.tenant_id", "tables.id"],
            name=op.f("fk_visits_tenant_id_table_id_tables"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_visits_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_visits")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_visits_tenant_id_id")),
    )
    op.create_index(
        "ix_visits_open_last_activity",
        "visits",
        ["last_activity_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('open')"),
    )
    op.create_index(
        op.f("ix_visits_tenant_id_table_id_opened_at"), "visits", ["tenant_id", "table_id", "opened_at"], unique=False
    )
    op.create_index(
        "uq_visits_open_table", "visits", ["table_id"], unique=True, postgresql_where=sa.text("status IN ('open')")
    )
    op.create_table(
        "cart_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        sa.Column("price_tier", sa.Text(), nullable=False),
        sa.Column("price_at_add", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price_tier ~ '^[a-z][a-z0-9_]{0,31}$'", name=op.f("ck_cart_items_price_tier")),
        sa.CheckConstraint("char_length(comment) <= 200", name=op.f("ck_cart_items_comment")),
        sa.CheckConstraint("price_at_add >= 0", name=op.f("ck_cart_items_price_at_add")),
        sa.CheckConstraint("qty BETWEEN 1 AND 99", name=op.f("ck_cart_items_qty")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            name=op.f("fk_cart_items_tenant_id_menu_item_id_menu_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "visit_id"],
            ["visits.tenant_id", "visits.id"],
            name=op.f("fk_cart_items_tenant_id_visit_id_visits"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_cart_items_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cart_items")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_cart_items_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "visit_id",
            "menu_item_id",
            "comment",
            name=op.f("uq_cart_items_tenant_id_visit_id_menu_item_id_comment"),
        ),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_creation_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("jsonb_typeof(content) = 'array'", name=op.f("ck_messages_content")),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_messages_role")),
        sa.CheckConstraint("cache_creation_tokens >= 0", name=op.f("ck_messages_cache_creation_tokens")),
        sa.CheckConstraint("cache_read_tokens >= 0", name=op.f("ck_messages_cache_read_tokens")),
        sa.CheckConstraint("char_length(text) <= 8000", name=op.f("ck_messages_text")),
        sa.CheckConstraint(
            "content IS NOT NULL OR redacted_at IS NOT NULL", name=op.f("ck_messages_content_or_redacted")
        ),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_messages_cost_usd")),
        sa.CheckConstraint("input_tokens >= 0", name=op.f("ck_messages_input_tokens")),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_messages_latency_ms")),
        sa.CheckConstraint("output_tokens >= 0", name=op.f("ck_messages_output_tokens")),
        sa.CheckConstraint(
            "redacted_at IS NULL OR (content IS NULL AND text IS NULL)", name=op.f("ck_messages_redacted_empty")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "visit_id"],
            ["visits.tenant_id", "visits.id"],
            name=op.f("fk_messages_tenant_id_visit_id_visits"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_messages_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_messages_tenant_id_id")),
    )
    op.create_index(
        "ix_messages_retention",
        "messages",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("redacted_at IS NULL"),
    )
    op.create_index(op.f("ix_messages_tenant_id_created_at"), "messages", ["tenant_id", "created_at"], unique=False)
    op.create_index(
        op.f("ix_messages_tenant_id_visit_id_created_at"),
        "messages",
        ["tenant_id", "visit_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_tenant_id_visit_id_created_at"), table_name="messages")
    op.drop_index(op.f("ix_messages_tenant_id_created_at"), table_name="messages")
    op.drop_index("ix_messages_retention", table_name="messages", postgresql_where=sa.text("redacted_at IS NULL"))
    op.drop_table("messages")
    op.drop_table("cart_items")
    op.drop_index("uq_visits_open_table", table_name="visits", postgresql_where=sa.text("status IN ('open')"))
    op.drop_index(op.f("ix_visits_tenant_id_table_id_opened_at"), table_name="visits")
    op.drop_index("ix_visits_open_last_activity", table_name="visits", postgresql_where=sa.text("status IN ('open')"))
    op.drop_table("visits")
