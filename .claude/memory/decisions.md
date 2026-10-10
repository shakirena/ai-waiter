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
