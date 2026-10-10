"""Слой доступа к PostgreSQL (issue #7, docs/arch/feature-7-data-model.md).

- ``base.py`` — ``Base`` (DeclarativeBase) с ``NAMING_CONVENTION`` (ADR-7.8);
- ``ids.py`` — генерация первичных ключей UUIDv7 (ADR-7.1);
- ``mixins.py`` — ``TenantMixin``, ``TimestampMixin`` (ADR-7.3);
- ``session.py`` — ``Database``: async-движок asyncpg и фабрика сессий (ADR-7.9).

Зависимости ``sqlalchemy[asyncio]``, ``asyncpg``, ``alembic`` добавляет developer в #7;
до этого модули пакета не импортируют SQLAlchemy на уровне модуля.
"""
