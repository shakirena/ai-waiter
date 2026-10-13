# Test Case Traceability Matrix

Обновлено: 2026-10-13. Feature #6 «Каркас проекта» (stories #37–#45, прогон 2026-10-02) и feature #7 «Модель данных v1 и миграции Alembic» (stories #48–#54, #56, прогон 2026-10-12, финальный прогон G5 2026-10-13). Столбец «Авто» — где тест выполняется автоматически (для #7 пути относительно `backend/tests/`, `db/` — тесты с маркером `db`, нужен PostgreSQL); «Прогон» — результат на дату прогона.

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

Всего в матрице: 94 TC.

## Cross-reference между историями (#7)
- #48 → все stories #7 (база моделей, Alembic, фикстура `db`, guard `*_test`); #48 → #56 (`Database.ping()`)
- #49 → #50, #51 (составные FK на `tenants`, `tables`); #49 → #53 (уникальность `qr_token` защищает чужие столы)
- #50 → #51, #52 (`price_at_add`, `price_at_order`, RESTRICT на `menu_items`)
- #51 → #52 (заказ принадлежит визиту)
- #49–#52 → #54 (инварианты `tenant_id`, `NUMERIC(10,2)`, `timestamptz` на реальной схеме), #53 (сид наполняет все таблицы)
- #37 → #56 (TC-37-005 расширен проверкой БД); #44 → #54 (шаги CI)
