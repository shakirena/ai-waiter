# Story #54: Проверка миграций в CI — upgrade, downgrade, инварианты схемы

*Parent: #7. Spec: docs/specs/feature-7-data-model.md (FR-9, NFR-1, NFR-2, AC-7). Arch: docs/arch/feature-7-data-model.md (ADR-7.3, 7.4, 7.10, 7.11).*

---

## 💻 Реализация (developer)

**Branch:** feature/7-data-model (PR #57)
**Новые файлы:**
- backend/tests/db/test_schema_invariants.py — инварианты реальной схемы после `upgrade head` из `pg_catalog`/`information_schema`: `tenant_id NOT NULL` и первый в полном (не частичном) индексе — обычном, UNIQUE или PK; явный список денежных колонок ADR-7.4 = `numeric(10,2)`; любая `numeric` = `numeric(10,2)`, кроме `messages.cost_usd (12,6)` и `menu_item_meta.weight_amount (8,2)`; `real`/`double precision`/`money` запрещены; нет `timestamp without time zone`, все `*_at` — `timestamptz`; `created_at` во всех таблицах, кроме `alembic_version`. Функции `tenant_violations`, `money_column_violations`, `numeric_violations`, `timestamp_violations` принимают имя схемы; негативные тесты — временные таблицы в схеме `schema_invariants_probe` внутри откатываемой транзакции. 12 тестов.

**Изменённые файлы:**
- .github/workflows/ci.yml — в `backend-services` перед pytest шаги `uv run alembic upgrade head` / `downgrade base` / `upgrade head` / `check` (DATABASE_URL джоба = ai_waiter_test)
- backend/tests/test_repo_artifacts.py — тест порядка CLI-шагов до pytest и `DATABASE_URL == TEST_DATABASE_URL`
- README.md, шаг «5. База данных» — локальная проверка миграций на Windows (PowerShell, uv или `.venv`) и Linux на `ai_waiter_test`
- backend/app/models/menu.py, backend/alembic/versions/0002_menu.py, backend/tests/test_models_metadata.py — индексы `ix_menu_item_prices_tenant_id_menu_item_id`, `ix_menu_item_meta_tenant_id_menu_item_id`

**Решения:**
- Новый тест нашёл расхождение: у `menu_item_prices` (PK `menu_item_id, price_tier`) и `menu_item_meta` (PK `menu_item_id`) не было индекса с ведущим `tenant_id` — нарушение NFR-1 spec и п.1 ADR-7.3 («tenant_id покрыт составными индексами»). Исправлено в ревизии 0002 (PR не влит, ревизия нигде не применялась в проде), а не исключением в тесте. В словаре данных arch эти индексы не перечислены — нужен doc-sync.
- Ревизия 0002 изменена: локальные БД, поднятые старой 0002, нужно пересоздать (`DROP SCHEMA public CASCADE; CREATE SCHEMA public;` → `upgrade head` → сид), иначе `downgrade` падает на `DROP INDEX`, а `alembic check` видит отсутствие индексов.
- Исключение `menu_item_meta.weight_amount NUMERIC(8,2)` (вес порции, не деньги) добавлено к `messages.cost_usd` — так в реальной схеме и в `test_models_metadata.py`.
- Порядок в CI: CLI-цикл до pytest; db-фикстуры сами делают `DROP SCHEMA public` + `upgrade head`, поэтому состояние после CLI им не мешает.

**Build:** ruff check OK · ruff format --check OK · pytest полный 1017 passed, 3 skipped (scaled без Redis) · -m db 222 passed · -m "not db and not scaled" 795 passed · alembic upgrade head / downgrade base / upgrade head / check на ai_waiter_test — код 0, БД оставлена в head (0004)
