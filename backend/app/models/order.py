"""Заказ: ``Order``, ``OrderItem``, ``OrderEvent``.

Заглушка: колонки — docs/arch/feature-7-data-model.md, «Словарь данных → Заказ».
Ревизия Alembic ``0004_orders`` (включая триггер append-only для ``order_events``).

- ``orders.id`` (UUIDv7) — это ``order_id`` Integration API (ТЗ 4.4, ``ai_order_map`` кассы).
- ``UNIQUE (tenant_id, idempotency_key)`` (NFR-3).
- ``order_items`` хранят снимки: ``name_snapshot`` (``pos_name`` на момент заказа) и
  ``price_at_order`` (ADR-7.4); ``removed_by_staff`` вместо удаления строки (FR-13).
- ``confirmed_by_staff_id`` — UUID без FK до появления ``staff_users`` (#19), ADR-7.7.
- ``order_events`` — только INSERT; UPDATE/DELETE запрещены триггером (ADR-7.6).
"""
