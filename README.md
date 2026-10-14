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

Установка uv (любой из способов, подробнее — в [документации uv](https://docs.astral.sh/uv/getting-started/installation/)). Способы с `irm | iex` и `curl | sh` запускают скачанный скрипт: пользуйтесь ими только с официального адреса astral.sh и при желании сначала прочитайте скрипт; безопаснее `winget` или `pip`:

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

Все переменные окружения перечислены в [.env.example](.env.example). Скопируйте его в корень репозитория и впишите в `DATABASE_URL` пароль роли PostgreSQL (шаг 5); остальное для локального запуска можно не менять:

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

### 5. База данных

Нужен PostgreSQL 16. На Windows достаточно установщика PostgreSQL (служба Windows, Docker не нужен), на Linux — пакета дистрибутива. Расширения и права суперпользователя приложению не нужны: роль `ai_waiter` — владелец своих баз.

Создайте роль и две базы: рабочую `ai_waiter` и тестовую `ai_waiter_test` (имя тестовой базы обязано оканчиваться на `_test`, тесты пересоздают в ней схему `public`). Кодировка — `UTF8`, локаль — `C`, шаблон — `template0`: установщик Windows может предложить `WIN1251` и локаль Windows, а дамп с такой локалью не восстановится на Linux. Команды выполняются от имени администратора PostgreSQL (обычно `postgres`); пароль придумайте сами и не коммитьте:

```powershell
# Windows (PowerShell): psql лежит в каталоге bin установленного PostgreSQL
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost
```

```bash
# Linux
sudo -u postgres psql
```

```sql
CREATE ROLE ai_waiter LOGIN PASSWORD '<пароль>';
CREATE DATABASE ai_waiter OWNER ai_waiter ENCODING 'UTF8' LOCALE 'C' TEMPLATE template0;
CREATE DATABASE ai_waiter_test OWNER ai_waiter ENCODING 'UTF8' LOCALE 'C' TEMPLATE template0;
```

В `.env` (корень репозитория):

```dotenv
DATABASE_URL=postgresql+asyncpg://ai_waiter:<пароль>@localhost:5432/ai_waiter
# только для тестов с PostgreSQL (pytest -m db); никогда не указывайте здесь рабочую базу
TEST_DATABASE_URL=postgresql+asyncpg://ai_waiter:<пароль>@localhost:5432/ai_waiter_test
```

Пароль в URL — только из символов, допустимых в URL (буквы, цифры, `-`, `_`, `.`), иначе его нужно URL-кодировать. Без `DATABASE_URL` приложение не запускается и называет переменную; недоступная база запуск не останавливает — о ней сообщает `/health/ready`.

Схему создают миграции Alembic (из каталога `backend/`; приложение при старте миграции не запускает):

```bash
cd backend
uv run alembic upgrade head      # применить все миграции
uv run alembic current           # текущая ревизия
uv run alembic downgrade -1      # откатить последнюю (только для разработки)
cd ..
```

Миграции применяются к базе из `DATABASE_URL`. Чтобы применить их к другой базе, задайте `DATABASE_URL` в окружении процесса — она важнее `.env`.

Проверка миграций перед пушем — то же, что делает CI-джоб `backend-services`: цикл `upgrade head` → `downgrade base` → `upgrade head` (миграции обратимы), `alembic check` (модели совпадают с миграциями) и инварианты схемы (`tests/db/test_schema_invariants.py`: `tenant_id`, `NUMERIC(10,2)`, `timestamptz`). Локально всё это выполняют db-тесты (цикл и `alembic check` — `tests/db/test_alembic.py`). Они подключаются только по `TEST_DATABASE_URL` и отказываются работать, если имя базы не оканчивается на `_test`, поэтому рабочую базу не трогают. На Windows хватает PostgreSQL-службы, Docker не нужен:

```bash
cd backend
uv run pytest -q -m db      # без uv в PATH: .\.venv\Scripts\python.exe -m pytest -q -m db
cd ..
```

Без `TEST_DATABASE_URL` (в `.env` или окружении) db-тесты пропускаются (skipped), а не проходят: проверьте, что в итоге нет `skipped`. Не запускайте `alembic downgrade base` вручную: команда работает с базой из `DATABASE_URL`, обычно рабочей, и удаляет все её таблицы. В CI этот цикл выполняется через CLI на одноразовой базе сервис-контейнера.

Демо-данные для разработки (вымышленное заведение «Demo Restoran»: 2 зала, 6 столов, 14 аллергенов ЕС, 4 категории и 15 блюд с ценами `default`/`vip` на AZ/RU, открытый визит и заказ):

```bash
cd backend
uv run python -m app.seed                          # в базу из DATABASE_URL
uv run python -m app.seed --database-url <URL>     # в другую базу (postgresql+asyncpg://…)
cd ..
```

Команда идемпотентна: повторный запуск не создаёт дублей и возвращает демо-данные к исходным значениям (заказ и его журнал не меняются). В конце она печатает ссылки гостя вида `/t/demo-table-01-dev-only` — откройте их на `http://127.0.0.1:8000` после запуска backend. Токены столов детерминированы и годятся только для разработки, поэтому при `APP_ENV=prod` команда отказывается работать (код выхода 2); ошибка подключения или отсутствие схемы — код 1 (пароль в сообщение не попадает). Сначала примените миграции.

### 6. Собрать frontend

```bash
cd frontend
npm ci
npm run build
cd ..
```

Сборка попадает в `frontend/dist`, backend раздаёт её сам (`SERVE_FRONTEND=true`). Если `frontend/dist` нет, backend всё равно запускается, но вместо страниц будет 404, а в лог попадёт предупреждение.

### 7. Запустить backend

```bash
cd backend
uv run python -m app
```

Процесс слушает `http://127.0.0.1:8000` (в режиме `single` допустим только loopback-адрес). Остановка — `Ctrl+C`.

### 8. Проверить

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","mode":"single","version":"0.1.0"}
curl http://127.0.0.1:8000/health/ready
# {"status":"ready","checks":{"database":"ok","redis":"skipped"}}
```

В PowerShell используйте `curl.exe` (без `.exe` вызывается `Invoke-WebRequest`) или просто откройте адрес в браузере.

`/health` (liveness) к базе не обращается. `/health/ready` выполняет `SELECT 1` (таймаут 2 с): если PostgreSQL недоступен, ответ — `503` и `"database":"fail"`; причина (без пароля) записывается в лог процесса, в ответ не попадает.

Откройте в браузере:

- http://127.0.0.1:8000/t/demo-table-01-dev-only — гость (заглушка; токен из демо-данных `python -m app.seed`)
- http://127.0.0.1:8000/staff — официант (заглушка)
- http://127.0.0.1:8000/admin — админ (заглушка)
- http://127.0.0.1:8000/docs — Swagger (включён вне `APP_ENV=prod`)

### Режим разработки frontend

Для работы над интерфейсом с горячей перезагрузкой запустите backend (шаг 7) и в другом терминале:

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
   | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | учётные данные PostgreSQL; пароль замените на случайный (например, `openssl rand -hex 24`), значение `change-me` из примера использовать нельзя; допустимы только символы, допустимые в URL (буквы, цифры, `-`, `_`, `.`) |
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
   curl https://menu.example.com/health/ready         # {"status":"ready","checks":{"database":"ok","redis":"ok"}}
   ```

Ограничение: при разработке каркаса compose-файл проверялся только командой `docker compose config`; сборка образа и запуск на настоящем Docker не проверялись. Сервис `migrate` (применение миграций Alembic при развёртывании) в compose ещё не добавлен — он появится в рамках модели данных (#7). Установка режима `single` как службы Windows — отдельная задача.

## Импорт меню из файла

Касса без коннектора может передать меню файлом CSV (а после #65 — XLSX). Файл — полный снимок меню: позиции, которых в нём нет, будут скрыты у гостей (не удалены). Команду импорта `python -m app.menu_sync` добавит #66; ниже — формат файла. Синтетический пример: [backend/tests/fixtures/menu/menu_valid.csv](backend/tests/fixtures/menu/menu_valid.csv).

### Формат файла меню

Одна строка — одна позиция; категория повторяется в каждой строке своих позиций. Первая непустая строка — заголовок. Имена колонок пишутся без учёта регистра, порядок колонок любой.

| Колонка | Обязательна | Значение |
|---|---|---|
| `category_external_id` | да | id категории в кассе, текст до 64 символов |
| `category_name` | да | название категории, до 200 символов; одинаковое во всех строках категории |
| `category_sort_key` | нет | порядок категории, до 64 символов; одинаковый во всех строках категории |
| `external_id` | да | id позиции в кассе, до 64 символов; уникален в файле; `007` и `7` — разные id |
| `name` | да | название позиции, до 200 символов |
| `price_default` | да | цена основного тарифа |
| `price_<tier>` | нет | цена тарифа `<tier>`, например `price_vip`; имя тарифа — строчные латинские буквы, цифры и `_`. Пустая ячейка — у позиции этого тарифа нет |
| `currency` | нет | код валюты ISO 4217 (`AZN`); пусто — валюта заведения; другая валюта отвергает весь файл |
| `station` | нет | станция кухни или бара, до 100 символов |
| `sort_key` | нет | порядок позиции, до 64 символов |
| `is_available` | нет | `1`/`0`, `true`/`false`, `yes`/`no`. Нет колонки — наличие позиций не меняется (ручной стоп-лист не затирается). Колонка есть — значение обязательно в каждой строке |

- Колонка, имя которой начинается с `#`, игнорируется (комментарий). Любая другая неизвестная колонка — ошибка: опечатка вроде `is_avalable` или `price_VIP` не должна молча потеряться.
- Цены: `8`, `8.5`, `8.50`; не больше двух знаков после точки (ядро не округляет), без минуса, пробелов и разделителей тысяч, максимум `99999999.99`. Цена `0` допускается с предупреждением.
- CSV: кодировка UTF-8 (в Excel — «Сохранить как → CSV UTF-8»; BOM допустим). Другие кодировки, например Windows-1251, отвергаются: азербайджанские буквы в них не представимы. Разделитель — `,` или `;`, определяется по заголовку. Десятичная запятая (`8,50`) допускается только при разделителе `;` — так сохраняет Excel с русской и азербайджанской локалью. Значение с разделителем или кавычками берётся в кавычки, кавычка внутри удваивается.
- Управляющие символы (табуляция, перевод строки внутри значения) — ошибка. Полностью пустые строки пропускаются.
- Лимиты: файл до 5 МБ, до 5000 строк данных, до 50 колонок, до 1000 символов в ячейке, до 500 категорий и 10 тарифов.
- «Всё или ничего»: при ошибке в любой строке файл не применяется целиком. В отчёте все ошибки (до 100) с номером строки файла (заголовок — строка 1, как в Excel) и колонкой, например «строка 7, колонка `external_id`: повтор external_id позиции (строка 3)».

```csv
category_external_id,category_name,category_sort_key,external_id,name,price_default,price_vip,currency,station,sort_key,is_available
10,Salatlar,10,007,Çoban salatı,4.50,5.50,AZN,Mətbəx,10001,1
10,Salatlar,10,009,"Qarışıq göyərti, limon",3.20,,AZN,Mətbəx,10003,0
30,İçkilər,30,203,Limonad ev üsulu,2.80,,,Bar,30003,no
```

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
- Локально `uv run pytest -q` запускает всё; тесты с настоящим Redis пропускаются (skipped), если не задан `REDIS_URL`, а тесты с PostgreSQL — если не задан `TEST_DATABASE_URL`.
- Тесты с PostgreSQL: `uv run pytest -q -m db`. Они подключаются только к `TEST_DATABASE_URL` (окружение или корневой `.env`, шаг 5), никогда к `DATABASE_URL`; имя базы обязано оканчиваться на `_test`, иначе прогон прерывается. Схема `public` тестовой базы пересоздаётся и заполняется миграциями (`alembic upgrade head`) один раз за прогон, каждый тест работает в транзакции, которая откатывается. На Windows хватает PostgreSQL-службы, Docker не нужен. В CI (`CI=true`) отсутствие `TEST_DATABASE_URL` — ошибка, а не пропуск.
- Покрытие: backend — `uv run pytest -q --cov=app --cov-report=term-missing`, frontend — `npm run test -- --run --coverage` (отчёт по `src/`). Цель — не ниже 95% по новому коду.

## Конфигурация

Только через переменные окружения (или `.env`); полный список с комментариями — в [.env.example](.env.example). Неверная конфигурация останавливает запуск с понятным сообщением и кодом 1.

Репозиторий публичный: в нём нет и не должно быть реальных доменов, IP-адресов, ключей и паролей. `.env` и `deploy/.env` не коммитятся.
