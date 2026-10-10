"""Миксины моделей (ADR-7.1, ADR-7.3, ADR-7.4).

Пример модели заведения::

    class Hall(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
        __tablename__ = "halls"
        __extra_table_args__ = (UniqueConstraint("tenant_id", "name"),)

        name: Mapped[str] = mapped_column(Text)

``__table_args__`` формирует ``TenantMixin``: свои ограничения модель перечисляет в
``__extra_table_args__`` (ограничения и индексы; словарь опций таблицы — последним элементом,
как в ``__table_args__``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.ids import new_id


class UUIDPrimaryKeyMixin:
    """``id UUID PRIMARY KEY``: значение UUIDv7 из ``new_id``; запасной ``server_default
    gen_random_uuid()`` — для ручных INSERT (ADR-7.1)."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=new_id,
        server_default=text("gen_random_uuid()"),
    )


class TenantMixin:
    """Таблица заведения (ADR-7.3).

    - ``tenant_id UUID NOT NULL`` → FK ``tenants.id`` ON DELETE RESTRICT;
    - ``UNIQUE (tenant_id, id)`` (имя ``uq_<table>_tenant_id_id``) — цель составных FK дочерних
      таблиц, чтобы строка не могла сослаться на родителя другого заведения;
    - отдельный индекс по ``tenant_id`` не нужен: его покрывает этот UNIQUE.

    Ограничения задаются через ``__table_args__`` (``declared_attr``), потому что имя таблицы
    известно только в наследнике. Для таблиц-связок с составным PK (``menu_item_prices``,
    ``menu_item_allergens``) ``UNIQUE (tenant_id, id)`` не создаётся — у них нет ``id``.
    """

    __extra_table_args__: ClassVar[tuple[Any, ...]] = ()

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )

    @declared_attr.directive
    @classmethod
    def __table_args__(cls) -> tuple[Any, ...]:
        args: list[Any] = []
        if issubclass(cls, UUIDPrimaryKeyMixin):
            args.append(UniqueConstraint("tenant_id", "id"))
        extra = list(cls.__extra_table_args__)
        options = extra.pop() if extra and isinstance(extra[-1], dict) else None
        args.extend(extra)
        if options is not None:
            args.append(options)
        return tuple(args)


class TimestampMixin:
    """``created_at``/``updated_at TIMESTAMPTZ NOT NULL DEFAULT now()``; ``updated_at``
    обновляется ORM (``onupdate=func.now()``), без триггера. Только aware-datetime (ruff DTZ)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
