# Story #51: Модель данных — визит (visits, messages, cart_items)

*Parent: #7. Spec: docs/specs/feature-7-data-model.md (AC-4). Arch: docs/arch/feature-7-data-model.md (ADR-7.3, 7.4, 7.5, 7.7; словарь «Визит»).*

---

## 💻 Реализация (developer)

**Branch:** feature/7-data-model
**Новые файлы:**
- backend/alembic/versions/0003_visits.py (rev 0003, down_revision 0002; autogenerate + ручная чистка, docstring на русском)
- backend/tests/db/test_visits.py (AC-4 целиком; один открытый визит на стол, повторное открытие закрытого, ON CONFLICT по частичному индексу; CHECK visits/messages/cart_items; qty 1..99; обезличивание; CASCADE/RESTRICT; определения частичных индексов в БД)

**Изменённые файлы:**
- backend/app/models/visit.py (Visit, Message, CartItem), backend/app/models/__init__.py (+ visit)
- backend/app/models/checks.py (+ `sql_not_in`, пригодится в #52)
- backend/tests/test_models_metadata.py (EXPECTED_TABLES, EXPECTED_CHECKS, NUMERIC_EXCEPTIONS `messages.cost_usd (12,6)`, тесты индексов/ON DELETE/CHECK визита)
- backend/tests/test_migrations_offline.py (REVISION_TABLES 0003, SQL частичных индексов)
- backend/tests/db/test_migrations.py (REVISION_TABLES 0003, ENUM_CHECKS: ck_visits_status/lang/closed_by, ck_messages_role)
- backend/tests/db/test_tenant_isolation.py (visit→стол, cart_item→позиция меню/визит, message→визит другого заведения)
- backend/tests/db/factories.py (build_visit/create_visit, build_cart_item, build_message)

**Решения:**
- `visits`: TS (`created_at`/`updated_at`) + `opened_at` — по таблице словаря (в сверке со spec написано «opened_at + updated_at», но metadata-тест требует `created_at` у всех таблиц).
- Предикаты частичных индексов строятся из `VisitStatus` (`status IN ('open')`, в БД — `status = 'open'::text`); `ON CONFLICT (table_id) WHERE status = 'open'` работает (тест).
- `messages.content` — `JSONB(none_as_null=True)`: без этого None пишется как JSON `null`, и CHECK `content_or_redacted` не срабатывает (найдено тестом).
- Сверх arch: `ck_messages_latency_ms` (`>= 0`), `ck_messages_redacted_empty` (`redacted_at IS NULL OR (content IS NULL AND text IS NULL)`: обезличенное сообщение не хранит текст, NFR-5), индекс `ix_messages_tenant_id_created_at` (из issue/указания dev-lead).
- Неизвестный `status` визита при вставке ловит `ck_visits_closed_state` (PostgreSQL проверяет CHECK в алфавитном порядке имён); `ck_visits_status` проверен отдельно (тест с удалённым closed_state в откатываемой транзакции) и сверкой с перечислением.
- Роли сообщений — `user`/`assistant` (arch), не `tool`/`system` из текста issue.

**Build:** ruff check OK · ruff format --check OK · pytest -m "not db and not scaled" 657 passed · pytest -m db 144 passed (ai_waiter_test) · общий прогон 801 passed, 3 skipped (scaled без Redis) · покрытие app/models/visit.py и checks.py 100% · alembic upgrade head / downgrade base / upgrade head / check — код 0
