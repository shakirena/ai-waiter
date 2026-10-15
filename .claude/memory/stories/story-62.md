# Story #62: Применение снимка меню к базе по external_id со скрытием пропавших позиций

*Parent: #8. Spec: docs/specs/feature-8-menu-import.md (AC-2).*

---

## 📋 Задача (analyst)

**AC:** Given позиции 1001, 1002, 1003 (с meta), скрытая 1004, у другого заведения своя 1001 When применяется снимок 1001 (новая цена), 1002, 1004, 1005 Then новая цена у 1001, 1003 скрыта с сохранением meta, 1004 снова видима, 1005 создана, ничего не удалено, чужое заведение не изменилось
**Роли:** оператор; косвенно гость и ИИ (видят только не скрытые позиции)
**ТЗ:** INT-2, FR-16, FR-17, 4.4 `PUT /menu`, NFR-4
**Arch:** ADR-8.3, 8.4 — `app/menu_sync/plan.py` (`plan_menu_sync`, чистая), `app/menu_sync/service.py` (`apply_menu_snapshot`, advisory lock → `MenuSyncBusyError`, «всё или ничего», `mass_hide` ≥ 10 и ≥ 30 %, пустой снимок отвергается, dry_run, тарифы вне снимка удаляются, `is_available=None` не меняет наличие)
**Ограничения:** журнал `menu_sync_runs`, `unchanged`, `force`, `record_rejected_run` (#63), разбор файлов, CLI, данные админа (meta, аллергены, name_az/name_ru), стоп-лист (#16, #28)
**Зависимости:** #61
**Spec:** docs/specs/feature-8-menu-import.md

---

## 🏗️ Архитектура (architect)

**ADR:** ADR-8.1, ADR-8.3 (алгоритм), ADR-8.4 (транзакция, lock, «всё или ничего», mass-hide), ADR-8.6 (без EventBus); DEC-011
**Таблицы:** `categories`, `menu_items`, `menu_item_prices` (запись), `tenants` (чтение валюты); `menu_item_meta`/`menu_item_allergens` не трогаются; tenant_id: да, в каждом запросе
**Миграция:** нет (ревизия `0005` — только #63)
**API:** нет
**События/задачи:** нет (CLI — отдельный процесс; меню читается из БД без кеша в памяти)
**ИИ-tools:** не затронуты
**Security:** `tenant_id` — аргумент, не из данных; составные FK #7; `pg_try_advisory_xact_lock(8, hashtext(tenant_id::text))`; снимок с ошибками не применяется
**Code stubs:**
- `backend/app/menu_sync/plan.py` — `CurrentCategory`, `CurrentItem`, `CurrentMenu`, `CategoryWrite`, `ItemWrite`, `MenuSyncPlan`; `plan_menu_sync(current, snapshot, *, allow_mass_hide=False) -> MenuSyncPlan` (чистая); `MASS_HIDE_MIN_ITEMS = 10`, `MASS_HIDE_RATIO = Decimal("0.30")`
- `backend/app/menu_sync/service.py` — `apply_menu_snapshot(session, *, tenant_id, snapshot, source, source_ref=None, dry_run=False, force=False, allow_mass_hide=False) -> MenuSyncReport` (шаги 1, 2, 4, 5 из docstring); `load_current_menu(session, tenant_id) -> CurrentMenu`; `MenuSyncError`, `MenuSyncBusyError`, `TenantNotFoundError`; `MENU_SYNC_LOCK_NAMESPACE = 8`
**Без журнала:** статусы только `applied`/`rejected`; `snapshot_hash`/`run_id` = `None`; `force` принимается и не влияет; #63 добавит шаги 3 и 6 без смены сигнатуры
**Правила:** upsert по `(tenant_id, external_id)`; пропавшие → `is_hidden`, вернувшиеся → `restored`; тарифы вне снимка удаляются; `is_available=None` — не менять; `synced_at` всем присутствующим, `updated_at` — только изменённым (явно в UPSERT); сервис не коммитит
**Тесты:** unit `tests/test_menu_plan.py`; db `tests/db/test_menu_sync_apply.py` (AC #62, два заведения, meta цела, dry-run, lock через второе соединение, `TenantNotFoundError`)
**Зависимости:** #61
**Arch doc:** docs/arch/feature-8-menu-import.md (раздел «Истории — файлы, тесты, порядок»)

---

## 💻 Разработка (developer)

**Branch:** story/62-menu-import (от feature/8-menu-import на c7bec9c, worktree s62)
**Новые файлы:**
- backend/tests/test_menu_plan.py
- backend/tests/db/test_menu_sync_apply.py

**Изменённые файлы:**
- backend/app/menu_sync/plan.py — `plan_menu_sync` (чистая; `new_id` из `app.db.ids`, тесты подменяют), `is_mass_hide`, `_plan_categories`, `_plan_items`, `_plan_prices`, `_clear_writes`
- backend/app/menu_sync/service.py — `load_current_menu` (3 SELECT с фильтром `tenant_id`), `apply_menu_snapshot` (шаги 1, 2, 4, 5), `_acquire_lock`, `_tenant_currency`, `_report`, `_write_plan`, `_upsert_items`; `last_applied_hash`/`record_rejected_run` остаются заглушками #63

**Решения:**
- Счётчики: строка попадает ровно в одно поле; изменение только цен или только наличия — `updated` (строка `menu_items` переписывается, `updated_at` меняется). `availability_changed` — только существующие позиции (у новых не считается).
- `present_*_ids` — все строки снимка, включая новые; `synced_at` ставится одним `UPDATE … WHERE tenant_id AND id IN (…)` с `updated_at = updated_at` (иначе сработал бы `onupdate`). `updated_at` у изменённых — явно в UPSERT/`UPDATE` скрытия.
- Цены: UPSERT по `(menu_item_id, price_tier)` с `WHERE price IS DISTINCT FROM excluded.price` — неизменённые тарифы не перезаписываются; удаление — `DELETE … WHERE tenant_id AND (menu_item_id, price_tier) IN (…)`.
- `is_available=None` — позиции пишутся отдельным пакетом без колонки (у новой срабатывает `DEFAULT true`).
- `mass_hide`: счётчики плана сохраняются (сообщение «скрыл бы N из M видимых»), списки записи очищаются; в отчёте отклонённого снимка счётчики нулевые (как при ошибках `check_snapshot`).
- Lock: `pg_try_advisory_xact_lock(:namespace, hashtext(CAST(:tenant_id AS text)))` с `str(uuid)` — совпадает с `hashtext(tenant_id::text)` (db-тест берёт lock во втором соединении через `CAST(… AS uuid)::text`).
- Отчёт всегда проходит через `limit_issues` (≤ 100 проблем, остальное — `issues_truncated`); пробный прогон без ошибок — `applied` с `dry_run=True`.
- `source`, `source_ref`, `force` до #63 не используются.

**Build:** ruff check / format OK · pytest 1218 passed, 3 skipped (с db; без Redis) · покрытие plan.py — 100 %, service.py — 99 % (не покрыты только заглушки #63)

---

## 🔒 Security Review (security-reviewer)

**Verdict:** PASS (метка security:passed, https://github.com/shakirena/ai-waiter/issues/62#issuecomment-6167079534)
**Delta:** c7bec9c..154c614
**Findings:** CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 1, INFO: 1
**Notes:**
- [LOW] `_write_plan`: удаление тарифов `tuple_(menu_item_id, price_tier).in_(...)` — 2 параметра на пару; снимок `MAX_ITEMS` × `MAX_TIERS_PER_ITEM` (≈ 45 000 пар) превышал лимит asyncpg 32 767 и глубину выражения PostgreSQL → откат легитимного снимка.
- [INFO] `ON CONFLICT` цен по PK без `tenant_id` — безопасно, но без пояснения.

**Исправление (fix(#62), ветка story/63-menu-import):** удаление тарифов — один `DELETE … USING unnest(:ids::uuid[], :tiers::text[])` (3 параметра на любой объём); остальные записи плана (UPSERT категорий, позиций, цен, `UPDATE` скрытия и `synced_at`) — пакетами по `WRITE_BATCH_ROWS = 1000` строк/id (самая широкая строка — позиция, ≈ 11 параметров). К `ON CONFLICT` цен добавлен комментарий: `menu_item_id` только своего заведения + составной FK. db-тест `test_max_size_snapshot_fits_bind_parameter_limit`: 5000 позиций × 10 тарифов, затем 5000 × 1 — применяется (45 000 удалённых цен).
