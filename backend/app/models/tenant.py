"""Платформа и заведение: ``Tenant`` (tenants), ``Hall`` (halls), ``Table`` (tables).

Колонки, ограничения и индексы — docs/arch/feature-7-data-model.md, раздел «Словарь данных →
Платформа и заведение». Ревизия Alembic ``0001_tenants_tables``.

- ``Tenant`` — без ``tenant_id`` (сама арендная единица); ``settings`` — jsonb-объект,
  хранит только переопределения порогов ТЗ 3.4 и правила бота (FR-19, FR-21); эффективные
  значения даёт Pydantic-модель ``TenantSettings`` (вне #7, вместе с первым потребителем).
- ``Hall`` — ``TenantMixin``, ``UNIQUE (tenant_id, name)``.
- ``Table`` — ``TenantMixin``; ``qr_token`` глобально уникален (по нему определяется
  заведение, FR-1); ``UNIQUE (tenant_id, external_id)``; составной FK ``(tenant_id, hall_id)``.

Relationships не объявлены (ADR-7.3: только там, где нужны) — связи выбираются запросами
с явным ``tenant_id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.checks import sql_in, sql_length, sql_match, sql_text_array
from app.models.enums import (
    CURRENCY_PATTERN,
    DEFAULT_PRICE_TIER,
    PRICE_TIER_PATTERN,
    QR_TOKEN_PATTERN,
    Lang,
    TableType,
)

# Значения по умолчанию заведения (словарь данных): валюта и часовой пояс пилота.
DEFAULT_CURRENCY = "AZN"
DEFAULT_TIMEZONE = "Asia/Baku"
# Сортировка по sort_key — побайтно, одинаково на Windows и Linux (ADR-7.13).
SORT_KEY_TYPE = Text(collation="C")


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Заведение (арендатор). Языки: первый элемент — язык по умолчанию (FR-2)."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(sql_length("name", 200, 1), name="name"),
        CheckConstraint(sql_match("currency", CURRENCY_PATTERN), name="currency"),
        CheckConstraint(
            f"cardinality(languages) >= 1 AND languages <@ {sql_text_array(Lang)}",
            name="languages",
        ),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="settings"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=DEFAULT_CURRENCY)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default=DEFAULT_TIMEZONE)
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text(f"'{{{','.join(Lang)}}}'::text[]"),
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class Hall(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Зал заведения; из ``PUT /tables`` коннектора приходит только названием."""

    __tablename__ = "halls"
    __extra_table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint(sql_length("name", 100, 1), name="name"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_key: Mapped[str] = mapped_column(SORT_KEY_TYPE, nullable=False, server_default="")


class Table(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Стол или кабинет (FR-15). Перевыпуск токена (FR-1) — UPDATE ``qr_token`` и ``token_issued_at``."""

    __tablename__ = "tables"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "hall_id"],
            ["halls.tenant_id", "halls.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("qr_token"),
        UniqueConstraint("tenant_id", "external_id"),
        Index(None, "tenant_id", "hall_id"),
        CheckConstraint(sql_length("name", 100, 1), name="name"),
        CheckConstraint(sql_in("type", TableType), name="type"),
        CheckConstraint(sql_match("price_tier", PRICE_TIER_PATTERN), name="price_tier"),
        CheckConstraint(sql_length("external_id", 64, 1), name="external_id"),
        CheckConstraint(sql_match("qr_token", QR_TOKEN_PATTERN), name="qr_token"),
    )

    hall_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False, server_default=TableType.TABLE.value)
    price_tier: Mapped[str] = mapped_column(Text, nullable=False, server_default=DEFAULT_PRICE_TIER)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
