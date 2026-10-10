# Feature #7: Модель данных v1 и миграции Alembic

## 📋 Задача (analyst)

**Stories:** #48, #49, #50, #51, #52, #53, #54
**Spec:** docs/specs/feature-7-data-model.md
**Открытые вопросы:** 24 пункта в разделе «Открытые вопросы» spec (решает architect / analysis-lead)
**Вне #7:** staff_users (#19), connectors (#16), waiter_calls (#22), reviews (#25)

---

## 🏗️ Архитектура (architect)

**Arch doc:** docs/arch/feature-7-data-model.md (ADR-7.1…ADR-7.14, ERD, словарь данных, сверка со spec)
**Таблицы (все новые, tenant_id: да, кроме tenants):** tenants, halls, tables · categories, menu_items, menu_item_prices, menu_item_meta, allergens, menu_item_allergens · visits, messages, cart_items · orders, order_items, order_events
**Миграции (backend/alembic/versions, линейно):** 0001_tenants_tables (#49) → 0002_menu (#50) → 0003_visits (#51) → 0004_orders (#52, + триггер append-only order_events). #48 — alembic.ini/env.py (async), app/db, фикстура db без таблиц. #53 — app/seed. #54 — tests/db/test_migrations.py (upgrade/downgrade/upgrade, alembic check) + tests/test_models_metadata.py.
**Ключевые решения:** PK UUIDv7 везде (ADR-7.1); статусы text+CHECK из StrEnum (7.2); составные FK (tenant_id, x_id) + UNIQUE (tenant_id, id), RLS — позже (7.3); NUMERIC(10,2) и снимки в order_items, исключение messages.cost_usd NUMERIC(12,6) (7.4); корзина = cart_items визита, один open-визит на стол (7.5); order_events append-only триггером (7.6); confirmed_by_staff_id/closed_by_staff_id — uuid без FK до #19 (7.7); naming_convention (7.8); Container.database, get_session без автокоммита (7.9); TEST_DATABASE_URL с guard *_test (7.11); сид идемпотентный, запрет в prod (7.12); БД UTF8 + LOCALE C, tzdata (7.13).
**Отличия от рекомендаций spec (обновить stories):** PK uuid вместо bigint; составные FK; qty integer 1–99; visits.closed_by = staff/pos/timeout; messages: input_tokens/output_tokens/cache_*/cost_usd/content; name_snapshot = pos_name; каталог backend/alembic/.
**API:** нет; /health/ready "database" — отдельная story после #48 (spec, вопрос 19).
**События/задачи:** нет; индексы под подметание #23 (ix_orders_pending_confirm, ix_visits_open_last_activity, ix_messages_retention).
**Security:** составные FK против межарендных ссылок; qr_token глобально UNIQUE + CHECK ≥22 base64url; idempotency_key UNIQUE в границах tenant; сид запрещён в prod; тестовая БД только *_test.
**Code stubs:** backend/app/db/{__init__,base,ids,mixins,session}.py, backend/app/models/{__init__,enums,reference,tenant,menu,visit,order}.py, backend/app/seed/{__init__,__main__}.py
