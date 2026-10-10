# Story #43: Docker Compose для режима scaled: api, worker, postgres, redis, caddy

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given на Linux-хосте установлен Docker, рядом с `deploy/docker-compose.yml` лежит `.env`, созданный из `.env.example`, и задан домен When выполняется `docker compose -f deploy/docker-compose.yml up -d --build` Then запускаются сервисы api, worker, postgres, redis и caddy, у каждого есть healthcheck, `GET https://{домен}/health` отвечает `200`, а данные postgres и медиафайлы лежат в именованных томах
**Роли:** администратор VPS
**ТЗ:** ТЗ раздел 8, ТЗ 9.2, ТЗ 9.3, NFR-8
**Ограничения:** Бэкапы БД и медиа (NFR-9, отдельная задача); Sentry, мониторинг; Скрипты службы Windows для режима single; Применение миграций Alembic (появится с #7)
**Зависимости:** #37, #40, #41
**Spec:** docs/specs/feature-6-project-scaffold.md

---

## 💻 Реализация (developer)

**Branch:** wt/43-compose (от feature/6-project-scaffold)
**Новые файлы:**
- .dockerignore — исключает .git, .github, .claude, docs, `**/.env*`, `**/.venv`, `**/node_modules`, `**/dist`, кэши Python, media/backups

**Изменённые файлы:**
- deploy/Dockerfile — multi-stage: `node:22-alpine` (npm ci + build) → `ghcr.io/astral-sh/uv:0.12.21` (версия закреплена, тег проверен в ghcr.io) → `python:3.12-slim`; `uv sync --frozen --no-dev --extra scaled` с cache mount и `UV_PYTHON_DOWNLOADS=never`; пользователь app (uid/gid 10001, `USER 10001:10001`), писать может только в `/app/backend/media`; HEALTHCHECK на `/health`
- deploy/docker-compose.yml — api, worker, postgres, redis, caddy; healthcheck у каждого (api — python urllib `/health`; worker — `arq --check app.core.scaled.worker.WorkerSettings`; postgres — `pg_isready`; redis — `redis-cli ping`; caddy — `wget` (busybox в образе caddy) на admin API `127.0.0.1:2019/config/`); `depends_on: condition: service_healthy`; именованные тома pgdata, media, caddy_data, caddy_config; порты наружу только у caddy (80, 443, 443/udp); сети backend и edge (подсеть `EDGE_SUBNET`); `--forwarded-allow-ips=${EDGE_SUBNET}` вместо `'*'`; `no-new-privileges` для api/worker/caddy; обязательные переменные — `${VAR:?текст}`; `env_file: .env` = deploy/.env
- deploy/Caddyfile — HSTS без includeSubDomains, комментарии про X-Forwarded-For
- .env.example — раздел «Только docker-compose»: как создать deploy/.env, EDGE_SUBNET, требования к паролю
- backend/app/core/scaled/worker.py — `HEALTH_CHECK_INTERVAL = timedelta(seconds=60)` в WorkerSettings (по умолчанию arq — 1 час, healthcheck не заметил бы зависший worker)
- backend/tests/test_scaled_worker.py — проверка health_check_interval

**Build:** ruff OK · ruff format OK · pytest 398 passed, 3 skipped (нужен живой Redis) · hadolint v2.15.1 — 0 замечаний · `caddy validate` (caddy v2.11.6) — Valid configuration, `caddy fmt` — без изменений · `docker compose config` с заглушками — OK, без обязательной переменной — ошибка с текстом · `uv sync --frozen --no-dev --extra scaled` во временное окружение — OK, `create_app()` и ленивый `WorkerSettings` импортируются, `arq --check` разрешает модуль и без Redis завершается с кодом 1

**Не проверено (Docker daemon на машине разработчика выключен):** сборка образа, `docker compose up`, статусы healthy, `GET https://{домен}/health`, выпуск сертификата. Проверка admin API caddy на запущенном процессе не выполнена: песочница запрещает bind на 127.0.0.1:2019.

**Заметки:**
- caddy в штатном образе работает от root (как разрешено задачей); postgres и redis сами понижают привилегии в entrypoint.
- Пароль Postgres подставляется в URL без экранирования — только URL-безопасные символы (записано в .env.example).
- Redis без персистентности (`--appendonly no --save ""`): очередь arq теряется при пересоздании контейнера, задачи идемпотентны (ADR-1).
- Сервис migrate добавляется в #7 на якоре `x-app`.
