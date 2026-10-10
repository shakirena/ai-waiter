"""Миксины моделей (ADR-7.3, ADR-7.4). Заглушки: колонки описаны в docstring, developer
переносит их в ``Mapped``-атрибуты после добавления sqlalchemy в зависимости.
"""

from __future__ import annotations


class UUIDPrimaryKeyMixin:
    """``id UUID PK``: ``mapped_column(Uuid, primary_key=True, default=new_id,
    server_default=text("gen_random_uuid()"))`` — см. ``app.db.ids.new_id``."""


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


class TimestampMixin:
    """``created_at TIMESTAMPTZ NOT NULL DEFAULT now()``,
    ``updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`` с ``onupdate=func.now()`` (на уровне ORM,
    без триггера). Только aware-datetime (ruff DTZ); ``DateTime(timezone=True)``."""
