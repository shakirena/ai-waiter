"""Платформа и заведение: ``Tenant`` (tenants), ``Hall`` (halls), ``Table`` (tables).

Заглушка: колонки, ограничения и индексы — docs/arch/feature-7-data-model.md, раздел
«Словарь данных → Платформа и заведение». Ревизия Alembic ``0001_tenants_tables``.

- ``Tenant`` — без ``tenant_id`` (сама арендная единица); ``settings`` — jsonb-объект,
  хранит только переопределения порогов ТЗ 3.4 и правила бота (FR-19, FR-21); эффективные
  значения даёт Pydantic-модель ``TenantSettings`` (вне #7, вместе с первым потребителем).
- ``Hall`` — ``TenantMixin``, ``UNIQUE (tenant_id, name)``.
- ``Table`` — ``TenantMixin``; ``qr_token`` глобально уникален (по нему определяется
  заведение, FR-1); ``UNIQUE (tenant_id, external_id)``; FK ``(tenant_id, hall_id)``.
"""
