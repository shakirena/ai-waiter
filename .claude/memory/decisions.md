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
