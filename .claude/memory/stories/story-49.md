# Story #49: Модель данных — tenants, halls, tables

*Parent: #7. Spec: docs/specs/feature-7-data-model.md (AC-2). Arch: docs/arch/feature-7-data-model.md (ADR-7.1–7.3, 7.8, 7.13; словарь «Платформа и заведение»).*

---

## 💻 Реализация (developer)

**Branch:** feature/7-data-model
**Новые файлы:**
- backend/alembic/versions/0001_tenants_tables.py (rev 0001, корень цепочки; `check_server_encoding` — RuntimeError, если БД не UTF8; в офлайн-режиме пропускается)
- backend/app/models/checks.py — построители текста CHECK (`sql_in`, `sql_match`, `sql_length`, `sql_between`, `sql_text_array`), отказ на апостроф/NUL и некорректное имя колонки
- backend/tests/test_models_metadata.py — инварианты metadata без БД (tenant_id NOT NULL + FK RESTRICT, UNIQUE (tenant_id, id), составные FK, UUID, timestamptz, NUMERIC(10,2) со списком исключений, имена по соглашению ≤ 63, явный список CHECK по таблицам, CHECK из перечислений, COLLATE "C" у sort_key)
- backend/tests/test_migrations_offline.py — `upgrade --sql` без БД, линейная цепочка, каждая ревизия создаёт/удаляет ровно свои таблицы, проверка кодировки на фейковом соединении
- backend/tests/db/factories.py — построители строк, `expect_violation` (begin_nested + имя нарушенного ограничения из asyncpg)
- backend/tests/db/test_tenants_tables.py (AC-2), backend/tests/db/test_tenant_isolation.py, backend/tests/db/test_migrations.py (downgrade -1 по ревизиям, CHECK = перечисления, UTF8)

**Изменённые файлы:**
- backend/app/models/tenant.py (Tenant, Hall, Table), backend/app/models/__init__.py (импорт модулей моделей), backend/app/models/enums.py (QR_TOKEN_PATTERN, ALLERGEN_CODE_PATTERN, ABSOLUTE_PATH_PATTERN, WeightUnit)
- backend/app/db/mixins.py — `sort_order` колонок: id, tenant_id первыми, created_at/updated_at последними (только порядок колонок в DDL)
- backend/tests/test_alembic_setup.py — корень цепочки теперь строго `0001`

**Решения:**
- Тип стола `table`/`cabin` (как `TableType` и словарь arch), а не `cabinet` из текста issue; у залов `sort_key` (arch), а не `sort_order`.
- `sort_key` — `TEXT COLLATE "C"` (побайтная сортировка независимо от локали БД, ADR-7.13).
- Relationships не объявлены (ADR-7.3: только где нужны); значения по умолчанию — серверные, ORM получает их через RETURNING (eager_defaults auto).
- Ревизия сгенерирована autogenerate, проверена вручную; комментарии autogenerate удалены.

**Build:** ruff OK · ruff format OK · pytest -m "not db and not scaled" 545 passed · pytest -m db 49 passed (ai_waiter_test) · alembic upgrade head / downgrade base / upgrade head / check — код 0
