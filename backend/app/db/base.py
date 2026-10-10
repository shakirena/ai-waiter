"""Декларативная база моделей и соглашение об именах ограничений (ADR-7.8).

Имена ограничений детерминированы, поэтому Alembic autogenerate и ``alembic check`` дают
стабильный diff, а downgrade может удалять ограничения по имени. Лимит PostgreSQL —
63 байта; длинные имена SQLAlchemy усекает с хеш-суффиксом, частичные индексы получают
явное ``name=``.

Реализация (developer, после добавления sqlalchemy в зависимости)::

    from sqlalchemy import MetaData
    from sqlalchemy.orm import DeclarativeBase

    class Base(DeclarativeBase):
        metadata = MetaData(naming_convention=NAMING_CONVENTION)

``alembic/env.py`` берёт ``target_metadata = Base.metadata`` после ``import app.models``
(пакет моделей импортирует все модули, чтобы таблицы попали в metadata).
"""

from __future__ import annotations

from typing import Final

# ck: в CheckConstraint задаётся короткое name="status" → ck_orders_status.
NAMING_CONVENTION: Final[dict[str, str]] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}
