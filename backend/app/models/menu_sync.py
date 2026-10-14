"""Журнал синхронизаций меню: ``MenuSyncRun`` (``menu_sync_runs``), story #63, ADR-8.5, DEC-012.

Ревизия Alembic ``0005_menu_sync_runs``; модуль подключён в ``app/models/__init__.py``.

Назначение: хеш последнего применённого снимка (INT-1), время последней синхронизации и ошибки
для админки (FR-20) и алерта устаревшего меню (INT-4, #23). Источник — файл или коннектор;
ссылка на коннектор (``connector_id``) добавляется в #16 вместе с таблицей ``connectors``.

Таблица — журнал: строки только добавляются; очистка старых записей — задача #23 (срок хранения).
Межарендные FK невозможны: единственная ссылка — ``tenant_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, UUIDPrimaryKeyMixin
from app.models.checks import sql_in, sql_length, sql_match
from app.models.enums import MenuSyncSource, MenuSyncStatus

SNAPSHOT_HASH_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_REF_MAX = 255


class MenuSyncRun(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Одна синхронизация меню (применена, без изменений или отклонена). Пробный прогон не пишется."""

    __tablename__ = "menu_sync_runs"
    __extra_table_args__ = (
        CheckConstraint(sql_in("source", MenuSyncSource), name="source"),
        CheckConstraint(sql_in("status", MenuSyncStatus), name="status"),
        CheckConstraint(sql_length("source_ref", SOURCE_REF_MAX, 1), name="source_ref"),
        CheckConstraint(sql_match("snapshot_hash", SNAPSHOT_HASH_PATTERN), name="snapshot_hash"),
        # Применённый или неизменный снимок всегда имеет хеш; отклонённый — может не иметь (файл не разобран).
        CheckConstraint(
            f"status = '{MenuSyncStatus.REJECTED}' OR snapshot_hash IS NOT NULL",
            name="hash_state",
        ),
        CheckConstraint("finished_at >= started_at", name="finished_at"),
        CheckConstraint("jsonb_typeof(counts) = 'object'", name="counts"),
        CheckConstraint("jsonb_typeof(issues) = 'array'", name="issues"),
        # Последний применённый хеш и лента журнала заведения (tenant_id — ведущая колонка, DEC-010).
        Index(None, "tenant_id", "finished_at"),
    )

    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=10
    )
