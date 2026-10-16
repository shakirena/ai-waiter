"""Журнал синхронизаций меню: menu_sync_runs (#63).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14 12:00:00.000000

Источник хеша последнего применённого снимка (INT-1) и времени синхронизации меню (FR-20, INT-4)
для любого источника — файла или коннектора (ADR-8.5, DEC-012). Строки только добавляются,
``updated_at`` нет. Отклонённый снимок может не иметь хеша (файл не разобран) — ``hash_state``.
Ссылка на коннектор (``connector_id``) появится в #16 вместе с таблицей ``connectors``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "menu_sync_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "counts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "issues", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source IN ('file', 'connector')", name=op.f("ck_menu_sync_runs_source")),
        sa.CheckConstraint("status IN ('applied', 'unchanged', 'rejected')", name=op.f("ck_menu_sync_runs_status")),
        sa.CheckConstraint("char_length(source_ref) BETWEEN 1 AND 255", name=op.f("ck_menu_sync_runs_source_ref")),
        sa.CheckConstraint("snapshot_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_menu_sync_runs_snapshot_hash")),
        sa.CheckConstraint(
            "status = 'rejected' OR snapshot_hash IS NOT NULL", name=op.f("ck_menu_sync_runs_hash_state")
        ),
        sa.CheckConstraint("finished_at >= started_at", name=op.f("ck_menu_sync_runs_finished_at")),
        sa.CheckConstraint("jsonb_typeof(counts) = 'object'", name=op.f("ck_menu_sync_runs_counts")),
        sa.CheckConstraint("jsonb_typeof(issues) = 'array'", name=op.f("ck_menu_sync_runs_issues")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_menu_sync_runs_tenant_id_tenants"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_sync_runs")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_menu_sync_runs_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_menu_sync_runs_tenant_id_finished_at"), "menu_sync_runs", ["tenant_id", "finished_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_menu_sync_runs_tenant_id_finished_at"), table_name="menu_sync_runs")
    op.drop_table("menu_sync_runs")
