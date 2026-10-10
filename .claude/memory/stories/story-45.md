# Story #45: README: инструкция локального запуска, режимы single, scaled

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given чистая машина (Windows или Linux) с установленными Python 3.12 и Node LTS, клонированный репозиторий When разработчик выполняет шаги раздела «Локальный запуск» из README для режима `single` Then backend отвечает на `/health`, frontend открывается в браузере, а раздел «Режим scaled» описывает запуск через `docker compose` и команды проверки (`ruff`, `pytest`, `npm run lint/test/build`), совпадающие с фактическими скриптами
**Роли:** новый разработчик
**ТЗ:** ТЗ раздел 8, ТЗ 9.1, 9.2, NFR-8
**Ограничения:** Инструкция по установке на Windows Server 2019 как службы (отдельная задача этапа 5); Пользовательская документация для заведения; Описание API
**Зависимости:** #37, #42, #43
**Spec:** docs/specs/feature-6-project-scaffold.md

---

## 💻 Реализация (developer)

**Branch:** wt/45-readme (от feature/6-project-scaffold)
**Новые файлы:** нет

**Изменённые файлы:**
- README.md — статус (каркас готов, бизнес-логики нет), таблица режимов single/scaled (Redis, arq, Docker — только scaled), стек с оговоркой про БД (не подключена до #7), реальная структура, «Локальный запуск» (uv, Node 22+, `.env` для PowerShell и bash, `uv sync`, `npm ci && npm run build`, `uv run python -m app`, `/health`, `/health/ready`, `/t/demo`, `/staff`, `/admin`, `/docs`), режим разработки (`npm run dev`, proxy, `VITE_API_PROXY_TARGET`), «Режим scaled» (deploy/.env: POSTGRES_*, PUBLIC_DOMAIN, EDGE_SUBNET, API_WORKERS; что compose задаёт сам), «Проверки» (как в CI), маркеры db/scaled, конфигурация
- CLAUDE.md — «Состояние проекта» актуализировано, добавлен раздел «Команды»
- .claude/memory/project-summary.md — Build Commands, Layout, Current State

**Build:** проверка README в чистом клоне (`git clone --no-hardlinks`, Windows 11, Git Bash): `cp .env.example .env` · `uv sync` (uv 0.12.21 сам поставил Python 3.12.14) · `npm ci` · `npm run build` · `uv run python -m app` → `/health` 200 `{"status":"ok","mode":"single",...}`, `/health/ready` `{"redis":"skipped"}`, `/t/demo`, `/staff`, `/admin`, `/docs` → 200 · `npm run dev` → proxy `/health` и `/docs` 200, `/t/demo` отдаёт index.html Vite · `PORT=8765` перекрывает `.env`; без `frontend/dist` — `/t/demo` 404 и warning в логе · `uv sync --extra scaled` · ruff check OK · ruff format --check OK (50 файлов) · pytest 400 passed, 3 skipped (нужен живой Redis) · npm lint OK · typecheck OK · vitest 15 passed. Все ссылки README на файлы существуют.

**Заметки:**
- Найдено при проверке и учтено в README: после одного `uv sync` (без `--extra scaled`) `pytest` падает на сборке 6 модулей `test_scaled_*` (нет `arq`), поэтому для проверок нужен `uv sync --extra scaled`; пакет `redis` ставится и без extra (зависимость fakeredis из dev-группы); при занятом 5173 Vite берёт следующий порт.
- Команда scaled — без `--env-file`: compose читает `deploy/.env` рядом с compose-файлом (так в шапке deploy/docker-compose.yml; в arch doc был вариант `--env-file .env`).
- Не проверялось: Linux (только Windows), чистая машина без Python/Node, официальные установщики uv (использован уже установленный uv), `docker compose up` (Docker не запускался), открытие страниц в браузере (проверено curl).
- При перенаправлении stdout в файл на Windows кириллица в логе (формат console) пишется в кодировке консоли; с `PYTHONIOENCODING=utf-8` — корректно. На запуск не влияет.
