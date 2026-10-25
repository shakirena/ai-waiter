# Architectural Decisions

*Только решения, влияющие на 2+ stories. Дописывает architect или developer. Базовые правила проекта — в CLAUDE.md, здесь не дублируются.*

---

<!--
## DEC-001: {название}

**Decision:** …
**Reason:** …
**Applies to:** …
**Revisit when:** …
-->

## DEC-001: Композиция режимов single/scaled через Container

**Decision:** Интерфейсы `EventBus`, `TaskScheduler`, `RateLimiter` — в `app/core/{events,scheduler,ratelimit}.py`; реализации — только в `app/core/single/` (память, APScheduler 3.x) и `app/core/scaled/` (Redis, arq). Выбор — `build_container(settings, registry)` по `APP_MODE`, ленивый импорт пакета реализаций. Зависимости в эндпоинтах — через `app/api/deps.py` (`Depends(get_event_bus)` и т. п.) из `app.state.container`. Каналы событий — `tenant_channel(tenant_id, topic)`; ключи лимитов — `rate_key(...)` с `tenant_id` для лимитов по столу. Отложенные задачи в single теряются при рестарте → бизнес-таймеры делать периодическим «подметанием» БД (`@registry.periodic`). Payload задач и событий — JSON-сериализуемый.
**Reason:** ТЗ 8 (один код, два режима); граница проверяется ruff TID251 и `tests/test_import_boundaries.py`.
**Applies to:** #20, #22, #23, #24, #26, #36 и любые stories с реалтаймом, фоновыми задачами, лимитами.
**Revisit when:** замена arq (режим поддержки) или появление второго заведения на одном single-инстансе.

## DEC-002: Конфигурация — pydantic-settings, только env

**Decision:** Все настройки — поля `Settings` (`app/core/config.py`) без префикса; секреты — `SecretStr`; каждая новая переменная добавляется одновременно в `Settings` и `.env.example`. Остальной код получает настройки через `Container`, не через `get_settings()`. `DATABASE_URL` — схема `postgresql+asyncpg://`, обязательным становится в #7.
**Reason:** ТЗ 9.2, NFR-4, NFR-8.
**Applies to:** все stories.
**Revisit when:** —

## DEC-003: Префиксы маршрутов и раздача фронтенда

**Decision:** SPA API — `/api` (без версии), Integration API — `/integration/v1`, WebSocket официанта — `/ws`, служебные — `/health`. Backend раздаёт `frontend/dist` в обоих режимах (`app/web/spa.py`, SPA fallback); зарезервированные префиксы (`RESERVED_PREFIXES`) не отдают `index.html`. Новый backend-префикс добавляется в `RESERVED_PREFIXES`, `BACKEND_PREFIXES` в `frontend/vite.config.ts` (proxy + navigateFallbackDenylist). Same-origin, CORS не включается.
**Reason:** ТЗ 9.1 (статика тем же процессом), одно поведение в single и scaled.
**Applies to:** все backend- и frontend-stories.
**Revisit when:** отдача статики через CDN/Caddy в #36.

## DEC-004: uv + pyproject; asyncpg; Windows-совместимость

**Decision:** Python-зависимости — `backend/pyproject.toml` + `uv.lock` (uv), extra `scaled` для redis/arq. Драйвер PostgreSQL — asyncpg (без смены event loop policy на Windows; psycopg запрещён ruff). Только `pathlib` (ruff PTH), только aware-datetime (ruff DTZ), `encoding="utf-8"` явно, `.gitattributes eol=lf`. Тесты с PostgreSQL/Redis — маркеры `db`/`scaled`, только Linux-джоб CI; unit-тесты scaled — через fakeredis.
**Reason:** ТЗ 9.1–9.2: нативный запуск на Windows Server 2019 и CI на двух ОС.
**Applies to:** все backend-stories, #7, #30, #36.
**Revisit when:** —

## DEC-005: Развёртывание scaled — deploy/.env, сети backend/edge, доверие к прокси

**Decision:** Конфигурация compose — `deploy/.env` (копия `.env.example`, рядом с `deploy/docker-compose.yml`): из неё и подстановка `${...}`, и `env_file` для api/worker. `APP_MODE=scaled`, `APP_ENV=prod`, `DATABASE_URL`, `REDIS_URL`, `PUBLIC_BASE_URL=https://${PUBLIC_DOMAIN}` задаёт сам compose. Две сети: `backend` (postgres, redis, api, worker) и `edge` (caddy, api) с явной подсетью `EDGE_SUBNET`; uvicorn запускается с `--proxy-headers --forwarded-allow-ips=${EDGE_SUBNET}` — X-Forwarded-* принимаются только от caddy. Healthcheck worker — `arq --check`, интервал записи ключа здоровья — `HEALTH_CHECK_INTERVAL` (60 с) в `app/core/scaled/worker.py`. Новый сервис на образе приложения (например, migrate в #7) наследует якорь `x-app`.
**Reason:** AC-7, ADR-6, раздел Security arch doc: наружу только caddy, адрес клиента нельзя подделать из внутренних контейнеров.
**Applies to:** #43, #45 (README), #7 (migrate), #32, #36.
**Revisit when:** переход на оркестратор или внешний балансировщик перед caddy.

## DEC-006: Ключи UUIDv7 и мультиарендность составными FK

**Decision:** Все PK — `uuid`, значение UUIDv7 из `app.db.ids.new_id()` (запасной `server_default gen_random_uuid()`); `tenant_id uuid NOT NULL` во всех таблицах заведения; у родителей `UNIQUE (tenant_id, id)`, ссылки внутри заведения — составные FK `(tenant_id, x_id)`; бизнес-уникальности — `(tenant_id, …)`, глобально уникален только `tables.qr_token`. Ссылки на персонал (`*_staff_id`) — uuid; FK на `staff_users` добавляет #19. Статусы — `text` + `CHECK`, значения из `app/models/enums.py`. Имена ограничений — `NAMING_CONVENTION` из `app/db/base.py`.
**Reason:** docs/arch/feature-7-data-model.md ADR-7.1–7.3, 7.7, 7.8: order_id Integration API — UUID; гостю не видны перебираемые ID; слияние БД пилота с VPS; БД сама отвергает межарендные ссылки; RLS подключается без изменения таблиц.
**Applies to:** #8–#36, все stories с новыми таблицами (#16 connectors, #19 staff_users, #22 waiter_calls, #25 reviews).
**Revisit when:** включение RLS на этапе SaaS (#36) — отдельный ADR.

## DEC-007: Сессии БД и транзакции

**Decision:** `Container.database: Database` (lazy async engine asyncpg, `expire_on_commit=False`); в эндпоинтах — `SessionDep` из `app/api/deps.py`; commit — явно в сервисе (заказ коммитится до любых вызовов ИИ и уведомлений, NFR-3), без автокоммита в зависимости. Миграции не запускаются при старте приложения: `alembic upgrade head` (scaled — сервис `migrate` в compose, single — шаг установки службы #30). Деньги — `NUMERIC(10,2)`/`Decimal`; исключение — стоимость ИИ `NUMERIC(12,6)`.
**Reason:** ADR-7.4, 7.9, 7.10.
**Applies to:** все backend-stories с БД; #23 (фоновые задачи берут Database из Container), #30, #36.
**Revisit when:** —

## DEC-008: Тесты с PostgreSQL

**Decision:** db-тесты — `backend/tests/db/`, маркер `db`, подключение только из `TEST_DATABASE_URL` (имя БД оканчивается на `_test`); нет переменной — skip локально, ошибка при `CI=true`. Схема — `alembic upgrade head` один раз за сессию (синхронная фикстура), изоляция — транзакция + `join_transaction_mode="create_savepoint"` с откатом. Инварианты metadata и офлайн-SQL миграций — unit-тесты без БД (идут и на Windows).
**Reason:** ADR-7.11; Windows-джоб CI без PostgreSQL.
**Applies to:** все stories с db-тестами.
**Revisit when:** параллельный запуск тестов (pytest-xdist) — нужна БД на воркер.

## DEC-009: CHECK из кода и шаблон тестов модели данных

**Decision:** Текст CHECK строится только построителями `app/models/checks.py` (`sql_in`, `sql_match`, `sql_not_match`, `sql_length`, `sql_between`, `sql_text_array`) из перечислений и шаблонов `app/models/enums.py`; короткое имя CHECK = имя колонки (`ck_<table>_<column>`), составные — по смыслу (`ck_menu_item_meta_weight`). Новая таблица/ревизия обязана дополнить: `EXPECTED_TABLES`, `EXPECTED_CHECKS`, `NUMERIC_EXCEPTIONS` в `tests/test_models_metadata.py`; `REVISION_TABLES` в `tests/test_migrations_offline.py` и `tests/db/test_migrations.py`; `ENUM_CHECKS` (CHECK «IN» ↔ перечисление) в `tests/db/test_migrations.py`; межарендные FK — в `tests/db/test_tenant_isolation.py`. db-тесты ограничений — через `tests/db/factories.py:expect_violation` (SAVEPOINT + имя нарушенного ограничения). Ревизия — autogenerate с ручной проверкой, комментарии autogenerate удаляются, docstring на русском. Колонки в DDL: `id`, `tenant_id`, …, `created_at`, `updated_at` (`sort_order` в миксинах); `sort_key` — `TEXT COLLATE "C"`.
**Reason:** ADR-7.2, 7.3, 7.8, 7.13: alembic check не сравнивает CHECK; одинаковые проверки для всех ревизий 0001–0004.
**Applies to:** #51, #52, #53, #54 и будущие таблицы (#16, #19, #22, #25).
**Revisit when:** —

## DEC-010: Инварианты схемы проверяются на реальной БД

**Decision:** `tests/db/test_schema_invariants.py` после `upgrade head` читает схему из `pg_catalog`/`information_schema`: в каждой таблице, кроме `tenants` и `alembic_version`, `tenant_id NOT NULL` — первая колонка полного (не частичного) индекса (обычного, UNIQUE или PK); денежные колонки ADR-7.4 и любые другие `numeric` — `numeric(10,2)`, кроме `NUMERIC_EXCEPTIONS` (`messages.cost_usd`, `menu_item_meta.weight_amount`); `real`/`double precision`/`money` запрещены; нет `timestamp without time zone`, все `*_at` — `timestamptz`. Если PK таблицы не начинается с `tenant_id` и составного UNIQUE с ним нет, нужен индекс `Index(None, "tenant_id", <ключ>)` (так сделано для `menu_item_prices`, `menu_item_meta`). Новая денежная колонка — в `MONEY_COLUMNS`; не-денежная `numeric` — в `NUMERIC_EXCEPTIONS` обоих тестов (метаданных и схемы) с обоснованием. CI (`backend-services`) перед pytest выполняет CLI `alembic upgrade head` / `downgrade base` / `upgrade head` / `check`.
**Reason:** NFR-1 spec #7, ADR-7.3, ADR-7.4, ADR-7.10; модельный тест не ловит миграцию, разошедшуюся с моделью в том, что не видит `alembic check`.
**Applies to:** все будущие таблицы и ревизии (#16, #19, #22, #25).
**Revisit when:** появится законная таблица заведения без `tenant_id` или колонка времени без часового пояса.

## DEC-011: Единый путь синхронизации меню — `app/menu_sync`

**Decision:** Любой источник меню (файл CSV/XLSX в #8, `PUT /integration/v1/menu` в #16) превращается в Pydantic-снимок `MenuSnapshot` (форма тела `PUT /menu`, ТЗ 4.4) и применяется только через `app.menu_sync.service.apply_menu_snapshot` в одной транзакции под `pg_try_advisory_xact_lock(8, hashtext(tenant_id::text))`; занят → `MenuSyncBusyError` (CLI код 3, API 409/503). Политика «всё или ничего»: любая ошибка — ничего не пишется, отчёт `MenuSyncReport` со списком `SyncIssue`. Пропавшие из снимка категории и позиции → `is_hidden`, вернувшиеся → `is_hidden=false`; тарифы, которых нет в снимке, удаляются; `is_available=None` — не менять; `menu_item_meta`/`menu_item_allergens` не трогаются; валюта ≠ валюте заведения → отказ всего снимка; ядро не округляет деньги. `PUT /stoplist` (#16) и ручной стоп-лист (#28) берут тот же lock. EventBus-событий о синхронизации нет (CLI — отдельный процесс): меню гостя и ИИ читают БД, без кеша в памяти процесса. Границы: `app/menu_sync/files` без SQLAlchemy, `openpyxl` только в `files/xlsx_reader.py`, пакет не импортирует `fastapi`/`app.api`.
**Reason:** docs/arch/feature-8-menu-import.md ADR-8.1–8.4, 8.6; ТЗ 4.2 (файловый импорт — вид коннектора), INT-1, INT-2.
**Applies to:** #61 (снимок, `check_snapshot`), #62 (`plan_menu_sync`, `apply_menu_snapshot`, lock), #64, #65 (`files`, границы), #66 (CLI); #16 (`PUT /menu`, `PUT /stoplist`), #10, #11, #12 (скрытые/недоступные позиции при оформлении), #28.
**Revisit when:** появится кеш меню в процессе или частичные (дельта) обновления меню.

## DEC-012: Журнал `menu_sync_runs` — источник хеша и времени синхронизации меню

**Decision:** Таблица `menu_sync_runs` (ревизия `0005`, владелец — #63; #62 работает без журнала, #63 добавляет пропуск по хешу и запись журнала без смены сигнатуры `apply_menu_snapshot`): `source` (`file`/`connector`), `source_ref` (имя файла без пути), `status` (`applied`/`unchanged`/`rejected`), `snapshot_hash` (SHA-256 канонического снимка), `started_at`/`finished_at`, `counts`/`issues` jsonb. Пропуск по хешу (INT-1) — сравнение с последним `applied`/`unchanged` заведения любого источника; `unchanged` тоже журналируется (для INT-4/FR-20). Отклонённые снимки журналируются отдельной транзакцией; пробный прогон — нет. Уточняет ADR-7.7: `connectors.last_menu_hash`/`last_menu_sync_at` не создаются, #16 добавляет `menu_sync_runs.connector_id` (составной FK). Очистка старых строк — #23.
**Reason:** ADR-8.5; у файлового импорта нет ключа/записи коннектора, а FR-20 нужна история ошибок любого источника.
**Applies to:** #63, #66, #16, #23 (алерт `menu_stale_alert_min`, очистка), #29 (FR-20 в админке).
**Revisit when:** пользователь не утвердит уточнение ADR-7.7 (открытый вопрос 1 arch #8).

## DEC-013: Деньги в Pydantic-схемах — `app.schemas.money.MoneyStr`

**Decision:** Денежные поля API и снимков — `MoneyStr` (`Annotated[Decimal, …]` из `app/schemas/money.py`, story #61): на входе `str`/`Decimal`/`int`, `float` (JSON-число) отвергается, ≤ 2 знаков после точки без округления, 0…99999999.99; в JSON — строка с двумя знаками (`"8.50"`). Не путать с `app.db.base.Money` (тип колонки `NUMERIC(10,2)`).
**Reason:** CLAUDE.md «Деньги», ADR-7.4 («общий тип Money появляется в #10/#12» — появляется раньше, в #8).
**Applies to:** #61 (вводит тип), #64/#65 (деньги из файла), #10, #12, #16, #17 и любые схемы с деньгами.
**Revisit when:** дробные количества/цены за вес (открытый вопрос 4 #7).

## DEC-014: Демо-данные и боевая база — проверка по содержимому БД

**Decision:** Политика «демо-заведение `DEMO_TENANT_ID` только в базе разработки» проверяется по содержимому базы, а не только по `APP_ENV` машины. Запросы — только в `app/seed/guard.py` (`foreign_tenants_exist`, `ensure_seed_target`, `demo_tenant_exists`; `DEMO_TENANT_ID` — из `app.seed.data`, не дублируется). (1) `python -m app.seed`: после отказа при `APP_ENV=prod` и загрузки `Settings`, первым запросом транзакции сида (READ COMMITTED, без `LOCK TABLE`) — есть заведение кроме демо → `ForeignTenantsError`, откат, код 2 (`EXIT_FORBIDDEN`; 2 = «запрещено политикой», 1 = ошибка конфигурации/БД); проверка в CLI, не в `apply_seed`. (2) Приложение при `APP_ENV=prod`: `DemoDataMonitor` (`app/api/demo_data.py`, `app.state.demo_data_monitor`) — один раз в lifespan после `start_container` (для лога; таймаут 2 с, старт не прерывает) и на каждом `/health/ready` параллельно с `database`; демо найдено или результат неизвестен → 503 `not_ready`; лог только при смене состояния, без `exc_info`, ошибки через `describe_error`. Тело `/health/ready` не меняется (ключа `demo_data` нет — не подсказывать, что демо-токены действуют; ждёт подтверждения пользователя). Процесс в prod при демо не завершается.
**Reason:** docs/arch/feature-60-demo-data-guard.md ADR-60.1–60.3; arch #6 «недоступная зависимость не роняет процесс»; в `single` readiness никто не опрашивает, в `scaled` compose/Caddy смотрят на `/health`.
**Applies to:** #60, #71; story гостевого входа по QR (рекомендация: отклонять `DEMO_TENANT_ID` при `APP_ENV=prod`); #30/G6 (чек-лист `APP_ENV=prod`); любые будущие проверки политик в `/health/ready`.
**Revisit when:** пользователь выберет отдельный ключ в `checks` (открытый вопрос 1 arch #60), появится оркестратор, снимающий трафик по readiness, или флаг `--force` для сида.
