# Architecture: Feature #6 — Каркас проекта (backend, frontend, CI, режимы single/scaled)

**Issue:** #6 · **ТЗ:** разделы 6 (NFR-2, NFR-4, NFR-6, NFR-8), 8 (стек, режимы), 9 (размещение и перенос), 4.4 (базовый путь Integration API)
**Spec:** `docs/specs/feature-6-project-scaffold.md` (пишет analyst)
**Смежные issues:** #7 (модель данных и Alembic), #20 (WebSocket + EventBus в деле), #23 (фоновые задачи), #26 (rate-limit), #30 (служба Windows), #32 (наблюдаемость), #36 (перенос на VPS)

Каркас задаёт границы, в которые встраиваются все следующие stories: композицию режимов, конфигурацию, раскладку репозитория, раздачу фронтенда, CI. Бизнес-логики здесь нет.

---

## ADR-1. Композиция режимов `single` / `scaled` через фабрику по конфигурации

**Контекст.** ТЗ, раздел 8: один код, два режима. `single` — один процесс uvicorn на Windows Server 2019 без Docker и без Redis; `scaled` — несколько процессов api, отдельный worker, Redis. Код приложения обращается только к интерфейсам `EventBus`, `TaskScheduler`, `RateLimiter` (CLAUDE.md, «Архитектурные правила»).

**Решение.**

1. Интерфейсы (ABC) и общие типы — в `app/core/`: `events.py` → `Event`, `tenant_channel`, `EventBus`; `scheduler.py` → `TaskRegistry`, `PeriodicTask`, `TaskScheduler`; `ratelimit.py` → `RateLimitResult`, `rate_key`, `RateLimiter`. Эти модули не импортируют сторонних библиотек очередей/кэшей. Интерфейсы также содержат `ping()` (EventBus, RateLimiter — для `/health/ready`), `RateLimiter.reset()`, `TaskScheduler.cancel()`. Общая проверка JSON-сериализуемости payload событий и задач (только `dict` со строковыми ключами, строгий JSON, не более 1 МиБ) — `app/core/payload.py` (`ensure_json_object`); используется и в `single`, и в `scaled`.
2. Реализации — в двух пакетах реализаций (spec AC-2, NFR-7):
   - `app/core/single/`: `InMemoryEventBus`, `InProcessTaskScheduler` (APScheduler 3.x, `AsyncIOScheduler`), `InMemoryRateLimiter`;
   - `app/core/scaled/`: `RedisEventBus`, `ArqTaskScheduler`, `RedisRateLimiter`, `connection.py` (ленивые клиенты Redis/arq с таймаутом подключения, JSON-сериализатор задач arq вместо pickle), `worker.py` с `WorkerSettings` для arq. `WorkerSettings` собирается при первом обращении (модульный `__getattr__`, `build_worker_settings(settings, registry)`), чтобы импорт модуля не читал окружение.
3. `app/core/container.py`: `build_container(settings, registry) -> Container` — единственное место, где читается `settings.app_mode` для выбора реализаций. Пакет реализаций импортируется лениво внутри своей ветки: в `single` не импортируются `redis`/`arq` (и не нужны установленными), в `scaled` — `apscheduler`.
4. `Container` создаётся в `lifespan` приложения и кладётся в `app.state.container`; эндпоинты получают зависимости через `app/api/deps.py` (`Depends(get_event_bus)` и т. п.). Глобальных синглтонов нет — тесты подставляют свой `Settings`/`Container`.
5. Граница закреплена дважды: `ruff` (`flake8-tidy-imports.banned-api`, `TID251`) запрещает `redis`/`arq` вне `app/core/scaled/**` и `apscheduler` вне `app/core/single/**`; тест `tests/test_import_boundaries.py` (AST-обход `app/`) проверяет то же в pytest (spec AC-2). CI падает при нарушении.
6. Переменная окружения `APP_MODE=single|scaled` (по умолчанию `single`). Для `scaled` обязателен `REDIS_URL` — проверяется валидатором `Settings` при старте.

**Семантика, одинаковая в обоих режимах** (иначе `single` будет скрывать ошибки, которые проявятся на VPS):

| Интерфейс | Контракт |
|---|---|
| `EventBus` | Уведомления «at-most-once», без хранения. Источник истины — БД: после переподключения клиент перечитывает состояние через REST. Канал всегда содержит tenant: `tenant:{tenant_id}:{topic}` (`tenant_channel()`). Payload — JSON-сериализуемый (`Event` — Pydantic-модель, в Redis уходит `model_dump_json()`). Медленный подписчик не блокирует издателя: очередь подписчика ограничена, при переполнении старые события отбрасываются с предупреждением в лог. |
| `TaskScheduler` | Задача — имя из `TaskRegistry` + JSON-сериализуемый `dict` (проверяется в `enqueue` в обоих режимах). Обработчики идемпотентны. Отложенные задачи (`delay`) в `single` живут в памяти и **теряются при перезапуске**, поэтому бизнес-критичные таймеры (эскалации, #23) делаются периодическим «подметанием» по данным БД (`@registry.periodic`), а не одноразовым таймером на каждый заказ. Периодические задачи в `scaled` запускает только worker (arq `cron_jobs`), в `single` — единственный процесс. |
| `RateLimiter` | Фиксированное окно: `hit(key, limit=, window=) -> RateLimitResult(allowed, limit, remaining, retry_after)`. В Redis — `INCR` + `EXPIRE` атомарно; в памяти — словарь с ленивой очисткой и ограничением числа ключей. Ключ собирается `rate_key(scope, *parts)`; для лимитов по столу в ключ входит `tenant_id`. |

**Альтернативы.**
- *Всегда Redis (в т. ч. Redis/Memurai на Windows).* Отклонено: ТЗ прямо требует `single` без Redis; Memurai — лишняя служба на сервере кассы.
- *`typing.Protocol` вместо ABC.* Protocol удобнее для утиной типизации, но ABC даёт общие no-op `start()/stop()` и ошибку при создании неполной реализации. Выбран ABC.
- *DI-фреймворк (dependency-injector и т. п.).* Избыточно для трёх зависимостей; `Depends` FastAPI + `app.state` хватает.
- *APScheduler 4.x.* На момент решения нестабилен; 3.x — зрелый, работает на Windows.

**Последствия.**
- В `single` нельзя запускать несколько процессов uvicorn: in-memory шина и лимиты не разделяются между процессами. Валидатор `Settings` отклоняет `APP_MODE=single` при `API_WORKERS>1`; `python -m app` в `single` всегда запускает один процесс.
- arq находится в режиме поддержки; если его придётся заменить (например, на taskiq/saq), меняется только `app/core/scaled/scheduler.py` и `worker.py`.
- Unit-тесты `scaled`-реализаций используют `fakeredis` (dev-зависимость, работает на Windows) — spec AC-4; лежат в отдельных файлах `tests/test_scaled_*.py` (общие тестовые двойники — `tests/doubles.py`, `tests/fake_redis.py`). Тесты с настоящим Redis (`tests/test_scaled_redis.py`) помечены `@pytest.mark.scaled` и пропускаются, если не задан `REDIS_URL`; идут только в Linux-джобе CI с сервисом Redis.
- Недоступность Redis при старте не роняет процесс: `start_container` логирует ошибку компонента и продолжает, о неготовности сообщает `/health/ready` (503). Остановка — в обратном порядке, ошибка одного компонента не мешает остальным.

---

## ADR-2. Конфигурация — только переменные окружения (pydantic-settings)

**Контекст.** ТЗ 9.2 и NFR-4/NFR-8: конфигурация только в env (`.env`), одинаковая для Windows и Docker; секреты не в коде.

**Решение.**
- `app/core/config.py`: класс `Settings(BaseSettings)`, без префикса имён. Источники по приоритету: переменные окружения процесса → `.env` в текущем каталоге → `../.env` (корень репозитория при запуске из `backend/`). Файл `.env` не коммитится; в репозитории — `.env.example` в корне. Пустое значение («`ПЕРЕМЕННАЯ=`») считается незаданным. Для Docker Compose (`scaled`) файл конфигурации — `deploy/.env` (копия `.env.example`, см. ADR-6); внутрь контейнера он попадает как `env_file`, а не как `.env` в каталоге backend.
- Секреты (`DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `SENTRY_DSN`) — `SecretStr`: не попадают в `repr`, логи и трассировки.
- `DATABASE_URL` без значения по умолчанию (нет «дефолтного пароля» в публичном репозитории); схема — строго `postgresql+asyncpg://`. В каркасе он **необязателен**: подключение к PostgreSQL вне scope #6 (spec, Out of Scope), а локальный запуск по README должен работать без PostgreSQL (spec AC-9). Обязательным его делает #7 вместе с движком SQLAlchemy.
- Пути (`MEDIA_DIR`, `FRONTEND_DIST_DIR`) — `pathlib.Path`, по умолчанию относительные. Код не содержит абсолютных путей; абсолютный путь допустим только как значение переменной окружения на конкретном сервере.
- Модель ИИ и её параметры (`AI_MODEL`, далее — в #11/#15) — только из env.
- `get_settings()` кэшируется (`lru_cache`) и используется только в `create_app()`/`__main__`; остальной код получает настройки через `Container`.

| Переменная | Тип / по умолчанию | Назначение |
|---|---|---|
| `APP_MODE` | `single` \| `scaled`, `single` | Режим (ADR-1) |
| `APP_ENV` | `dev` \| `test` \| `prod`, `dev` | В `prod` выключается `/docs`, если не задано `DOCS_ENABLED` |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Адрес прослушивания для `python -m app`. В `single` — только loopback (`127.0.0.1`, `::1`, `localhost`; ТЗ 9.1), снаружи через туннель |
| `API_WORKERS` | `1` | Число процессов api; в `single` допустимо только `1` |
| `DATABASE_URL` | `SecretStr`, необязателен до #7 | `postgresql+asyncpg://…` |
| `REDIS_URL` | `SecretStr`, обязателен при `scaled` | `redis://…` |
| `PUBLIC_BASE_URL` | URL, обязателен при `APP_ENV=prod` | Внешний адрес — всегда домен (QR-ссылки, CORS не нужен) |
| `SERVE_FRONTEND` | `true` | Раздавать сборку фронтенда этим процессом (ADR-3) |
| `FRONTEND_DIST_DIR` | не задан → `<repo>/frontend/dist`, вычисляется от расположения пакета | Каталог сборки Vite |
| `MEDIA_DIR` | `media` | Локальный том медиафайлов (слой хранения — позже) |
| `DOCS_ENABLED` | не задан → `true` вне `prod` | Swagger/OpenAPI (нужен для Integration API) |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | Структурированные логи (NFR-6); `console` — для разработки |
| `ANTHROPIC_API_KEY`, `AI_MODEL` | необязательны в каркасе | Задействуются в #11 |
| `SENTRY_DSN` | необязателен | #32 |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `PUBLIC_DOMAIN`, `EDGE_SUBNET` | только `deploy/.env` | Не поля `Settings`: читаются только Docker Compose (подстановка `${...}`, ADR-6). `API_WORKERS` в compose — по умолчанию 2 |

Для `scaled` compose сам задаёт `APP_MODE=scaled`, `APP_ENV=prod`, `DATABASE_URL`, `REDIS_URL`, `PUBLIC_BASE_URL=https://${PUBLIC_DOMAIN}`, `MEDIA_DIR` (значения из `deploy/.env` для них перекрываются). `VITE_API_PROXY_TARGET` — только dev server Vite (`frontend/.env.local`), не переменная backend.

**Альтернативы.** YAML/TOML-файлы конфигурации — отклонено (ТЗ 9.2). `python-dotenv` + ручной разбор — pydantic-settings уже даёт валидацию и типы.

**Последствия.** Любая новая настройка появляется одновременно в `Settings` и в `.env.example` (проверка на ревью). Settings валидируется при старте — ошибка конфигурации видна сразу, а не при первом запросе.

---

## ADR-3. Фронтенд раздаётся backend-ом (StaticFiles + SPA fallback) в обоих режимах

**Контекст.** ТЗ 9.1: в `single` статика раздаётся тем же процессом (на сервере заведения нет nginx/Caddy — только cloudflared). Одно приложение React с маршрутами `/t/{token}`, `/staff`, `/admin` (client-side routing).

**Решение.**
- `app/web/spa.py`: `mount_spa(app, dist_dir)` монтирует `SPAStaticFiles` (наследник `starlette.staticfiles.StaticFiles`) на `/` **последним**, после всех роутеров.
- Fallback: если файл не найден и путь не начинается с зарезервированных префиксов — отдаётся `index.html` (200). Зарезервированные префиксы: `/api`, `/integration`, `/health`, `/ws`, `/docs`, `/redoc`, `/openapi.json`. Для них неизвестный путь даёт обычный JSON 404 FastAPI, а не HTML (иначе клиенты API и коннекторы получат HTML вместо ошибки).
- Путь с расширением файла (`/foo.png`), которого нет, — 404, а не `index.html`.
- Кэш: `index.html`, `sw.js`, `manifest.webmanifest` — `Cache-Control: no-cache`; `/assets/*` (хешированные имена Vite) — `public, max-age=31536000, immutable`.
- Если `SERVE_FRONTEND=true`, а каталога сборки нет, — предупреждение в лог и API работает без фронтенда (разработка идёт через Vite dev server с proxy).
- В `scaled` используется **тот же** механизм: Docker-образ api содержит собранный фронтенд (multi-stage `deploy/Dockerfile`), Caddy только терминирует TLS и проксирует. Один путь раздачи — одно поведение в обоих режимах.
- API для SPA — префикс `/api` (без версии: клиент и сервер разворачиваются вместе). Integration API — `/integration/v1` (внешние клиенты, версия обязательна, ТЗ 4.4). Реалтайм официанта — `/ws` (#20).
- CORS не включается: фронтенд и API на одном origin; в разработке Vite проксирует `/api`, `/integration`, `/health`, `/ws` на backend.

**Альтернативы.** Caddy раздаёт статику в `scaled` — быстрее на отдачу файлов, но это второй путь с другими заголовками и fallback-правилами; выигрыш для PWA с кэшем Service Worker несущественный. Можно пересмотреть в #36 без изменения кода приложения (`SERVE_FRONTEND=false`).

**Последствия.** На сервере заведения (single) Node.js не нужен: `frontend/dist` собирается в CI или на машине разработчика и поставляется вместе с backend (порядок поставки — #30).

Service Worker (vite-plugin-pwa) не должен перехватывать зарезервированные префиксы: `navigateFallbackDenylist` в `vite.config.ts` совпадает со списком `RESERVED_PREFIXES` в `spa.py`. Любой новый backend-префикс добавляется в оба места.

---

## ADR-4. Менеджер зависимостей Python — uv (pyproject.toml + uv.lock)

**Контекст.** Нужны воспроизводимые установки на Windows Server 2019 (нативно, без Docker), на Linux в Docker и в CI на двух ОС.

**Решение.** `backend/pyproject.toml` (PEP 621, сборка `hatchling`) + `uv.lock` в репозитории.
- Основные зависимости — в `[project.dependencies]`; Redis-стек — extra `scaled` (`redis`, `arq`); инструменты разработки — `[dependency-groups] dev`.
- Команды: `uv sync` (single), `uv sync --extra scaled` (scaled/CI), `uv run pytest`, `uv run ruff check .`.
- Python 3.12 фиксируется в `requires-python` и `.python-version`.

**Почему uv, а не pip + requirements.txt / Poetry.**
- Один бинарник без зависимостей, одинаково ставится на Windows Server 2019 и Linux; может сам поставить Python 3.12 — упрощает #30.
- Кроссплатформенный lock-файл (`uv.lock` фиксирует версии для всех ОС сразу), в отличие от `pip freeze`, который фиксирует окружение одной ОС.
- Официальный `astral-sh/setup-uv` для GitHub Actions с кэшем; установка в разы быстрее pip — важно для матрицы CI.
- Формат стандартный (PEP 621): при необходимости `pip install -e ".[scaled]"` работает без uv — это путь отступления, lock-in нет.
- Poetry отклонён: собственный формат секций, медленнее, на Windows ставится сложнее.

**Последствия.** Разработчики и CI используют `uv`; `uv.lock` генерируется developer-ом при реализации (`uv lock`) и коммитится. В Docker-образе — `uv sync --frozen --no-dev --extra scaled`.

---

## ADR-5. Совместимость с Windows

**Контекст.** `single` работает нативно на Windows Server 2019 (ТЗ 9.1), CI проверяет Windows и Linux (ТЗ 9.2).

**Решение.**
- **Драйвер PostgreSQL — `asyncpg`** (решение для #7; в каркасе зависимостей БД ещё нет). Он работает и с `ProactorEventLoop` (по умолчанию на Windows), и с `SelectorEventLoop`, поэтому **никакой смены event loop policy в коде нет**. `psycopg` (v3) в async-режиме на Windows требует `WindowsSelectorEventLoopPolicy` — это глобальная подмена цикла, влияющая на uvicorn и subprocess; поэтому psycopg не используется. Alembic (#7) работает через async-движок с тем же `asyncpg`.
- `uvloop` не используется явно; `uvicorn[standard]` ставит его только на не-Windows (маркеры окружения), на Windows — стандартный asyncio.
- Пути — только `pathlib.Path`, относительные от расположения пакета или от CWD (ruff `PTH` запрещает `os.path`). Никаких `/tmp`, `C:\`, `~`.
- Нет `fork`, `signal.SIGHUP/SIGUSR*`, `os.getuid`, `fcntl`, `resource`; остановка процесса — через lifespan uvicorn (служба Windows шлёт Ctrl+C/`CTRL_BREAK`).
- Время — только aware-datetime (`datetime.now(UTC)`), ruff `DTZ` запрещает naive. Часовой пояс заведения — из БД, не из ОС.
- Кодировка файлов — явно `encoding="utf-8"` (на Windows по умолчанию cp1251/cp1252). Концы строк — `.gitattributes` (`* text=auto eol=lf`), чтобы `ruff format --check` вёл себя одинаково на обеих ОС.
- Скрипты службы Windows (WinSW/NSSM) — в `deploy/windows/` (issue #30), не в `app/`.

**Последствия.** CI на `windows-latest` запускает те же `ruff` и `pytest`; тесты с PostgreSQL на Windows-раннере не запускаются (сервис-контейнеры GitHub Actions работают только на Linux) — такие тесты помечены `@pytest.mark.db` и идут в Linux-джобе.

---

## ADR-6. Docker Compose для `scaled` и CI

**Compose (`deploy/docker-compose.yml`).**

| Сервис | Образ | Команда | Примечание |
|---|---|---|---|
| `postgres` | `postgres:16` | — | том `pgdata`; healthcheck `pg_isready`; сеть `backend` |
| `redis` | `redis:7-alpine` | `redis-server --appendonly no --save ""` | сеть `backend`, без публикации порта; healthcheck `redis-cli ping` |
| `api` | `deploy/Dockerfile` (multi-stage: node → сборка фронтенда, python → backend) | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-2} --proxy-headers --forwarded-allow-ips=${EDGE_SUBNET}` | `APP_MODE=scaled`; том `media`; healthcheck `GET /health`; сети `backend` и `edge`; порт наружу не публикуется |
| `worker` | тот же образ | `arq app.core.scaled.worker.WorkerSettings` | выполняет задачи и периодические задания; сеть `backend`; healthcheck `arq --check` (ключ здоровья в Redis, интервал `HEALTH_CHECK_INTERVAL` = 60 с в `worker.py`) |
| `caddy` | `caddy:2` | — | порты 80/443 (и 443/udp); `reverse_proxy api:8000`; домен из `PUBLIC_DOMAIN`; сеть `edge`; healthcheck — Admin API `127.0.0.1:2019/config/` |
| `migrate` | тот же образ | `alembic upgrade head` | one-shot; появится в #7 (в каркасе только комментарий); наследует якорь `x-app` |

- Контекст сборки — корень репозитория; конфигурация — **`deploy/.env`** (рядом с compose-файлом): из него и подстановка `${...}`, и `env_file` для api/worker, поэтому `--env-file` не нужен. `DATABASE_URL`/`REDIS_URL` в compose указывают на имена сервисов (`postgres`, `redis`), не на IP. Общие настройки api/worker вынесены в якорь `x-app` (образ `ai-waiter:local`, `no-new-privileges`, `restart: unless-stopped`, `depends_on` с `service_healthy`).
- **Две сети.** `backend` — postgres, redis, api, worker; `edge` — только caddy и api, с явной подсетью `EDGE_SUBNET`. Uvicorn доверяет `X-Forwarded-*` только из `EDGE_SUBNET` (`--forwarded-allow-ips`), поэтому подделать адрес клиента из сети `backend` нельзя. Подсеть администратор выбирает из частных диапазонов так, чтобы она не пересекалась с сетями хоста; значение шаблона — только в `.env.example` и README.
- `0.0.0.0` внутри контейнера — это bind на все интерфейсы контейнера, а не адрес сети; наружу api доступен только через Caddy. Контейнеры api/worker работают не от root (`USER 10001`).
- Бэкапы (NFR-9) — #31.

**CI (`.github/workflows/ci.yml`).**

| Джоб | ОС | Шаги |
|---|---|---|
| `backend` | матрица `ubuntu-latest`, `windows-latest`; Python 3.12; shell — bash на обеих ОС | `uv sync --frozen --extra scaled` → проверка версии Python → `ruff check .` → `ruff format --check .` → `pytest -q -m "not db and not scaled"` |
| `backend-services` | `ubuntu-latest` + сервисы `postgres:16`, `redis:7-alpine` | `pytest -q -m "db or scaled"`; `DATABASE_URL`/`REDIS_URL` задаются в env джоба. Код pytest 5 («тесты не выбраны») считается успехом с notice, остальные ненулевые коды — красная проверка (`continue-on-error` не используется) |
| `frontend` | матрица `ubuntu-latest`, `windows-latest`; Node 22 | `npm ci` → `npm run lint` → `npm run typecheck` → `npm run test -- --run` → `npm run build` |

Триггеры: `push` в `main`, `pull_request`. Секреты в CI не нужны.

---

## ERD

**В каркасе таблиц нет, подключения к БД нет.** Модель данных (ТЗ, раздел 7), движок SQLAlchemy 2 + asyncpg, `app/core/db.py`, `alembic/`, `alembic.ini` и проверка `database` в `/health/ready` — issue #7. Контракт для #7: движок и фабрика сессий добавляются полями в `Container`, `DATABASE_URL` становится обязательным.

---

## API Contracts

| Method | Path | Кто | Request | Response | Ошибки |
|--------|------|-----|---------|----------|--------|
| GET | `/health` | все (без авторизации) | — | `200 {"status": "ok", "mode": "single", "version": "0.1.0"}` | — |
| GET | `/health/ready` | все (без авторизации) | — | `200 {"status": "ready", "checks": {"redis": "skipped"}}` | `503 {"status": "not_ready", "checks": {"redis": "fail"}}` |
| GET | `/{любой путь SPA}` | браузер | — | `200 text/html` (`index.html`) | 404, если путь с расширением и файла нет; 404 JSON для зарезервированных префиксов |

- `/health` — liveness: не трогает БД и Redis, отвечает, пока жив event loop. Используют служба Windows/Docker healthcheck.
- Реализация: `/health` — story #37, `/health/ready` — story #38 (нужен `Container` и `ping()` интерфейсов); оба в `app/api/health.py`.
- `/health/ready` — readiness: в `scaled` — `ping()` шины и rate-limiter-а (Redis `PING`), в `single` — `"skipped"`; #7 добавляет ключ `"database"` (`SELECT 1`). Каждая проверка с таймаутом 2 с. Тело ответа не содержит текстов исключений, строк подключения и хостов — детали только в лог.
- Значения `checks`: `"ok"`, `"fail"`, `"skipped"`. `mode`: `"single"` \| `"scaled"`.
- Время в будущих ответах — ISO 8601 с зоной; деньги — строка `"12.50"` (к `/health` не относится).

TS-типы: `frontend/src/api/types.ts` (`HealthResponse`, `ReadinessResponse`).

---

## События и фоновые задачи

В каркасе **не публикуется ни одно доменное событие и не регистрируется ни одна задача** — появляются только механизмы:

- `Event(type, tenant_id, payload, occurred_at)`, `tenant_channel(tenant_id, topic)` — `app/core/events.py`.
- `TaskRegistry` с декораторами `@registry.task("name")` и `@registry.periodic("name", every_minutes=N)`; единый реестр `app/tasks/__init__.py:registry`. Оба планировщика (`InProcessTaskScheduler`, arq `WorkerSettings`) строятся из одного реестра, поэтому набор задач одинаков в обоих режимах.
- `every_minutes` должен делить 60 или быть кратным 60 и делить 1440 — так интервал однозначно выражается и в APScheduler (`interval`), и в arq (`cron` с набором минут/часов).
- Жизненный цикл: `lifespan` запускает `event_bus.start()` → `rate_limiter.start()` → `scheduler.start()` и останавливает в обратном порядке. В `scaled` api-процессы стартуют `ArqTaskScheduler` только как издателя (enqueue/cancel), периодические задачи выполняет только `worker`.

---

## ИИ

Не затрагивается. В `Settings` зарезервированы `ANTHROPIC_API_KEY` и `AI_MODEL` (модель — только из конфигурации); функций ИИ, промптов и SDK Anthropic в каркасе нет (#11). Функции отправки заказа у ИИ нет и не появляется.

---

## Security

- **Секреты:** только env; `SecretStr` для `DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `SENTRY_DSN`. `.env` в `.gitignore`, `.env.example` — только имена и безопасные заглушки. В репозитории нет IP, доменов заведения, паролей.
- **Сеть:** `single` слушает `127.0.0.1` (ТЗ 9.1); в `scaled` наружу открыт только Caddy (80/443), postgres/redis/api без публикации портов. HTTPS — Cloudflare Tunnel / Caddy (NFR-4).
- **Доверие к прокси:** `python -m app` (single) принимает `X-Forwarded-*` только с loopback (`TRUSTED_PROXY_IPS` в `app/__main__.py`, cloudflared на той же машине); в `scaled` uvicorn в контейнере принимает их только из подсети `edge` (`--forwarded-allow-ips=${EDGE_SUBNET}`), где кроме api находится лишь caddy; Caddy не доверяет входящему `X-Forwarded-For` клиентов. Wildcard (`'*'`) не используется.
- **/health:** без авторизации, но без внутренних деталей (нет текстов ошибок, хостов, версий зависимостей). Версия приложения — открытая информация (репозиторий публичный).
- **SPA fallback:** зарезервированные префиксы не отдают HTML — исключает путаницу типов ответа и «успешный 200» на несуществующий API. `StaticFiles` Starlette защищён от path traversal; `follow_symlink=False`.
- **Мультиарендность:** каналы `EventBus` и ключи `RateLimiter` включают `tenant_id` по контракту (хелперы `tenant_channel`, `rate_key`); подписка официанта на чужой tenant исключается на уровне #20 (tenant берётся из учётной записи, не из запроса).
- **Rate-limit:** интерфейс готов; применение к эндпоинтам — #22, #26.
- **OpenAPI/Swagger:** в `prod` выключены по умолчанию (`DOCS_ENABLED`), включаются явно, если нужна документация Integration API для интеграторов.
- **Заголовки безопасности** (CSP, HSTS) — в Caddy/Cloudflare для `scaled`; для `single` — middleware в #32 или #30 (вне каркаса).
- **Граница Redis:** ruff `TID251` и `test_import_boundaries.py` не дают использовать `redis`/`arq` вне `app/core/scaled/`.

---

## Module Structure (code stubs)

```
.env.example                         # все переменные Settings, без секретов
.gitattributes                       # eol=lf
.github/workflows/ci.yml             # матрица ubuntu+windows: backend и frontend

backend/
  pyproject.toml                     # uv/hatchling, ruff (TID251, PTH, DTZ, ASYNC, S), pytest
  uv.lock                            # генерирует developer (`uv lock`), коммитится
  .python-version                    # 3.12
  app/
    __init__.py                      # __version__
    __main__.py                      # python -m app → uvicorn (single: 1 процесс)
    main.py                          # create_app(settings) + lifespan; ленивый атрибут `app` для `uvicorn app.main:app`
    core/
      config.py                      # Settings, AppMode, AppEnv, get_settings()
      events.py                      # Event, tenant_channel, EventBus (ABC)
      scheduler.py                   # TaskRegistry, PeriodicTask, TaskScheduler (ABC)
      ratelimit.py                   # RateLimitResult, rate_key, RateLimiter (ABC)
      container.py                   # Container, build_container(), start_container/stop_container
      payload.py                     # ensure_json_object: общая проверка JSON-payload событий и задач
      single/                        # ЕДИНСТВЕННОЕ место с apscheduler
        events.py                    # InMemoryEventBus
        scheduler.py                 # InProcessTaskScheduler (APScheduler 3.x)
        ratelimit.py                 # InMemoryRateLimiter
      log.py                         # configure_logging() — JSON/console (не logging.py: не затенять stdlib)
      scaled/                        # ЕДИНСТВЕННОЕ место с redis/arq
        events.py                    # RedisEventBus
        scheduler.py                 # ArqTaskScheduler
        ratelimit.py                 # RedisRateLimiter
        connection.py                # redis_from_url, arq_redis_from_url, serialize_job/deserialize_job (JSON)
        worker.py                    # WorkerSettings для arq (ленивый, build_worker_settings)
    api/
      deps.py                        # get_container, get_app_settings, get_event_bus, get_scheduler, get_rate_limiter
      health.py                      # /health, /health/ready
    web/
      spa.py                         # SPAStaticFiles, mount_spa, RESERVED_PREFIXES
    tasks/
      __init__.py                    # registry = TaskRegistry()
  tests/
    conftest.py                      # settings/app/client/spa_dist фикстуры
    doubles.py, fake_redis.py        # тестовые двойники (в т. ч. fakeredis для scaled)
    test_config.py, test_main.py, test_lifespan.py, test_log.py
    test_container.py, test_interfaces.py
    test_events.py, test_scheduler.py, test_ratelimit.py   # контракт интерфейсов
    test_single_mode.py              # реализации single
    test_scaled_connection.py, test_scaled_events.py, test_scaled_ratelimit.py,
    test_scaled_scheduler.py, test_scaled_worker.py        # реализации scaled на fakeredis
    test_scaled_redis.py             # @pytest.mark.scaled, настоящий Redis (REDIS_URL)
    test_health.py
    test_spa.py
    test_import_boundaries.py        # AST: redis/arq/apscheduler только в пакетах реализаций

frontend/
  package.json                       # scripts: dev, build, preview, lint, typecheck, test, icons; engines node >=22
  public/icons/                      # PWA-иконки 192/512 (генерация: scripts/generate-icons.mjs)
  package-lock.json                  # генерирует developer (`npm install`), коммитится; CI — `npm ci`
  tsconfig.json, tsconfig.app.json, tsconfig.node.json
  vite.config.ts                     # react, tailwind, PWA (manifest), dev proxy
  eslint.config.js
  index.html
  src/
    main.tsx, App.tsx                # маршруты /t/:token, /staff, /admin (заглушки, code splitting)
    pages/                           # GuestPage, StaffPage, AdminPage, NotFoundPage
    components/PlaceholderPage.tsx
    index.css                        # @import "tailwindcss"
    api/types.ts                     # HealthResponse, ReadinessResponse
    api/client.ts                    # getHealth(), ApiError
    App.test.tsx, api/client.test.ts
    test/setup.ts

deploy/
  Dockerfile                         # multi-stage: frontend build → python runtime
  docker-compose.yml                 # postgres, redis, api, worker, caddy; сети backend/edge
  Caddyfile                          # {$PUBLIC_DOMAIN} → reverse_proxy api:8000
  .env                               # не коммитится: копия .env.example для compose (ADR-6)
.dockerignore
```

### Команды (для раздела «Команды» в CLAUDE.md — добавляет developer при реализации)

```bash
# backend
cd backend && uv sync --extra scaled
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
uv run python -m app                          # single, 127.0.0.1:8000
# frontend
cd frontend && npm ci && npm run lint && npm run typecheck && npm run test -- --run && npm run build
npm run dev                                   # Vite с proxy на backend
# scaled (из корня репозитория; cp .env.example deploy/.env и заполнить раздел «Только docker-compose»)
docker compose -f deploy/docker-compose.yml up -d --build
```

> **Пометка doc-sync (2026-10-02, #6).** Раздел приведён в соответствие с реализацией (#37–#45), решения не менялись: `deploy/.env` вместо корневого `.env` для compose; две сети `backend`/`edge` и `--forwarded-allow-ips=${EDGE_SUBNET}`; `/health/ready` реализован в #38; добавлены `core/payload.py`, `core/scaled/connection.py`; тесты scaled — отдельные файлы `test_scaled_*.py`; уточнены сценарии CI и healthcheck-и compose. Решения — `.claude/memory/decisions.md` (DEC-001…DEC-005).
