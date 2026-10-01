# Feature #6: Каркас проекта (backend, frontend, CI, режимы single/scaled)

## Обзор
Каркас репозитория, на котором строятся все задачи этапа 1 и далее: `backend/` (FastAPI), `frontend/` (React PWA), интерфейсы `EventBus`, `TaskScheduler`, `RateLimiter` с реализациями для режимов `single` (один процесс, без Redis, Windows Server 2019 без Docker) и `scaled` (Redis, arq, Docker Compose на VPS), конфигурация через переменные окружения, CI на Linux и Windows, инструкция запуска. Код один, режим выбирается переменной `APP_MODE` (ТЗ раздел 8). Модель данных и миграции в эту фичу не входят (задача #7).

## Functional Requirements
- FR-1 (ТЗ раздел 8): `backend/` содержит приложение FastAPI, `pyproject.toml` с ruff и pytest, эндпоинт `GET /health` (статус и режим). Story #37.
- FR-2 (ТЗ раздел 8, 9.2): все настройки читаются только из переменных окружения; `.env.example` перечисляет каждую переменную без секретов. Некорректный `APP_MODE` или отсутствие обязательной переменной прерывает запуск с понятной ошибкой. Story #37.
- FR-3 (ТЗ раздел 8): код приложения работает с шиной событий, планировщиком задач и rate-limit только через интерфейсы `EventBus`, `TaskScheduler`, `RateLimiter`; реализация выбирается по `APP_MODE`. Story #38.
- FR-4 (ТЗ раздел 8, 9.1): режим `single` реализован в памяти процесса и на APScheduler, без Redis. Story #39.
- FR-5 (ТЗ раздел 8, 9.3): режим `scaled` имеет заготовки на Redis pub/sub, arq (точка входа worker-а) и Redis rate-limit. Story #40.
- FR-6 (ТЗ раздел 8): `frontend/` — React + Vite + TypeScript + Tailwind, маршруты `/t/:token`, `/staff`, `/admin`, PWA-манифест и service worker. Story #41.
- FR-7 (ТЗ 9.1): в режиме `single` процесс backend раздаёт собранный frontend (SPA fallback), не перехватывая пути API. Story #42.
- FR-8 (ТЗ 9.3): `deploy/docker-compose.yml` для `scaled`: api, worker, postgres, redis, caddy. Story #43.
- FR-9 (ТЗ 9.2): GitHub Actions выполняют линтер и тесты backend и frontend на Linux и Windows. Story #44.
- FR-10 (ТЗ 9.1, 9.2): README описывает локальный запуск и проверки. Story #45.

## Non-Functional Requirements
- NFR-1 Переносимость (ТЗ NFR-8, 9.2): никаких абсолютных путей, IP-адресов и ОС-специфики в коде; тесты проходят на Linux и Windows.
- NFR-2 Безопасность (ТЗ NFR-4): секреты только в окружении, без значений по умолчанию; `.env` в `.gitignore`; в репозитории нет IP-адресов, ключей, данных заведения; ai-waiter в режиме `single` слушает `127.0.0.1` по умолчанию; контейнеры без root.
- NFR-3 Производительность интерфейса (ТЗ NFR-2): mobile-first вёрстка, code splitting по маршрутам, работоспособность на ширине 360 px.
- NFR-4 Наблюдаемость (ТЗ NFR-6): структурированные (JSON) логи с первого дня.
- NFR-5 Ресурсы (ТЗ 9.1a): режим `single` — один процесс Python, ориентир 300–500 МБ RAM.
- NFR-6 Качество: ruff и pytest без ошибок, покрытие нового кода стремится к ≥ 95%, unit-тесты укладываются в 2 минуты.
- NFR-7 Изоляция от Redis: `redis`, `arq`, `apscheduler` импортируются только внутри пакета реализаций.

## Acceptance Criteria (Given / When / Then)
### AC-1 (story #37)
**Given** в чистой копии репозитория установлены зависимости `backend/` (Python 3.12) и заданы переменные из `.env.example`
**When** выполняются `ruff check .`, `pytest -q` и запускается `uvicorn app.main:app`, затем выполняется `GET /health`
**Then** ruff и pytest завершаются без ошибок, а `/health` отвечает `200` с JSON, где есть `status: ok` и текущий `mode` (`single` или `scaled`); приложение не стартует с понятной ошибкой, если обязательная переменная не задана или `APP_MODE` имеет недопустимое значение

### AC-2 (story #38)
**Given** каркас backend (story A) запущен и определён `APP_MODE`
**When** приложение стартует и запрашивает `EventBus`, `TaskScheduler`, `RateLimiter` через фабрику зависимостей
**Then** фабрика возвращает реализацию, соответствующую `APP_MODE`, а неизвестное значение режима приводит к ошибке старта; код за пределами пакета реализаций не импортирует `redis`, `arq` и `apscheduler` напрямую (проверяется тестом на импорты)

### AC-3 (story #39)
**Given** приложение запущено с `APP_MODE=single` без Redis в окружении
**When** подписчик слушает канал, затем в канал публикуется событие, планируется задача через 1 секунду и делается больше запросов, чем допускает лимит
**Then** подписчик получает событие, задача выполняется один раз через ~1 секунду, а запрос сверх лимита получает отказ с временем до сброса окна; при остановке приложения планировщик и подписки закрываются без зависших задач

### AC-4 (story #40)
**Given** приложение запущено с `APP_MODE=scaled` и заданным `REDIS_URL`, доступен тестовый Redis (или его in-memory-замена в юнит-тестах)
**When** выполняются публикация события, постановка задачи в очередь и запросы к RateLimiter
**Then** событие доставляется подписчику другого экземпляра через Redis pub/sub, задача попадает в очередь arq и обрабатывается worker-ом, а счётчик лимита общий для всех экземпляров; без `REDIS_URL` приложение в режиме `scaled` не стартует с понятной ошибкой

### AC-5 (story #41)
**Given** в `frontend/` выполнен `npm ci`
**When** выполняются `npm run lint`, `npm run test -- --run`, `npm run build`, затем открываются маршруты `/t/demo`, `/staff` и `/admin` в собранном приложении
**Then** все три команды завершаются без ошибок, каждый маршрут показывает свою заглушку-страницу, сборка содержит `manifest.webmanifest` (name, icons, `display: standalone`, `start_url`) и service worker, а вёрстка работает на ширине 360 px

### AC-6 (story #42)
**Given** выполнена сборка `frontend/dist`, приложение запущено с `APP_MODE=single` и `FRONTEND_DIST_DIR`, указывающим на неё
**When** клиент запрашивает `/t/demo`, `/staff`, `/assets/<файл>` и `/api-несуществующий-путь` под `/api`
**Then** маршруты интерфейсов возвращают `index.html` (SPA fallback), статические файлы отдаются с заголовками кэширования, пути под `/api`, `/integration` и `/health` не перехватываются и отвечают как API; при отсутствии каталога сборки приложение стартует и пишет предупреждение

### AC-7 (story #43)
**Given** на Linux-хосте установлен Docker, рядом с `deploy/docker-compose.yml` лежит `.env`, созданный из `.env.example`, и задан домен
**When** выполняется `docker compose -f deploy/docker-compose.yml up -d --build`
**Then** запускаются сервисы api, worker, postgres, redis и caddy, у каждого есть healthcheck, `GET https://{домен}/health` отвечает `200`, а данные postgres и медиафайлы лежат в именованных томах

### AC-8 (story #44)
**Given** в репозитории есть `.github/workflows/ci.yml` и открыт pull request
**When** запускается workflow с матрицей `ubuntu-latest` и `windows-latest`
**Then** на обеих ОС выполняются `ruff check` и `pytest` (Python 3.12) в `backend/` и `npm ci`, `lint`, `test`, `build` (Node LTS) в `frontend/`, с кэшем зависимостей, а падение любого шага на любой ОС делает проверку красной

### AC-9 (story #45)
**Given** чистая машина (Windows или Linux) с установленными Python 3.12 и Node LTS, клонированный репозиторий
**When** разработчик выполняет шаги раздела «Локальный запуск» из README для режима `single`
**Then** backend отвечает на `/health`, frontend открывается в браузере, а раздел «Режим scaled» описывает запуск через `docker compose` и команды проверки (`ruff`, `pytest`, `npm run lint/test/build`), совпадающие с фактическими скриптами

## User Stories
| Story | Title | Size | Priority | Blocked by |
|-------|-------|------|----------|------------|
| #37 | Backend: каркас FastAPI, настройки из окружения, /health, .env.example | M | High | - |
| #38 | Интерфейсы EventBus, TaskScheduler, RateLimiter с выбором реализации по режиму | S | High | #37 |
| #39 | Режим single: EventBus в памяти, APScheduler, RateLimiter в памяти | M | High | #38 |
| #40 | Режим scaled: заготовки Redis pub/sub, arq, Redis RateLimiter | M | Medium | #38 |
| #41 | Frontend: каркас React, Vite, TypeScript, Tailwind с PWA-манифестом | M | High | - |
| #42 | Раздача собранного frontend процессом backend в режиме single | S | High | #37, #41 |
| #43 | Docker Compose для режима scaled: api, worker, postgres, redis, caddy | M | Medium | #37, #40, #41 |
| #44 | GitHub Actions: линтер, тесты backend, frontend на Linux, Windows | M | High | #37, #41 |
| #45 | README: инструкция локального запуска, режимы single, scaled | S | Medium | #37, #42, #43 |

Порядок: A и E независимы и стартуют первыми; B после A; C и D после B параллельно; F после A и E; H после A и E; G после A, D и E; I последней.

## Out of Scope
- Модель данных, Alembic-миграции, подключение к PostgreSQL (#7).
- Бизнес-эндпоинты, авторизация, tenant-логика, Integration API.
- ИИ-диалог и функции Claude.
- Реальные экраны гостя, официанта и админки.
- Установка службы Windows (WinSW/NSSM), Cloudflare Tunnel, бэкапы, Sentry.
- Публикация Docker-образов и деплой; E2E-тесты.
