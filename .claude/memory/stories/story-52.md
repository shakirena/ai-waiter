# Story #52: Модель данных — заказ (orders, order_items, order_events)

*Parent: #7. Spec: docs/specs/feature-7-data-model.md (AC-5). Arch: docs/arch/feature-7-data-model.md (ADR-7.3, 7.4, 7.6, 7.7; словарь «Заказ»).*

---

## 💻 Реализация (developer)

**Branch:** feature/7-data-model
**Новые файлы:**
- backend/alembic/versions/0004_orders.py (rev 0004, down_revision 0003; функция `order_events_append_only()` и триггер `trg_order_events_append_only` BEFORE UPDATE OR DELETE через `op.execute` со статическим SQL; downgrade: таблица order_items, триггер, функция, order_events, orders)
- backend/tests/db/test_orders.py (AC-5 целиком; 8 статусов; ключ идемпотентности в границах заведения; CHECK заказа/строк/событий; снимок `name_snapshot`/`price_at_order` при смене `pos_name` и цены; UPDATE/DELETE журнала → SQLSTATE 23001; откат вставленных событий; ON DELETE; частичные индексы в БД)
- backend/tests/test_order_status.py (все 64 пары статусов для `can_transition`, терминальные статусы, `escalated → edited`, достижимость подтверждённых статусов, строки из БД, неизвестный статус → ValueError)

**Изменённые файлы:**
- backend/app/models/order.py (Order, OrderItem, OrderEvent), backend/app/models/__init__.py (+ order)
- backend/app/models/enums.py — `ORDER_TRANSITIONS` + `escalated → edited`, реализован `can_transition` (принимает `OrderStatus | str`)
- backend/tests/test_models_metadata.py, backend/tests/test_migrations_offline.py (триггер в SQL, порядок DROP, 15 таблиц), backend/tests/db/test_migrations.py (REVISION_TABLES 0004, ENUM_CHECKS заказа/событий, триггер исчезает при downgrade на 0003, `DROP SCHEMA public CASCADE` удаляет триггер и функцию), backend/tests/db/test_tenant_isolation.py (заказ→визит, строка→позиция меню/заказ, событие→заказ другого заведения), backend/tests/db/factories.py

**Решения:**
- `idempotency_key` — `uuid` (arch), не `text` из issue; `order_events.type` (arch), не `event_type`; FK `order_events → orders` RESTRICT (ADR-7.6), не CASCADE из issue.
- Длина `reject_reason` — отдельный CHECK `ck_orders_reject_reason_length` (1..500), т.к. имя `ck_orders_reject_reason` занято правилом FR-12 «rejected → причина обязательна». Пустая причина отвергается.
- Списки статусов в CHECK/индексах — в порядке объявления `OrderStatus` (а не обход frozenset): текст CHECK детерминирован при любом PYTHONHASHSEED.
- `checks.sql_not_in` (добавлен в #51) — для `ck_orders_confirmed_at`, `ck_orders_reject_reason`, `ck_order_events_status_change`.
- Текст исключения триггера — как в ADR-7.6 (`order_events is append-only`), ERRCODE `restrict_violation`.
- `edited → edited` не считается переходом (статус тот же, пишется событие) — зафиксировано комментарием в enums.

**Build:** ruff check OK · ruff format --check OK · pytest -m "not db and not scaled" 771 passed · pytest -m db 203 passed (ai_waiter_test) · общий прогон 974 passed, 3 skipped (scaled без Redis) · покрытие app/models 100% (order.py, enums.py, visit.py, checks.py) · alembic upgrade head / downgrade base / upgrade head / check — код 0
