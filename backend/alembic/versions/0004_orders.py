"""Заказ: orders, order_items, order_events и триггер append-only журнала (#52).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 21:01:37.209379

``UNIQUE (tenant_id, idempotency_key)`` — идемпотентность POST /orders в границах заведения
(NFR-3, ADR-7.3). ``order_items`` принадлежат заказу (CASCADE), остальные ссылки — RESTRICT.
``order_events`` защищён триггером: UPDATE и DELETE отвергаются с SQLSTATE ``restrict_violation``
(ADR-7.6); TRUNCATE триггер не вызывает. Alembic autogenerate триггеры не видит, поэтому функция
и триггер создаются статическим SQL, а их наличие проверяют db-тесты.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Статический SQL (без подстановки значений), ADR-7.6.
CREATE_APPEND_ONLY_FUNCTION = """
CREATE FUNCTION order_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'order_events is append-only' USING ERRCODE = 'restrict_violation';
END $$
"""
CREATE_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_order_events_append_only BEFORE UPDATE OR DELETE ON order_events
  FOR EACH ROW EXECUTE FUNCTION order_events_append_only()
"""
DROP_APPEND_ONLY_TRIGGER = "DROP TRIGGER trg_order_events_append_only ON order_events"
DROP_APPEND_ONLY_FUNCTION = "DROP FUNCTION order_events_append_only()"


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="submitted", nullable=False),
        sa.Column("price_tier", sa.Text(), nullable=False),
        sa.Column("total", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("confirmed_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("pos_ref", sa.Text(), nullable=True),
        sa.Column("pos_total", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("pos_error", sa.Text(), nullable=True),
        sa.Column("sent_to_pos_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pos_acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_orders_currency")),
        sa.CheckConstraint("price_tier ~ '^[a-z][a-z0-9_]{0,31}$'", name=op.f("ck_orders_price_tier")),
        sa.CheckConstraint(
            "status IN ('submitted', 'edited', 'confirmed', 'rejected', 'escalated', "
            "'sent_to_pos', 'in_pos', 'pos_failed')",
            name=op.f("ck_orders_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('confirmed', 'sent_to_pos', 'in_pos', 'pos_failed') OR confirmed_at IS NOT NULL",
            name=op.f("ck_orders_confirmed_at"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('rejected') OR reject_reason IS NOT NULL", name=op.f("ck_orders_reject_reason")
        ),
        sa.CheckConstraint("char_length(pos_error) <= 1000", name=op.f("ck_orders_pos_error")),
        sa.CheckConstraint("char_length(pos_ref) <= 64", name=op.f("ck_orders_pos_ref")),
        sa.CheckConstraint("char_length(reject_reason) BETWEEN 1 AND 500", name=op.f("ck_orders_reject_reason_length")),
        sa.CheckConstraint("pos_total >= 0", name=op.f("ck_orders_pos_total")),
        sa.CheckConstraint("total >= 0", name=op.f("ck_orders_total")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "visit_id"],
            ["visits.tenant_id", "visits.id"],
            name=op.f("fk_orders_tenant_id_visit_id_visits"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_orders_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_orders_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name=op.f("uq_orders_tenant_id_idempotency_key")),
    )
    op.create_index(
        "ix_orders_pending_confirm",
        "orders",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('submitted', 'edited')"),
    )
    op.create_index(
        "ix_orders_pos_queue",
        "orders",
        ["tenant_id", "confirmed_at", "id"],
        unique=False,
        postgresql_where=sa.text("status IN ('confirmed', 'sent_to_pos')"),
    )
    op.create_index(
        op.f("ix_orders_tenant_id_status_created_at"), "orders", ["tenant_id", "status", "created_at"], unique=False
    )
    op.create_index(op.f("ix_orders_tenant_id_visit_id"), "orders", ["tenant_id", "visit_id"], unique=False)
    op.create_table(
        "order_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('guest', 'staff', 'connector', 'system')", name=op.f("ck_order_events_actor_type")
        ),
        sa.CheckConstraint(
            "from_status IN ('submitted', 'edited', 'confirmed', 'rejected', 'escalated', "
            "'sent_to_pos', 'in_pos', 'pos_failed')",
            name=op.f("ck_order_events_from_status"),
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f("ck_order_events_payload")),
        sa.CheckConstraint(
            "to_status IN ('submitted', 'edited', 'confirmed', 'rejected', 'escalated', "
            "'sent_to_pos', 'in_pos', 'pos_failed')",
            name=op.f("ck_order_events_to_status"),
        ),
        sa.CheckConstraint(
            "type IN ('created', 'status_changed', 'item_removed', 'item_qty_changed', 'pos_ack', 'pos_error', "
            "'pos_total_mismatch', 'manual_pos_entry')",
            name=op.f("ck_order_events_type"),
        ),
        sa.CheckConstraint(
            "type NOT IN ('status_changed') OR to_status IS NOT NULL", name=op.f("ck_order_events_status_change")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["orders.tenant_id", "orders.id"],
            name=op.f("fk_order_events_tenant_id_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_order_events_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_events")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_order_events_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_order_events_tenant_id_order_id_created_at"),
        "order_events",
        ["tenant_id", "order_id", "created_at"],
        unique=False,
    )
    op.execute(CREATE_APPEND_ONLY_FUNCTION)
    op.execute(CREATE_APPEND_ONLY_TRIGGER)
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("price_at_order", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        sa.Column("removed_by_staff", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(comment) <= 200", name=op.f("ck_order_items_comment")),
        sa.CheckConstraint("price_at_order >= 0", name=op.f("ck_order_items_price_at_order")),
        sa.CheckConstraint("qty BETWEEN 1 AND 99", name=op.f("ck_order_items_qty")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            name=op.f("fk_order_items_tenant_id_menu_item_id_menu_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["orders.tenant_id", "orders.id"],
            name=op.f("fk_order_items_tenant_id_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_order_items_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_order_items_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "order_id",
            "menu_item_id",
            "comment",
            name=op.f("uq_order_items_tenant_id_order_id_menu_item_id_comment"),
        ),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.execute(DROP_APPEND_ONLY_TRIGGER)
    op.execute(DROP_APPEND_ONLY_FUNCTION)
    op.drop_index(op.f("ix_order_events_tenant_id_order_id_created_at"), table_name="order_events")
    op.drop_table("order_events")
    op.drop_index(op.f("ix_orders_tenant_id_visit_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_tenant_id_status_created_at"), table_name="orders")
    op.drop_index(
        "ix_orders_pos_queue", table_name="orders", postgresql_where=sa.text("status IN ('confirmed', 'sent_to_pos')")
    )
    op.drop_index(
        "ix_orders_pending_confirm", table_name="orders", postgresql_where=sa.text("status IN ('submitted', 'edited')")
    )
    op.drop_table("orders")
