# Test Cases: Story #45 — README: инструкция локального запуска, режимы single, scaled

**Feature:** #6 «Каркас проекта» (story #45, AC-9)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-45-001: Локальный запуск по README (режим single)

**Priority:** Critical
**Type:** Functional
**AC:** AC-9 (Given чистая машина с Python 3.12 и Node LTS / When шаги раздела «Локальный запуск» / Then backend отвечает на `/health`, frontend открывается в браузере)
**E2E Automated:** No
**Автоматизация:** Ручной. Часть шагов покрыта автотестами: `test_repo_artifacts.py::test_readme_has_required_sections_and_commands`.
**Статус прогона:** Частично PASS. QA выполнил на Windows 11 шаги 5–7 (сборка frontend, `python -m app`, `/health`, `/health/ready`, раздача `/t/demo`). Установка с нуля на чистой машине (шаги 1–4) не выполнялась: на рабочей машине окружение уже собрано, `uv` отсутствует в PATH. Установку в чистом клоне разработчик проверял при подготовке README (коммит ce0d292).

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Установить Python 3.12, Node 22+, uv | Версии соответствуют README |
| 2 | Клонировать репозиторий, скопировать `.env.example` в `.env` | `.env` создан |
| 3 | `uv sync` в `backend/`, `npm ci` в `frontend/` | Без ошибок |
| 4 | `npm run build` в `frontend/` | Создан `frontend/dist` |
| 5 | `uv run python -m app` в `backend/` | Процесс слушает `127.0.0.1:8000` |
| 6 | `curl http://127.0.0.1:8000/health` | `{"status":"ok","mode":"single","version":"0.1.0"}` |
| 7 | Открыть `http://127.0.0.1:8000/t/demo` в браузере | Открывается заглушка гостя |

---

## TC-45-002: Раздел «Режим scaled» и команды проверок совпадают с фактическими

**Priority:** High
**Type:** Functional
**AC:** AC-9 (раздел «Режим scaled» описывает запуск через `docker compose` и команды проверки (`ruff`, `pytest`, `npm run lint/test/build`), совпадающие с фактическими скриптами)
**E2E Automated:** No
**Автоматизация:** Авто — `test_repo_artifacts.py::test_readme_commands_match_actual_frontend_scripts` (каждый `npm run <скрипт>` из README есть в `package.json`), `test_readme_has_required_sections_and_commands` (разделы и команды `uv run ruff check .`, `uv run pytest -q`, `docker compose -f deploy/docker-compose.yml up -d --build`).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Сверить команды раздела «Проверки» со скриптами `frontend/package.json` и CI | Совпадают |
| 2 | Сверить команду запуска scaled с `deploy/docker-compose.yml` | Файл существует по указанному пути, обязательные переменные перечислены |

---

## TC-45-003: README не содержит секретов и адресов заведения

**Priority:** High
**Type:** Security
**AC:** AC-9 (+ NFR-2: репозиторий публичный)
**E2E Automated:** No
**Автоматизация:** Авто (частично) — `test_env_files_are_gitignored_except_example`, `test_no_ip_addresses_or_keys_in_infrastructure_files` (для `.env.example`, compose, Caddyfile, `ci.yml`). Для README — ручной просмотр.
**Статус прогона:** PASS. Замечание: в README и `.env.example` пароль `change-me` назван недопустимым, требуется случайный.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Поиск IP-адресов, ключей и паролей в README | Только примеры с `example.com` и placeholder-значения |
| 2 | Проверить `.gitignore` | `.env` и `.env.*` игнорируются, `.env.example` — нет |

---

## Related TCs
- TC-42-001 (`/t/demo` через backend), TC-43-003 (запуск scaled)
