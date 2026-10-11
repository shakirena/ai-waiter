"""Визит: ``Visit`` (visits), ``Message`` (messages), ``CartItem`` (cart_items).

Колонки — docs/arch/feature-7-data-model.md, «Словарь данных → Визит». Ревизия Alembic ``0003_visits``.

- Не больше одного открытого визита на стол: частичный уникальный индекс
  ``uq_visits_open_table`` по ``table_id`` WHERE ``status = 'open'`` (ADR-7.5); закрытых
  визитов у стола может быть сколько угодно.
- Одна текущая корзина на визит (ADR-7.5): корзина — это строки ``cart_items`` визита,
  отдельной таблицы ``carts`` нет; при отправке заказа строки удаляются в той же транзакции.
  ``UNIQUE (tenant_id, visit_id, menu_item_id, comment)``: то же блюдо с тем же комментарием
  увеличивает ``qty``, с другим комментарием — отдельная строка.
- ``messages`` — содержимое в формате блоков Claude API (``content`` jsonb), токены и
  стоимость ИИ (``cost_usd NUMERIC(12,6)`` — исключение из правила NUMERIC(10,2), ADR-7.4).
  Обезличивание по ``dialog_retention_days`` (NFR-5): ``text`` и ``content`` → NULL,
  ``redacted_at`` заполняется; токены и стоимость остаются для метрик. Только ``created_at``:
  сообщение не редактируется (кроме обезличивания).
- ``closed_by_staff_id`` — UUID без FK до появления ``staff_users`` (#19), ADR-7.7.

ON DELETE (ADR-7.3): ``messages`` и ``cart_items`` принадлежат визиту — CASCADE; визит → стол и
строка корзины → позиция меню — RESTRICT.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.checks import sql_between, sql_in, sql_length, sql_match
from app.models.enums import PRICE_TIER_PATTERN, Lang, MessageRole, VisitClosedBy, VisitStatus

QTY_MIN: Final = 1
QTY_MAX: Final = 99
COMMENT_MAX: Final = 200
MESSAGE_TEXT_MAX: Final = 8000
# Стоимость вызова ИИ в долларах с точностью до миллионных (ADR-7.4, NFR-7).
COST_USD_TYPE: Final = Numeric(12, 6, asdecimal=True)

# Предикаты частичных индексов: значения из перечислений (ADR-7.2).
OPEN_VISIT_PREDICATE: Final = sql_in("status", [VisitStatus.OPEN])

TOKEN_COLUMNS: Final[tuple[str, ...]] = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")


class Visit(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Сессия стола: общий диалог и одна корзина для всех устройств за столом (ТЗ 7)."""

    __tablename__ = "visits"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "table_id"],
            ["tables.tenant_id", "tables.id"],
            ondelete="RESTRICT",
        ),
        Index("uq_visits_open_table", "table_id", unique=True, postgresql_where=sql_text(OPEN_VISIT_PREDICATE)),
        Index(None, "tenant_id", "table_id", "opened_at"),
        # Межарендное подметание забытых визитов (#23, visit_idle_close_hours).
        Index("ix_visits_open_last_activity", "last_activity_at", postgresql_where=sql_text(OPEN_VISIT_PREDICATE)),
        CheckConstraint(sql_in("status", VisitStatus), name="status"),
        CheckConstraint(sql_in("lang", Lang), name="lang"),
        CheckConstraint(sql_in("closed_by", VisitClosedBy), name="closed_by"),
        CheckConstraint(
            f"({sql_in('status', [VisitStatus.OPEN])} AND closed_at IS NULL AND closed_by IS NULL) OR "
            f"({sql_in('status', [VisitStatus.CLOSED])} AND closed_at IS NOT NULL AND closed_by IS NOT NULL)",
            name="closed_state",
        ),
    )

    table_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=VisitStatus.OPEN.value)
    lang: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class Message(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Сообщение диалога. ``role`` — в терминах Claude API: ``user`` (гость или tool_result) и
    ``assistant`` (бот). Личных данных нет (NFR-5); содержимое — данные, не инструкции (AI-3)."""

    __tablename__ = "messages"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "visit_id"],
            ["visits.tenant_id", "visits.id"],
            ondelete="CASCADE",
        ),
        Index(None, "tenant_id", "visit_id", "created_at"),
        # Очистка по dialog_retention_days (#23): только ещё не обезличенные сообщения.
        Index("ix_messages_retention", "created_at", postgresql_where=sql_text("redacted_at IS NULL")),
        # Выборки заведения по времени (метрики стоимости, экспорт, NFR-6/NFR-8).
        Index(None, "tenant_id", "created_at"),
        CheckConstraint(sql_in("role", MessageRole), name="role"),
        CheckConstraint(sql_length("text", MESSAGE_TEXT_MAX), name="text"),
        CheckConstraint("jsonb_typeof(content) = 'array'", name="content"),
        *(CheckConstraint(f"{column} >= 0", name=column) for column in TOKEN_COLUMNS),
        CheckConstraint("cost_usd >= 0", name="cost_usd"),
        CheckConstraint("latency_ms >= 0", name="latency_ms"),
        CheckConstraint("content IS NOT NULL OR redacted_at IS NOT NULL", name="content_or_redacted"),
        # Обезличенное сообщение не хранит текст диалога (NFR-5).
        CheckConstraint("redacted_at IS NULL OR (content IS NULL AND text IS NULL)", name="redacted_empty"),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # none_as_null: Python None → SQL NULL, а не JSON null (иначе CHECK content/redacted не сработает).
    content: Mapped[list[Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(COST_USD_TYPE, nullable=False, server_default=sql_text("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=10
    )


class CartItem(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Строка корзины визита. ``price_at_add`` и ``price_tier`` — снимок цены за единицу и тарифа
    стола на момент добавления; при отправке сервис сверяет их с последним снимком меню (INT-3)."""

    __tablename__ = "cart_items"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "visit_id"],
            ["visits.tenant_id", "visits.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "visit_id", "menu_item_id", "comment"),
        CheckConstraint(sql_between("qty", QTY_MIN, QTY_MAX), name="qty"),
        CheckConstraint(sql_length("comment", COMMENT_MAX), name="comment"),
        CheckConstraint(sql_match("price_tier", PRICE_TIER_PATTERN), name="price_tier"),
        CheckConstraint("price_at_add >= 0", name="price_at_add"),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    price_tier: Mapped[str] = mapped_column(Text, nullable=False)
    price_at_add: Mapped[Decimal] = mapped_column(Money, nullable=False)
