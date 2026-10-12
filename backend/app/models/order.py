"""Заказ: ``Order`` (orders), ``OrderItem`` (order_items), ``OrderEvent`` (order_events).

Колонки — docs/arch/feature-7-data-model.md, «Словарь данных → Заказ». Ревизия Alembic
``0004_orders`` (включая триггер append-only для ``order_events``).

- ``orders.id`` (UUIDv7) — это ``order_id`` Integration API (ТЗ 4.4, ``ai_order_map`` кассы).
- ``UNIQUE (tenant_id, idempotency_key)`` (NFR-3, ADR-7.3): повтор ключа в том же заведении
  отвергается, в другом — нет (нет межарендного оракула).
- ``status`` — 8 значений ``OrderStatus`` (ТЗ 4.6); переходы проверяет сервис по
  ``app.models.enums.can_transition``, БД проверяет только допустимость значения и
  согласованность (``confirmed_at`` у подтверждённых, ``reject_reason`` у отклонённых).
- ``order_items`` хранят снимки: ``name_snapshot`` (``pos_name`` на момент заказа) и
  ``price_at_order`` (ADR-7.4); ``removed_by_staff`` вместо удаления строки (FR-13).
- ``confirmed_by_staff_id`` — UUID без FK до появления ``staff_users`` (#19), ADR-7.7.
- ``order_events`` — только INSERT; UPDATE/DELETE запрещены триггером (ADR-7.6). ``actor_id`` —
  мягкая ссылка без FK (полиморфна по ``actor_type``). Только ``created_at``.

ON DELETE (ADR-7.3): ``order_items`` принадлежат заказу — CASCADE; заказ → визит, строка →
позиция меню и событие → заказ — RESTRICT (заказы не удаляются).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.checks import sql_between, sql_in, sql_length, sql_match, sql_not_in
from app.models.enums import (
    CONFIRMED_STATUSES,
    CURRENCY_PATTERN,
    PRICE_TIER_PATTERN,
    ActorType,
    OrderEventType,
    OrderStatus,
)
from app.models.visit import COMMENT_MAX, QTY_MAX, QTY_MIN

REJECT_REASON_MAX: Final = 500
POS_REF_MAX: Final = 64
POS_ERROR_MAX: Final = 1000

# Подтверждённые статусы в порядке объявления перечисления (текст CHECK детерминирован).
CONFIRMED_STATUS_VALUES: Final[tuple[OrderStatus, ...]] = tuple(s for s in OrderStatus if s in CONFIRMED_STATUSES)
# Ждут решения официанта — межарендное подметание эскалаций (#23).
PENDING_CONFIRM_STATUSES: Final[tuple[OrderStatus, ...]] = (OrderStatus.SUBMITTED, OrderStatus.EDITED)
# Очередь выдачи коннектору с push_order: GET /orders?after= с курсором (confirmed_at, id) (INT-5, #17).
POS_QUEUE_STATUSES: Final[tuple[OrderStatus, ...]] = (OrderStatus.CONFIRMED, OrderStatus.SENT_TO_POS)


class Order(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Заказ гостя. ``created_at`` — время отправки; сохраняется до любого вызова ИИ (NFR-3)."""

    __tablename__ = "orders"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "visit_id"],
            ["visits.tenant_id", "visits.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "idempotency_key"),
        Index(None, "tenant_id", "visit_id"),
        Index(None, "tenant_id", "status", "created_at"),
        Index(
            "ix_orders_pending_confirm",
            "created_at",
            postgresql_where=text(sql_in("status", PENDING_CONFIRM_STATUSES)),
        ),
        Index(
            "ix_orders_pos_queue",
            "tenant_id",
            "confirmed_at",
            "id",
            postgresql_where=text(sql_in("status", POS_QUEUE_STATUSES)),
        ),
        CheckConstraint(sql_in("status", OrderStatus), name="status"),
        CheckConstraint(sql_match("price_tier", PRICE_TIER_PATTERN), name="price_tier"),
        CheckConstraint("total >= 0", name="total"),
        CheckConstraint(sql_match("currency", CURRENCY_PATTERN), name="currency"),
        CheckConstraint("pos_total >= 0", name="pos_total"),
        CheckConstraint(sql_length("reject_reason", REJECT_REASON_MAX, 1), name="reject_reason_length"),
        CheckConstraint(sql_length("pos_ref", POS_REF_MAX), name="pos_ref"),
        CheckConstraint(sql_length("pos_error", POS_ERROR_MAX), name="pos_error"),
        CheckConstraint(
            f"{sql_not_in('status', CONFIRMED_STATUS_VALUES)} OR confirmed_at IS NOT NULL",
            name="confirmed_at",
        ),
        # FR-12: отклонение — всегда с причиной.
        CheckConstraint(
            f"{sql_not_in('status', [OrderStatus.REJECTED])} OR reject_reason IS NOT NULL",
            name="reject_reason",
        ),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=OrderStatus.SUBMITTED.value)
    price_tier: Mapped[str] = mapped_column(Text, nullable=False)
    total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pos_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    pos_total: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    pos_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_to_pos_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pos_acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderItem(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Строка заказа со снимком кассового названия и цены (не меняется при смене меню, INT-2)."""

    __tablename__ = "order_items"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["orders.tenant_id", "orders.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "menu_item_id"],
            ["menu_items.tenant_id", "menu_items.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "order_id", "menu_item_id", "comment"),
        CheckConstraint(sql_between("qty", QTY_MIN, QTY_MAX), name="qty"),
        CheckConstraint("price_at_order >= 0", name="price_at_order"),
        CheckConstraint(sql_length("comment", COMMENT_MAX), name="comment"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    price_at_order: Mapped[Decimal] = mapped_column(Money, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    removed_by_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())


class OrderEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Запись журнала заказа (FR-9, FR-13); пишется сервисом в той же транзакции, что и изменение."""

    __tablename__ = "order_events"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["orders.tenant_id", "orders.id"],
            ondelete="RESTRICT",
        ),
        Index(None, "tenant_id", "order_id", "created_at"),
        CheckConstraint(sql_in("type", OrderEventType), name="type"),
        CheckConstraint(sql_in("from_status", OrderStatus), name="from_status"),
        CheckConstraint(sql_in("to_status", OrderStatus), name="to_status"),
        CheckConstraint(sql_in("actor_type", ActorType), name="actor_type"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload"),
        CheckConstraint(
            f"{sql_not_in('type', [OrderEventType.STATUS_CHANGED])} OR to_status IS NOT NULL",
            name="status_change",
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=10
    )
