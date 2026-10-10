"""Слой доступа к PostgreSQL (issue #7, docs/arch/feature-7-data-model.md).

- ``base.py`` — ``Base`` (DeclarativeBase) с ``NAMING_CONVENTION`` (ADR-7.8), тип ``Money``;
- ``ids.py`` — генерация первичных ключей UUIDv7 (ADR-7.1);
- ``mixins.py`` — ``UUIDPrimaryKeyMixin``, ``TenantMixin``, ``TimestampMixin`` (ADR-7.3);
- ``session.py`` — ``Database``: async-движок asyncpg и фабрика сессий (ADR-7.9).

Миграции — ``backend/alembic/`` (ADR-7.10), команды выполняются из ``backend/``.
"""
