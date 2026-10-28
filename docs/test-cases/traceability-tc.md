# Test Case Traceability Matrix

Обновлено: 2026-10-28. Feature #6 «Каркас проекта» (stories #37–#45, прогон 2026-10-02), feature #7 «Модель данных v1 и миграции Alembic» (stories #48–#54, #56, прогон 2026-10-12, финальный прогон G5 2026-10-13), feature #8 «Импорт меню из CSV/XLSX» (stories #61–#67, прогон 2026-10-19) и защита от демо-данных (story #60, прогон 2026-10-28). Столбец «Авто» — где тест выполняется автоматически (для #7 и #8 пути относительно `backend/tests/`, `db/` — тесты с маркером `db`, нужен PostgreSQL); «Прогон» — результат на дату прогона.

## Feature #6 — Каркас проекта

| TC ID | Title | Feature | AC | Priority | E2E Automated | Авто (unit/static) | Прогон |
|-------|-------|---------|-----|----------|---------------|--------------------|--------|
| TC-37-001 | Запуск backend и ответ /health в режиме single | #37 | AC-1 | Critical | No | test_health.py, test_main.py | PASS |
| TC-37-002 | Некорректный APP_MODE прерывает запуск | #37 | AC-1 | Critical | No | test_config.py, test_main.py | PASS |
| TC-37-003 | Отсутствие обязательной переменной в scaled | #37 | AC-1 | High | No | test_config.py | PASS |
| TC-37-004 | Безопасные значения по умолчанию и секреты | #37 | AC-1, NFR-2 | High | No | test_config.py, test_repo_artifacts.py | PASS |
| TC-37-005 | Готовность /health/ready, устойчивость к Redis | #37 | AC-1 | Medium | No | test_health.py | PASS |
| TC-37-006 | Структурированные логи, ленивое создание app | #37 | AC-1, NFR-4 | Medium | No | test_log.py, test_main.py | PASS |
| TC-38-001 | Фабрика возвращает реализации по APP_MODE | #38 | AC-2 | Critical | No | test_container.py, test_lifespan.py | PASS |
| TC-38-002 | Неизвестный режим и scaled без REDIS_URL | #38 | AC-2 | Critical | No | test_container.py, test_lifespan.py | PASS |
| TC-38-003 | Границы импортов redis, arq, apscheduler | #38 | AC-2, NFR-7 | High | No | test_import_boundaries.py | PASS |
| TC-38-004 | Контракты интерфейсов и событий | #38 | AC-2 | High | No | test_interfaces.py | PASS |
| TC-39-001 | Сквозной сценарий single без Redis | #39 | AC-3 | Critical | No | test_single_mode.py, test_events.py, test_scheduler.py, test_ratelimit.py | PASS |
| TC-39-002 | Изоляция тенантов и медленный подписчик | #39 | AC-3 | High | No | test_events.py | PASS |
| TC-39-003 | Планировщик: идемпотентность, отмена, остановка | #39 | AC-3 | High | No | test_scheduler.py | PASS |
| TC-39-004 | RateLimiter в памяти: окно и память | #39 | AC-3 | High | No | test_ratelimit.py | PASS |
| TC-40-001 | Событие, задача arq, общий счётчик лимита | #40 | AC-4 | Critical | No | test_scaled_*.py (fakeredis), test_scaled_redis.py (Redis, CI) | PASS (fakeredis); настоящий Redis — только CI |
| TC-40-002 | scaled без REDIS_URL, защита адреса | #40 | AC-4 | Critical | No | test_scaled_worker.py, test_container.py | PASS |
| TC-40-003 | Отказоустойчивость Redis-реализаций | #40 | AC-4 | High | No | test_scaled_events.py, test_scaled_scheduler.py, test_scaled_ratelimit.py, test_scaled_connection.py | PASS |
| TC-41-001 | Проверки frontend: lint, тесты, сборка | #41 | AC-5 | Critical | No | CI frontend (2 ОС) | PASS |
| TC-41-002 | Маршруты /t/:token, /staff, /admin | #41 | AC-5 | Critical | No | App.test.tsx, main.test.tsx | PASS |
| TC-41-003 | Неизвестные маршруты и отсутствие #root | #41 | AC-5 | Medium | No | App.test.tsx, main.test.tsx | PASS |
| TC-41-004 | PWA: манифест и service worker | #41 | AC-5 | High | No | pwa-config.test.ts | PASS |
| TC-41-005 | Клиент API: /health и ошибки | #41 | AC-5 | Medium | No | client.test.ts | PASS |
| TC-41-006 | Вёрстка на ширине 360 px | #41 | AC-5, NFR-3 | Medium | No | — (ручной) | НЕ ВЫПОЛНЕН |
| TC-42-001 | SPA fallback для маршрутов интерфейсов | #42 | AC-6 | Critical | No | test_spa.py | PASS |
| TC-42-002 | Кэширование статики | #42 | AC-6 | High | No | test_spa.py | PASS |
| TC-42-003 | Пути API не перехватываются | #42 | AC-6 | Critical | No | test_spa.py | PASS |
| TC-42-004 | Защита от обхода каталога | #42 | AC-6, NFR-2 | Critical | No | test_spa.py | PASS |
| TC-42-005 | Отсутствует каталог сборки | #42 | AC-6 | High | No | test_spa.py | PASS |
| TC-43-001 | Состав сервисов, healthcheck, тома (статика) | #43 | AC-7 | Critical | No | test_repo_artifacts.py | PASS |
| TC-43-002 | Сетевая изоляция и безопасность контейнеров | #43 | AC-7, NFR-2 | High | No | test_repo_artifacts.py | PASS |
| TC-43-003 | Запуск стека на Docker, /health по домену | #43 | AC-7 | Critical | No | — (ручной, Linux-хост) | НЕ ВЫПОЛНЕН |
| TC-44-001 | Матрица ОС и состав шагов CI | #44 | AC-8 | Critical | No | test_repo_artifacts.py; PR #47 CI | PASS |
| TC-44-002 | Падение шага делает проверку красной | #44 | AC-8 | High | No | test_repo_artifacts.py | PASS |
| TC-44-003 | Безопасность workflow | #44 | AC-8, NFR-2 | High | No | test_repo_artifacts.py | PASS |
| TC-45-001 | Локальный запуск по README (single) | #45 | AC-9 | Critical | No | — (ручной) | ЧАСТИЧНО (шаги 5–7) |
| TC-45-002 | Раздел scaled и команды проверок совпадают | #45 | AC-9 | High | No | test_repo_artifacts.py | PASS |
| TC-45-003 | README без секретов и адресов заведения | #45 | AC-9, NFR-2 | High | No | test_repo_artifacts.py | PASS |

Итого: 37 TC (PASS 34; не выполнены 2: TC-41-006, TC-43-003; частично 1: TC-45-001).

## Cross-reference между историями (#6)
- #37 → #38 (Settings → фабрика), #42 (`FRONTEND_DIST_DIR`)
- #38 → #39, #40 (реализации интерфейсов)
- #40 → #43 (worker и Redis в compose)
- #41 → #42 (сборка раздаётся backend-ом)
- #42, #43 → #45 (README описывает запуск)
- #37, #41 → #44 (CI выполняет их проверки)

## Feature #7 — Модель данных v1 и миграции Alembic

Прогон 2026-10-12: локально (Windows, PostgreSQL 16 как служба, база `ai_waiter_test`) `uv run pytest -q` — 1017 passed, 3 skipped (тесты настоящего Redis), все db-тесты PASS; CI по PR #57 — 5/5 зелёные. Финальный прогон G5 2026-10-13 после тестов tester (`test_seed_loader.py`, новые тесты в `test_seed.py` и `db/test_seed.py`), без параллельных прогонов на той же базе: полный `pytest -q --cov=app` — 1053 passed, 3 skipped, 1 xfailed (`db/test_seed.py::test_seed_rerun_when_demo_table_has_another_open_visit`, дефект #58, TC-53-007), 70 с, покрытие `app` 100%; без db (`-m "not db"`) — 830 passed, 3 skipped, 22 с, покрытие `app` 100%. Ошибки подготовки CLI-тестов `db/test_seed.py` в промежуточном прогоне были вызваны параллельной работой с той же базой и в финальном прогоне не воспроизвелись.

| TC ID | Title | Feature | AC | Priority | E2E Automated | Авто (unit/static) | Прогон |
|-------|-------|---------|-----|----------|---------------|--------------------|--------|
| TC-48-001 | Цикл Alembic upgrade / downgrade на пустой базе | #48 | AC-1 | Critical | No | db/test_alembic.py, test_alembic_setup.py, test_migrations_offline.py; CI PR #57 | PASS |
| TC-48-002 | Фикстура db: SELECT 1 и откат данных теста | #48 | AC-1 | Critical | No | db/test_db_fixture.py | PASS |
| TC-48-003 | Нет или ошибка DATABASE_URL — ошибка без пароля | #48 | AC-1 | High | No | test_config.py, test_db_session.py, db/test_db_fixture.py | PASS |
| TC-48-004 | Guard тестовой базы: TEST_DATABASE_URL и *_test | #48 | AC-1, FR-3 | Critical | No | test_db_guards.py, test_config.py, test_repo_artifacts.py | PASS |
| TC-48-005 | Базовый класс: имена ограничений, Money, timestamptz, UUIDv7 | #48 | AC-1, FR-2, NFR-2 | High | No | test_db_base.py, test_ids.py; ruff DTZ | PASS |
| TC-48-006 | Async-сессия и движок: ленивость, пул, закрытие | #48 | AC-1, FR-2 | Medium | No | test_db_session.py, test_container.py, test_lifespan.py, test_qa_coverage_gaps.py | PASS |
| TC-48-007 | Alembic без строк подключения и секретов | #48 | AC-1, NFR-5 | High | No | test_alembic_setup.py, test_config.py, test_repo_artifacts.py | PASS |
| TC-48-008 | Локальный запуск на Windows с PostgreSQL-службой | #48 | AC-1, NFR-5 | Medium | No | — (ручной) | PASS (ручной, 2026-10-12) |
| TC-49-001 | qr_token уникален на всю таблицу | #49 | AC-2 | Critical | No | db/test_tenants_tables.py, test_migrations_offline.py, test_models_metadata.py | PASS |
| TC-49-002 | external_id стола уникален внутри заведения | #49 | AC-2 | Critical | No | db/test_tenants_tables.py | PASS |
| TC-49-003 | Значения по умолчанию tenants и tables | #49 | AC-2 | High | No | db/test_tenants_tables.py, test_models_metadata.py | PASS |
| TC-49-004 | CHECK tenants, halls, tables | #49 | AC-2 | High | No | db/test_tenants_tables.py, db/test_migrations.py | PASS |
| TC-49-005 | Стол не ссылается на зал другого заведения | #49 | AC-2, NFR-1 | Critical | No | db/test_tenant_isolation.py, test_models_metadata.py | PASS |
| TC-49-006 | downgrade -1 удаляет три таблицы ревизии | #49 | AC-2 | High | No | db/test_migrations.py, test_migrations_offline.py | PASS |
| TC-49-007 | RESTRICT при удалении, перевыпуск qr_token | #49 | AC-2 | Medium | No | db/test_tenants_tables.py | PASS |
| TC-50-001 | Дубли external_id и тарифа внутри заведения | #50 | AC-3 | Critical | No | db/test_menu.py, test_models_metadata.py | PASS |
| TC-50-002 | Та же позиция в другом заведении принимается | #50 | AC-3 | High | No | db/test_menu.py | PASS |
| TC-50-003 | Скрытие не удаляет данные; RESTRICT для строк кассы | #50 | AC-3, NFR-7 | Critical | No | db/test_menu.py, test_models_metadata.py | PASS |
| TC-50-004 | CHECK меню: цена, острота, вес, путь фото | #50 | AC-3 | High | No | db/test_menu.py, db/test_migrations.py, test_models_metadata.py | PASS |
| TC-50-005 | Межарендные ссылки в меню отклоняются | #50 | AC-3, NFR-1 | Critical | No | db/test_tenant_isolation.py, test_models_metadata.py | PASS |
| TC-50-006 | allergens_verified = false по умолчанию, meta 1:1 | #50 | AC-3, AI-2 | High | No | db/test_menu.py, test_models_metadata.py | PASS |
| TC-50-007 | Деньги NUMERIC(10,2), сортировка sort_key | #50 | AC-3, NFR-2 | High | No | db/test_menu.py, db/test_schema_invariants.py, test_models_metadata.py | PASS |
| TC-50-008 | Справочник 14 аллергенов ЕС | #50 | AC-3 | Medium | No | test_models_metadata.py, db/test_menu.py | PASS |
| TC-51-001 | Не более одного открытого визита на стол | #51 | AC-4 | Critical | No | db/test_visits.py, test_migrations_offline.py, test_models_metadata.py | PASS |
| TC-51-002 | Корзина: комментарии и цена на момент добавления | #51 | AC-4 | Critical | No | db/test_visits.py, test_models_metadata.py | PASS |
| TC-51-003 | Количество в корзине 1..99 | #51 | AC-4 | High | No | db/test_visits.py | PASS |
| TC-51-004 | CHECK визита: status, lang, closed_by | #51 | AC-4 | High | No | db/test_visits.py, db/test_migrations.py, test_models_metadata.py | PASS |
| TC-51-005 | Сообщения: роль, токены, cost_usd, обезличивание | #51 | AC-4, NFR-8 | High | No | db/test_visits.py, db/test_schema_invariants.py, test_models_metadata.py | PASS |
| TC-51-006 | Межарендные ссылки визитов и корзины отклоняются | #51 | AC-4, NFR-1 | Critical | No | db/test_tenant_isolation.py | PASS |
| TC-51-007 | CASCADE для визита, RESTRICT для стола и меню | #51 | AC-4 | Medium | No | db/test_visits.py, db/test_migrations.py, test_models_metadata.py | PASS |
| TC-52-001 | Повтор idempotency_key отклоняется | #52 | AC-5, NFR-3 | Critical | No | db/test_orders.py, test_models_metadata.py | PASS |
| TC-52-002 | Ровно 8 статусов жизненного цикла | #52 | AC-5 | Critical | No | db/test_orders.py, db/test_migrations.py, test_order_status.py, test_models_metadata.py | PASS |
| TC-52-003 | Подтверждение и отклонение: обязательные поля | #52 | AC-5 | High | No | db/test_orders.py | PASS |
| TC-52-004 | Снимок названия и цены в позициях заказа | #52 | AC-5 | Critical | No | db/test_orders.py | PASS |
| TC-52-005 | order_events только дописывается (триггер) | #52 | AC-5 | Critical | No | db/test_orders.py, db/test_migrations.py, test_migrations_offline.py | PASS |
| TC-52-006 | Позиции заказа: CHECK, уникальность, removed_by_staff | #52 | AC-5 | High | No | db/test_orders.py | PASS |
| TC-52-007 | События заказа: CHECK типа, исполнителя, статусов | #52 | AC-5 | High | No | db/test_orders.py, db/test_migrations.py, test_models_metadata.py | PASS |
| TC-52-008 | Межарендные ссылки заказов отклоняются | #52 | AC-5, NFR-1 | Critical | No | db/test_tenant_isolation.py | PASS |
| TC-52-009 | Правила удаления и индексы ленты заказов | #52 | AC-5 | Medium | No | db/test_orders.py, db/test_migrations.py, test_models_metadata.py | PASS |
| TC-53-001 | Первый запуск: полный демонстрационный набор | #53 | AC-6 | Critical | No | db/test_seed.py, test_seed.py | PASS |
| TC-53-002 | Повторный запуск не меняет число строк | #53 | AC-6 | Critical | No | db/test_seed.py, test_seed_loader.py | PASS |
| TC-53-003 | Отказ при APP_ENV=prod | #53 | AC-6, NFR-6 | Critical | No | test_seed.py | PASS |
| TC-53-004 | Нет IP-адресов, секретов и реальных данных | #53 | AC-6, NFR-6 | High | No | test_seed.py | PASS |
| TC-53-005 | Ошибки запуска без раскрытия пароля; чужие строки | #53 | AC-6 | High | No | db/test_seed.py, test_seed.py, test_seed_loader.py | PASS |
| TC-53-006 | AZ-названия аллергенов и блюд проверены носителем | #53 | AC-6 | Low | No | — (ручной) | НЕ ВЫПОЛНЕН |
| TC-53-007 | Повторный сид при закрытом демо-визите и другом открытом визите | #53 | AC-6 | Medium | No | db/test_seed.py | PASS (дефект #58 исправлен) |
| TC-54-001 | Цикл миграций и alembic check в CI до pytest | #54 | AC-7 | Critical | No | test_repo_artifacts.py, db/test_alembic.py; CI PR #57 | PASS |
| TC-54-002 | alembic check без расхождений | #54 | AC-7 | Critical | No | db/test_alembic.py, test_migrations_offline.py; CI PR #57 | PASS |
| TC-54-003 | Инвариант tenant_id на реальной схеме | #54 | AC-7, NFR-1 | Critical | No | db/test_schema_invariants.py, test_models_metadata.py | PASS |
| TC-54-004 | Инвариант NUMERIC(10,2), исключение cost_usd | #54 | AC-7, NFR-2 | Critical | No | db/test_schema_invariants.py, test_models_metadata.py, test_db_base.py | PASS |
| TC-54-005 | Инвариант timestamptz | #54 | AC-7, NFR-2 | High | No | db/test_schema_invariants.py, test_models_metadata.py; ruff DTZ | PASS |
| TC-54-006 | Любое нарушение делает джоб красным | #54 | AC-7 | High | No | db/test_schema_invariants.py, test_repo_artifacts.py, test_db_guards.py | PASS (статика и детекторы) |
| TC-54-007 | Локальная проверка миграций на Windows по README | #54 | AC-7 | Medium | No | — (ручной); db/test_alembic.py | PASS (ручной, 2026-10-12) |
| TC-56-001 | БД доступна — 200, database: ok | #56 | AC | Critical | No | db/test_health_db.py, test_health.py | PASS |
| TC-56-002 | БД недоступна — 503, database: fail без деталей | #56 | AC | Critical | No | db/test_health_db.py, test_health.py | PASS |
| TC-56-003 | Таймаут проверки БД не больше 2 с | #56 | AC | High | No | test_health.py, test_db_session.py | PASS |
| TC-56-004 | /health не обращается к БД | #56 | AC (Tech Notes) | High | No | test_health.py | PASS |

Итого по #7: 57 TC (PASS 55, из них ручных 2 — TC-48-008, TC-54-007; FAIL 1 — TC-53-007, известный дефект сида #58, тест `xfail(strict=True)` добавлен tester 2026-10-13; не выполнен 1 — TC-53-006, ручной).


## Cross-reference между историями (#7)
- #48 → все stories #7 (база моделей, Alembic, фикстура `db`, guard `*_test`); #48 → #56 (`Database.ping()`)
- #49 → #50, #51 (составные FK на `tenants`, `tables`); #49 → #53 (уникальность `qr_token` защищает чужие столы)
- #50 → #51, #52 (`price_at_add`, `price_at_order`, RESTRICT на `menu_items`)
- #51 → #52 (заказ принадлежит визиту)
- #49–#52 → #54 (инварианты `tenant_id`, `NUMERIC(10,2)`, `timestamptz` на реальной схеме), #53 (сид наполняет все таблицы)
- #37 → #56 (TC-37-005 расширен проверкой БД); #44 → #54 (шаги CI)

## Feature #8 — Импорт меню из CSV/XLSX

Прогон qa-lead 2026-10-19 (ветка `feature/8-menu-import`): полный `uv run pytest -q --cov=app` — 1669 passed, 3 skipped (тесты настоящего Redis), покрытие `app` 100%. Код #67 — в репозитории кассы, TC ручные (приёмка пользователем на реальном меню; данные заведения в репозиторий не попадают). Полные списки тестов — в `docs/test-cases/feature-61-menu-snapshot.md` … `feature-67-restoran-export.md`.

| TC ID | Title | Feature | AC | Priority | E2E Automated | Авто (unit/static) | Прогон |
|-------|-------|---------|-----|----------|---------------|--------------------|--------|
| TC-61-001 | Три ошибки снимка за одну проверку | #61 | AC-1 | Critical | No | test_menu_snapshot.py::test_ac61_three_errors_at_once, ::test_shape_error_does_not_hide_cross_errors_of_other_items | PASS |
| TC-61-002 | Корректный снимок без ошибок, хеш не зависит от порядка | #61 | AC-1 | Critical | No | test_menu_snapshot.py::test_ac61_valid_snapshot_of_same_size_has_no_issues, ::test_ac61_valid_snapshot_hash_does_not_depend_on_item_order; test_menu_sync_runs.py | PASS |
| TC-61-003 | MoneyStr — Decimal без float | #61 | AC-1, NFR-4 | Critical | No | test_money.py | PASS |
| TC-61-004 | Ошибки формы, дубли, тарифы, пустой снимок, лимиты | #61 | AC-1, FR-1 | High | No | test_menu_snapshot.py | PASS |
| TC-61-005 | Валюта заведения и нулевая цена | #61 | AC-1, FR-1 | High | No | test_menu_snapshot.py, test_menu_sync_runs.py | PASS |
| TC-61-006 | Управляющие символы и санитизация отчёта | #61 | AC-1, NFR-6 | High | No | test_menu_snapshot.py | PASS |
| TC-61-007 | Отчёт: не больше 100 проблем | #61 | FR-3 | Medium | No | test_menu_snapshot.py | PASS |
| TC-61-008 | Границы импортов menu_sync и schemas | #61 | NFR-10 | Medium | No | test_import_boundaries.py | PASS |
| TC-62-001 | Сценарий AC: обновление, скрытие, возврат, создание | #62 | AC-2 | Critical | No | db/test_menu_sync_apply.py::test_ac62_scenario | PASS |
| TC-62-002 | Изоляция заведений при применении | #62 | AC-2, NFR-1 | Critical | No | db/test_menu_sync_apply.py::test_ac62_scenario, ::test_load_current_menu_is_tenant_scoped, ::test_unknown_tenant | PASS |
| TC-62-003 | План: создание, обновление, скрытие, возврат | #62 | AC-2, FR-2 | High | No | test_menu_plan.py, db/test_menu_sync_apply.py | PASS |
| TC-62-004 | Цены тарифов и наличие | #62 | FR-2, NFR-2 | High | No | test_menu_plan.py, db/test_menu_sync_apply.py::test_prices_and_availability | PASS |
| TC-62-005 | «Всё или ничего», пустой снимок, чужая валюта | #62 | FR-3 | Critical | No | db/test_menu_sync_apply.py | PASS |
| TC-62-006 | Защита от массового скрытия | #62 | FR-3 | High | No | test_menu_plan.py, db/test_menu_sync_apply.py::test_mass_hide_rejected_and_allowed | PASS |
| TC-62-007 | Пробный прогон dry_run | #62 | FR-3 | High | No | db/test_menu_sync_apply.py::test_dry_run_writes_nothing_and_matches_real_counts | PASS |
| TC-62-008 | Advisory lock занят — MenuSyncBusyError | #62 | FR-3, NFR-3 | High | No | db/test_menu_sync_apply.py::test_busy_lock_raises | PASS |
| TC-62-009 | Снимок максимального размера | #62 | ADR-8.2, NFR-5 | Medium | No | db/test_menu_sync_apply.py::test_max_size_snapshot_fits_bind_parameter_limit | PASS |
| TC-62-010 | 2 000 позиций не дольше 10 с на сервере пилота | #62 | NFR-5 | Medium | No | — (ручной) | НЕ ВЫПОЛНЕН |
| TC-63-001 | Тот же снимок в другом порядке — unchanged | #63 | AC-3 | Critical | No | db/test_menu_sync_runs.py::test_ac63_same_snapshot_in_other_order_is_unchanged | PASS |
| TC-63-002 | Хеш снимка канонический | #63 | AC-3, FR-1 | High | No | test_menu_sync_runs.py | PASS |
| TC-63-003 | force, изменённый снимок, другой источник | #63 | FR-4 | High | No | db/test_menu_sync_runs.py | PASS |
| TC-63-004 | rejected журналируется после отката | #63 | FR-4, NFR-6 | High | No | db/test_menu_sync_runs.py | PASS |
| TC-63-005 | Пробный прогон не пишет журнал | #63 | FR-4 | Medium | No | db/test_menu_sync_runs.py::test_dry_run_is_not_journaled | PASS |
| TC-63-006 | В журнал — только имя файла | #63 | NFR-6 | High | No | db/test_menu_sync_runs.py, test_menu_sync_runs.py | PASS |
| TC-63-007 | Журнал и хеш изолированы по заведению | #63 | NFR-1 | Critical | No | db/test_menu_sync_runs.py::test_journal_and_hash_are_tenant_scoped | PASS |
| TC-63-008 | Ревизия 0005 и CHECK menu_sync_runs | #63 | FR-4 | High | No | db/test_menu_sync_runs.py, test_migrations_offline.py, db/test_migrations.py, db/test_alembic.py, test_models_metadata.py | PASS |
| TC-64-001 | Ошибки строк 4 и 7, снимка нет | #64 | AC-4 | Critical | No | test_menu_csv.py::test_ac64_errors_with_rows_and_no_snapshot; test_menu_sync_cli.py::test_ac64_check_reports_row_4_price_and_row_7_duplicate_of_row_3 | PASS |
| TC-64-002 | Исправленный файл — Decimal("4.50") | #64 | AC-4 | Critical | No | test_menu_csv.py::test_ac64_fixed_file_gives_snapshot_with_decimal_comma | PASS |
| TC-64-003 | Синтетический пример, разделители, BOM | #64 | AC-4, FR-5 | High | No | test_menu_csv.py | PASS |
| TC-64-004 | Кодировка, кавычки, пустой файл, формат | #64 | FR-5 | High | No | test_menu_csv.py | PASS |
| TC-64-005 | Заголовок: регистр, #-колонки, неизвестные | #64 | FR-5 | High | No | test_menu_csv.py | PASS |
| TC-64-006 | Деньги в ячейках CSV | #64 | AC-4, NFR-4 | High | No | test_menu_csv.py | PASS |
| TC-64-007 | external_id и категории | #64 | AC-4 | High | No | test_menu_csv.py | PASS |
| TC-64-008 | Колонка is_available | #64 | FR-5 | High | No | test_menu_csv.py | PASS |
| TC-64-009 | Физические номера строк, сбор всех ошибок | #64 | AC-4, FR-5 | Medium | No | test_menu_csv.py | PASS |
| TC-64-010 | Лимиты файла и защита от DoS | #64 | ADR-8.2, NFR-6 | High | No | test_menu_csv.py | PASS |
| TC-64-011 | Управляющие символы в ячейках | #64 | NFR-6 | High | No | test_menu_csv.py | PASS |
| TC-64-012 | Граница импортов пакета files | #64 | NFR-10 | Medium | No | test_import_boundaries.py | PASS |
| TC-64-013 | Описание формата в README | #64 | FR-5 | Low | No | — (ручной) | PASS (ручной, 2026-10-19) |
| TC-65-001 | Лист Menu, снимок совпадает с CSV-примером | #65 | AC-5 | Critical | No | test_menu_xlsx.py::test_ac65_menu_sheet_matches_csv_example | PASS |
| TC-65-002 | Выбор листа: --sheet, menu, первый | #65 | AC-5 | High | No | test_menu_xlsx.py, test_menu_sync_cli.py::test_check_xlsx_with_sheet | PASS |
| TC-65-003 | Числа в ячейках: external_id, цены, наличие | #65 | AC-5, NFR-4 | High | No | test_menu_xlsx.py | PASS |
| TC-65-004 | Даты, ошибки Excel, формулы | #65 | FR-6 | High | No | test_menu_xlsx.py | PASS |
| TC-65-005 | Заголовок и пустые листы | #65 | FR-6 | Medium | No | test_menu_xlsx.py | PASS |
| TC-65-006 | Не-XLSX, макросы, повреждённая книга | #65 | FR-6, NFR-6 | Critical | No | test_menu_xlsx.py, test_menu_csv.py | PASS |
| TC-65-007 | XXE и XML-бомбы (defusedxml) | #65 | NFR-6 | Critical | No | test_menu_xlsx.py::test_defusedxml_is_used_by_openpyxl, ::test_xml_entities_are_rejected | PASS |
| TC-65-008 | Zip-бомба и лимиты архива | #65 | NFR-6 | Critical | No | test_menu_xlsx.py | PASS |
| TC-65-009 | DoS по CPU: строки, ячейки, элементы XML | #65 | NFR-6 | High | No | test_menu_xlsx.py | PASS |
| TC-65-010 | Книга только для чтения и закрывается; openpyxl изолирован | #65 | NFR-10 | Medium | No | test_menu_xlsx.py, test_import_boundaries.py | PASS |
| TC-66-001 | dry-run → applied → unchanged, код 0 | #66 | AC-6 | Critical | No | db/test_menu_sync_cli.py::test_ac66_dry_run_then_applied_then_unchanged; test_menu_sync_cli.py | PASS |
| TC-66-002 | check без БД и .env | #66 | FR-7 | High | No | test_menu_sync_cli.py | PASS |
| TC-66-003 | Ошибки в данных — код 2, rejected | #66 | AC-6, FR-7 | Critical | No | db/test_menu_sync_cli.py, test_menu_sync_cli.py | PASS |
| TC-66-004 | Массовое скрытие и --allow-mass-hide | #66 | FR-3, FR-7 | High | No | db/test_menu_sync_cli.py::test_mass_hide_needs_explicit_permission | PASS |
| TC-66-005 | Блокировка занята — код 3 | #66 | AC-6, NFR-3 | High | No | db/test_menu_sync_cli.py::test_busy_lock_is_exit_3; test_menu_sync_cli.py::test_import_busy_is_exit_3 | PASS |
| TC-66-006 | Ошибки окружения и аргументов — код 1 | #66 | FR-7 | High | No | db/test_menu_sync_cli.py::test_unknown_tenant_is_exit_1; test_menu_sync_cli.py | PASS |
| TC-66-007 | Пароль БД и путь не раскрываются | #66 | NFR-6 | Critical | No | db/test_menu_sync_cli.py::test_wrong_password_is_not_shown; test_menu_sync_cli.py | PASS |
| TC-66-008 | --json и кодировка консоли | #66 | FR-7, NFR-7 | Medium | No | test_menu_sync_cli.py | PASS |
| TC-66-009 | Нет колонки is_available — наличие не меняется | #66 | FR-5 | High | No | db/test_menu_sync_cli.py::test_missing_availability_column_keeps_availability | PASS |
| TC-66-010 | APP_ENV=prod, точка входа, справка | #66 | FR-7 | Medium | No | test_menu_sync_cli.py | PASS |
| TC-66-011 | README: команда, коды выхода, расписание | #66 | FR-7 | Low | No | — (ручной) | PASS (ручной, 2026-10-19) |
| TC-67-001 | Выгрузка проходит check с кодом 0 | #67 | AC-7 | Critical | No | ручной; формат со стороны ядра — test_menu_csv.py::test_pos_export_format_from_tz_a2_is_accepted, test_menu_sync_cli.py::test_check_accepts_pos_export_format | PASS (ручной, приёмка пользователем) |
| TC-67-002 | price_vip = 0 → пусто | #67 | AC-7 | High | No | — (ручной; unit-тесты в репозитории кассы) | PASS (ручной) |
| TC-67-003 | disabled = 1 → позиции нет в файле | #67 | AC-7 | High | No | — (ручной; unit-тесты в репозитории кассы) | PASS (ручной) |
| TC-67-004 | Цена 7.999999 → 8.00 | #67 | AC-7 | High | No | — (ручной; unit-тесты в репозитории кассы) | PASS (ручной) |
| TC-67-005 | Файл в local-data/, вне git | #67 | AC-7, NFR-9 | Critical | No | — (ручной, git check-ignore) | PASS (ручной, 2026-10-19) |
| TC-67-006 | Выгрузка импортируется: dry-run, import | #67 | AC-7, FR-8 | High | No | — (ручной) | PASS (ручной, приёмка пользователем: 362 позиции) |
| TC-67-007 | В ядре нет кода под кассу | #67 | ADR-8.8, NFR-9 | High | No | — (ручной) | PASS (ручной, 2026-10-19) |

Итого по #8: 67 TC (PASS 66, из них ручных 9 — TC-64-013, TC-66-011, TC-67-001…TC-67-007; не выполнен 1 — TC-62-010, производительность на сервере пилота, автотеста нет).

### AC → TC → автотест (#8)

| AC | Story | TC | Автотест |
|----|-------|----|----------|
| AC-1 | #61 | TC-61-001, TC-61-002 | test_menu_snapshot.py::test_ac61_three_errors_at_once, ::test_ac61_valid_snapshot_of_same_size_has_no_issues, ::test_ac61_valid_snapshot_hash_does_not_depend_on_item_order |
| AC-2 | #62 | TC-62-001, TC-62-002 | db/test_menu_sync_apply.py::test_ac62_scenario |
| AC-3 | #63 | TC-63-001 | db/test_menu_sync_runs.py::test_ac63_same_snapshot_in_other_order_is_unchanged |
| AC-4 | #64 | TC-64-001, TC-64-002 | test_menu_csv.py::test_ac64_errors_with_rows_and_no_snapshot, ::test_ac64_fixed_file_gives_snapshot_with_decimal_comma; test_menu_sync_cli.py::test_ac64_check_reports_row_4_price_and_row_7_duplicate_of_row_3 |
| AC-5 | #65 | TC-65-001 | test_menu_xlsx.py::test_ac65_menu_sheet_matches_csv_example |
| AC-6 | #66 | TC-66-001, TC-66-003, TC-66-005 | db/test_menu_sync_cli.py::test_ac66_dry_run_then_applied_then_unchanged, ::test_parse_errors_are_rejected_and_journaled, ::test_busy_lock_is_exit_3 |
| AC-7 | #67 | TC-67-001…TC-67-006 | ручная приёмка (код в репозитории кассы); формат выгрузки в ядре — test_menu_csv.py::test_pos_export_format_from_tz_a2_is_accepted, test_menu_sync_cli.py::test_check_accepts_pos_export_format |

Всего в матрице на конец #8: 161 TC (с #60 — 171, см. ниже).

## Cross-reference между историями (#8)
- #61 → #62 (снимок применяется), #63 (`snapshot_hash`), #64, #65 (разбор файла даёт `MenuSnapshot`)
- #62 → #63 (журнал добавляет шаги 3 и 6 в `apply_menu_snapshot`), #66 (CLI вызывает сервис)
- #64 → #65 (общий `format.py`), #66 (`check`/`import` печатают отчёт), #67 (формат выгрузки)
- #66 → #67 (проверка выгрузки `check` и `import`)
- #7: #50 → #62 (таблицы меню, RESTRICT, составные FK); #54 → #63 (инварианты схемы для `menu_sync_runs`); #53 → #63 (после сида журнал пуст)

## Защита от демо-данных в боевой базе — story #60

Прогон 2026-10-28: локально (Windows, PostgreSQL 16, тестовая база `*_test`) `pytest -q tests/test_seed_guard.py tests/test_seed.py tests/db/test_seed.py` — 56 passed, без пропусков; ручной TC-60-010 — PASS. AC-2 и E-7…E-9 относятся к #71 и здесь не учитываются.

| TC ID | Title | Feature | AC | Priority | E2E Automated | Авто (unit/static) | Прогон |
|-------|-------|---------|-----|----------|---------------|--------------------|--------|
| TC-60-001 | Только другое заведение — код 2, демо не создаётся | #60 | AC-1, E-4 | Critical | No | db/test_seed.py::test_cli_refuses_base_with_other_tenant, ::test_guard_on_other_only_base; test_seed.py::test_foreign_tenants_are_refused_with_exit_code_2; test_seed_guard.py | PASS |
| TC-60-002 | Демо и другое заведение — код 2, демо-строки не обновлены | #60 | AC-1, E-3 | Critical | No | db/test_seed.py::test_cli_refuses_demo_plus_other_without_updating_demo, ::test_guard_on_demo_and_other_base | PASS |
| TC-60-003 | Пустая база — сид загружает данные, код 0 | #60 | E-1, FR-2 | High | No | db/test_seed.py::test_guard_on_empty_base, ::test_cli_twice_commits_same_data; test_seed_guard.py | PASS |
| TC-60-004 | Только демо — повторный запуск идемпотентен | #60 | E-2, FR-2 | High | No | db/test_seed.py::test_guard_on_demo_only_base, ::test_cli_twice_commits_same_data, ::test_seed_twice_gives_same_row_counts | PASS |
| TC-60-005 | APP_ENV=prod — отказ до подключения, проверка не выполняется | #60 | E-5, FR-2 | Critical | No | test_seed.py::test_prod_refusal_happens_before_target_check, ::test_exit_prod_forbidden_is_alias_of_exit_forbidden | PASS |
| TC-60-006 | Ошибка БД при проверке — код 1 без пароля | #60 | E-6, NFR-1 | High | No | test_seed.py::test_database_error_in_target_check_is_exit_1_without_password; test_seed_guard.py::test_database_error_is_not_caught; db/test_seed.py::test_cli_without_schema_fails_with_hint, ::test_cli_wrong_password_is_not_shown | PASS (известное ограничение NFR-1: `describe_error` маскирует только пароль, LOW с #7) |
| TC-60-007 | Сообщение отказа без строки подключения, идентификаторов и названий | #60 | AC-1, NFR-1 | Critical | No | test_seed_guard.py::test_refusal_text_is_russian_without_connection_details; test_seed.py::test_foreign_tenants_are_refused_with_exit_code_2; db/test_seed.py | PASS |
| TC-60-008 | Проверка — первый запрос транзакции, загрузчик не вызывается | #60 | FR-1, NFR-4 | High | No | test_seed.py::test_target_check_runs_before_apply_seed_in_same_session; test_seed_guard.py::test_foreign_tenants_exist_query | PASS |
| TC-60-009 | Одинаково в single/scaled, Windows/Linux | #60 | E-10, NFR-2 | Medium | No | test_seed.py::test_foreign_tenants_refusal_is_same_in_both_modes; test_seed_guard.py, test_seed.py (матрица CI); db/test_seed.py (backend-services) | PASS (локально Windows; Linux — по CI PR) |
| TC-60-010 | Ручной: сид с --database-url базы с другим заведением (Windows, single) | #60 | AC-1, E-4, E-6, E-10 | Critical | No | — (ручной) | PASS (ручной, 2026-10-28) |

Итого по #60: 10 TC (PASS 10, из них ручной 1 — TC-60-010).

### AC → TC → автотест (#60)

| AC | Story | TC | Автотест |
|----|-------|----|----------|
| AC-1 | #60 | TC-60-001, TC-60-002, TC-60-007, TC-60-010 | db/test_seed.py::test_cli_refuses_base_with_other_tenant, ::test_cli_refuses_demo_plus_other_without_updating_demo; test_seed.py::test_foreign_tenants_are_refused_with_exit_code_2; test_seed_guard.py::test_refusal_text_is_russian_without_connection_details |

Всего в матрице: 171 TC.

## Cross-reference между историями (#60)
- #53 → #60: TC-53-003 (отказ при `APP_ENV=prod`) сохраняется — TC-60-005; замечание security review #53 из Notes TC-53-003 закрыто TC-60-001, TC-60-002, TC-60-010; идемпотентность TC-53-002 — TC-60-004; ошибки запуска TC-53-005 — TC-60-006
- #60 ↔ #71: независимые проверки (сид смотрит на целевую базу; приложение в prod сообщает о неготовности); гонку сида (ADR-60.1) ловит #71
