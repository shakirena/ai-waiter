# AI Waiter

ИИ-официант для ресторанов: гость сканирует QR-код на столе, общается с ботом на азербайджанском или русском, собирает заказ и отправляет его официанту. Официант подтверждает заказ в своей панели, а коннектор передаёт его в кассовую систему заведения.

Продукт не зависит от кассы: любая касса подключается через коннектор по [Integration API](docs/TZ.md#44-integration-api-v1). Первый коннектор — для Yii2-программы «restoran».

## Статус

Каркас проекта готов (issue #6): backend на FastAPI с `/health` и `/health/ready`, интерфейсы `EventBus`, `TaskScheduler`, `RateLimiter` с реализациями для режимов `single` и `scaled`, frontend-заготовка (PWA) с маршрутами-заглушками `/t/{token}`, `/staff`, `/admin`, Docker Compose для режима `scaled` и CI на Linux и Windows.

Бизнес-логики пока нет: модель данных, подключение к PostgreSQL, меню, чат с ИИ, заказы и коннекторы появятся в задачах этапов 1–4.

- Техническое задание: [docs/TZ.md](docs/TZ.md)
- Спецификация каркаса: [docs/specs/feature-6-project-scaffold.md](docs/specs/feature-6-project-scaffold.md)
- Архитектура каркаса (ADR): [docs/arch/feature-6-project-scaffold.md](docs/arch/feature-6-project-scaffold.md)
- Задачи и этапы — в Issues, Milestones и в GitHub Project «AI Waiter».

## Архитектура

```
Гость (QR, PWA) ─┐
Официант (PWA) ──┼──► AI Waiter: FastAPI + Claude API (+ PostgreSQL; Redis только в scaled)
Админ ───────────┘            ▲
                              │ Integration API (исходящие запросы коннектора)
                 ┌────────────┼──────────────┐
          Коннектор Yii2   Коннектор r_keeper   Импорт CSV/XLSX
```

Один код работает в двух режимах, режим выбирается переменной `APP_MODE`:

| | `single` | `scaled` |
|---|---|---|
| Назначение | разработка и пробный запуск на сервере заведения (Windows Server 2019, без Docker) | VPS |
| Процессы | один процесс `python -m app` | `api`, `worker`, `postgres`, `redis`, `caddy` в Docker Compose |
| Шина событий | в памяти | Redis pub/sub |
| Фоновые задачи | APScheduler в том же процессе | очередь arq (отдельный `worker`) |
| Rate limit | в памяти | Redis |
| Нужны Redis, arq, Docker | **нет** | да |

В режиме `single` Redis, arq и Docker не нужны и не запускаются. Пакеты режима `scaled` подключаются через `uv sync --extra scaled`; в режиме `single` код их не импортирует.

## Стек

- Backend: Python 3.12, FastAPI, Pydantic v2, APScheduler (single); SQLAlchemy 2 и Alembic — с модели данных (#7)
- Frontend: React, Vite, TypeScript, Tailwind (PWA)
- LLM: Claude API (tool use, стриминг) — с чата гостя (этапы 1–2)
- Режим `scaled`: Redis, arq, Docker Compose, Caddy
- БД: PostgreSQL 16. На момент каркаса БД не подключена: `DATABASE_URL` уже есть в конфигурации, но к ней никто не обращается до #7

## Структура

```
backend/              FastAPI-приложение (пакет app, управление зависимостями — uv)
  app/__main__.py     точка входа python -m app (режим single)
  app/main.py         create_app(): роутеры, lifespan, раздача frontend
  app/api/            /health, /health/ready
  app/core/           конфигурация, логи, интерфейсы EventBus/TaskScheduler/RateLimiter
  app/core/single/    реализации для single (в памяти, APScheduler)
  app/core/scaled/    реализации для scaled (Redis, arq) и arq worker
  app/web/spa.py      раздача frontend/dist с SPA fallback
  tests/              pytest
  pyproject.toml, uv.lock
frontend/             React-приложение (гость /t/{token}, официант /staff, админ /admin)
deploy/               Dockerfile, docker-compose.yml, Caddyfile (режим scaled)
docs/                 ТЗ, спецификации, архитектура, тест-кейсы
.github/workflows/    CI (ci.yml)
.env.example          все переменные окружения с комментариями
```

## Локальный запуск (режим single)

Шаги одинаковы для Windows и Linux; где команды различаются, даны оба варианта. На Windows команды приведены для PowerShell.

### 1. Что нужно установить

- **uv** — менеджер Python-окружения. Python 3.12 отдельно ставить не обязательно: если подходящего интерпретатора нет, `uv sync` скачает его сам (версия задана в `backend/.python-version`).
- **Node.js LTS 22 или новее** (`engines` в `frontend/package.json`) вместе с npm.
- **Git.**

Установка uv (любой из способов, подробнее — в [документации uv](https://docs.astral.sh/uv/getting-started/installation/)):

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# или
winget install --id=astral-sh.uv -e
```

```bash
# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Если Python уже установлен, подойдёт и `pip install uv`. В этом случае, если команда `uv` не находится в `PATH`, вызывайте её как `python -m uv` (например, `python -m uv sync`).

Проверка: `uv --version`, `node --version`, `npm --version`.

### 2. Клонировать репозиторий

```bash
git clone https://github.com/shakirena/ai-waiter.git
cd ai-waiter
```

### 3. Создать `.env`

Все переменные окружения перечислены в [.env.example](.env.example). Для локального запуска достаточно скопировать его без изменений в корень репозитория:

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```

```bash
# Linux
cp .env.example .env
```

`.env` не коммитится. Backend читает `../.env` (корень репозитория) и `backend/.env`, поэтому его запускают из каталога `backend/`. Значения по умолчанию: `APP_MODE=single`, `HOST=127.0.0.1`, `PORT=8000`. Если порт 8000 занят, поменяйте `PORT` в `.env` (или задайте переменную окружения `PORT`, она важнее файла).

### 4. Установить зависимости backend

```bash
cd backend
uv sync
cd ..
```

`uv sync` создаёт `backend/.venv` и ставит зависимости строго по `uv.lock`, включая инструменты разработки (pytest, ruff). Для запуска этого достаточно; для тестов нужен `uv sync --extra scaled` (см. «Проверки»).

### 5. Собрать frontend

```bash
cd frontend
npm ci
npm run build
cd ..
```

Сборка попадает в `frontend/dist`, backend раздаёт её сам (`SERVE_FRONTEND=true`). Если `frontend/dist` нет, backend всё равно запускается, но вместо страниц будет 404, а в лог попадёт предупреждение.

### 6. Запустить backend

```bash
cd backend
uv run python -m app
```

Процесс слушает `http://127.0.0.1:8000` (в режиме `single` допустим только loopback-адрес). Остановка — `Ctrl+C`.

### 7. Проверить

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","mode":"single","version":"0.1.0"}
curl http://127.0.0.1:8000/health/ready
# {"status":"ready","checks":{"redis":"skipped"}}
```

В PowerShell используйте `curl.exe` (без `.exe` вызывается `Invoke-WebRequest`) или просто откройте адрес в браузере.

Откройте в браузере:

- http://127.0.0.1:8000/t/demo — гость (заглушка)
- http://127.0.0.1:8000/staff — официант (заглушка)
- http://127.0.0.1:8000/admin — админ (заглушка)
- http://127.0.0.1:8000/docs — Swagger (включён вне `APP_ENV=prod`)

### Режим разработки frontend

Для работы над интерфейсом с горячей перезагрузкой запустите backend (шаг 6) и в другом терминале:

```bash
cd frontend
npm run dev
```

Vite открывается на http://localhost:5173 (если порт занят, берёт следующий свободный и печатает адрес в терминале) и проксирует на backend запросы к `/api`, `/integration`, `/health`, `/ws`, `/docs`, `/redoc`, `/openapi.json`. Адрес backend по умолчанию — `http://localhost:8000`; другой адрес задаётся переменной `VITE_API_PROXY_TARGET` (например, в `frontend/.env.local`). Если backend запущен на другом порту, укажите его здесь.

## Режим scaled (Docker Compose)

Для VPS: `api`, `worker`, `postgres`, `redis` и `caddy` в Docker Compose (файл [deploy/docker-compose.yml](deploy/docker-compose.yml)). Наружу открыт только Caddy (порты 80 и 443), он выпускает TLS-сертификат для домена и проксирует запросы в `api`. Остальные сервисы портов не публикуют.

Нужны Docker с плагином Compose и домен, DNS-запись которого указывает на сервер.

1. Создать `deploy/.env` из `.env.example` (из корня репозитория):

   ```bash
   cp .env.example deploy/.env
   ```

2. В `deploy/.env` раскомментировать и заполнить раздел «Только docker-compose»:

   | Переменная | Назначение |
   |---|---|
   | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | учётные данные PostgreSQL; пароль — только символы, допустимые в URL (буквы, цифры, `-`, `_`, `.`) |
   | `PUBLIC_DOMAIN` | домен для Caddy и `PUBLIC_BASE_URL`, например `menu.example.com` |
   | `EDGE_SUBNET` | частная подсеть сети `caddy`–`api`, не пересекающаяся с другими сетями хоста; `api` доверяет `X-Forwarded-For` только из неё |

   Необязательно: `API_WORKERS` — число процессов `api` (по умолчанию 2). `APP_MODE=scaled`, `APP_ENV=prod`, `DATABASE_URL`, `REDIS_URL` (`redis://redis:6379/0`), `PUBLIC_BASE_URL` и `MEDIA_DIR` compose задаёт сам, значения из `deploy/.env` для них игнорируются. Без любой обязательной переменной compose не запустится и назовёт её.

3. Собрать и запустить:

   ```bash
   docker compose -f deploy/docker-compose.yml up -d --build
   ```

   `deploy/.env` лежит рядом с compose-файлом, поэтому `--env-file` не нужен.

4. Проверить:

   ```bash
   docker compose -f deploy/docker-compose.yml ps     # все сервисы healthy
   curl https://menu.example.com/health               # {"status":"ok","mode":"scaled",...}
   curl https://menu.example.com/health/ready         # {"status":"ready","checks":{"redis":"ok"}}
   ```

Ограничение: при разработке каркаса compose-файл проверялся только командой `docker compose config`; сборка образа и запуск на настоящем Docker не проверялись. Миграции Alembic появятся вместе с моделью данных (#7). Установка режима `single` как службы Windows — отдельная задача.

## Проверки

Те же команды выполняет CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) на Linux и Windows.

Backend (из каталога `backend/`):

```bash
uv sync --extra scaled          # как в CI; без arq тесты режима scaled не соберутся
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Frontend (из каталога `frontend/`):

```bash
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

### Тесты и маркеры

- Unit-тесты не требуют внешних сервисов: реализации `scaled` проверяются на fakeredis.
- `db` — тесты с настоящим PostgreSQL, `scaled` — с настоящим Redis. В CI они выполняются только в Linux-джобе `backend-services` (`uv run pytest -q -m "db or scaled"`), а на обеих ОС — `uv run pytest -q -m "not db and not scaled"`.
- Локально `uv run pytest -q` запускает всё; тесты с настоящим Redis пропускаются (skipped), если не задан `REDIS_URL`.

## Конфигурация

Только через переменные окружения (или `.env`); полный список с комментариями — в [.env.example](.env.example). Неверная конфигурация останавливает запуск с понятным сообщением и кодом 1.

Репозиторий публичный: в нём нет и не должно быть реальных доменов, IP-адресов, ключей и паролей. `.env` и `deploy/.env` не коммитятся.
