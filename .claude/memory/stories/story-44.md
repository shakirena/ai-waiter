# Story #44: GitHub Actions: линтер, тесты backend, frontend на Linux, Windows

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given в репозитории есть `.github/workflows/ci.yml` и открыт pull request When запускается workflow с матрицей `ubuntu-latest` и `windows-latest` Then на обеих ОС выполняются `ruff check` и `pytest` (Python 3.12) в `backend/` и `npm ci`, `lint`, `test`, `build` (Node LTS) в `frontend/`, с кэшем зависимостей, а падение любого шага на любой ОС делает проверку красной
**Роли:** разработчик
**ТЗ:** ТЗ 9.2 (проверка в CI на Windows и Linux), ТЗ раздел 8 (GitHub Actions), NFR-8
**Ограничения:** Сборка и публикация Docker-образов; Деплой; E2E-тесты Playwright; Проверки, требующие PostgreSQL (появятся с #7)
**Зависимости:** #37, #41
**Spec:** docs/specs/feature-6-project-scaffold.md

---

## 💻 Реализация (developer)

**Branch:** wt/44-ci (от feature/6-project-scaffold; слияние в ветку feature #6)
**Новые файлы:** —
**Изменённые файлы:**
- .github/workflows/ci.yml

**Что сделано:**
- Джобы `backend` и `frontend` — матрица `ubuntu-latest` + `windows-latest`, `fail-fast: false`; `backend-services` — Linux с `postgres:16` и `redis:7-alpine` (healthcheck-и), маркеры `db or scaled`.
- Во всех джобах `defaults.run.shell: bash` (Git Bash на Windows) — один синтаксис шагов на обеих ОС; GitHub запускает его с `-eo pipefail`.
- Python 3.12 — через `astral-sh/setup-uv@v10` (`python-version: "3.12"`, кэш по `backend/uv.lock`) и отдельный шаг проверки версии; `UV_FROZEN=1` на уровне workflow: uv.lock не обновляется ни одной командой.
- Node 22 — `actions/setup-node@v7`, кэш npm по `frontend/package-lock.json`; команды совпадают со скриптами package.json (`lint`, `typecheck`, `test -- --run`, `build`).
- Код 5 pytest в `backend-services`: явная проверка `code == 5` → notice и успех; коды 1–4 проходят как есть (проверено локально: пустой набор → 0, падающие тесты → 1, ошибка выражения `-m` → 4).
- `-m "not db and not scaled"` совместим с `--strict-markers`: маркеры объявлены в pyproject.toml, а фильтр `-m` регистрации не требует.
- `permissions: contents: read`, `persist-credentials: false`, `timeout-minutes: 20`; concurrency отменяет только устаревшие прогоны PR, прогоны main не отменяются. Секретов нет.
- Actions — мажорные теги актуальных версий: checkout@v7, setup-node@v7, setup-uv@v10. Закрепление по SHA — рекомендация на будущее вместе с автообновлением (dependabot/renovate): без него SHA устаревают.

**Build:** actionlint 1.7.12 + shellcheck — 0 ошибок · ruff check OK · ruff format OK · pytest (not db and not scaled) 59 passed / 31 failed / 8 errors / 5 skipped — все падения на заглушках `NotImplementedError` историй #38, #39, #40, #42 · frontend npm ci, lint, typecheck, test (15 passed), build OK. Запуск на GitHub не выполнялся (без push).
