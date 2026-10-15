# Story #66: CLI-команда импорта меню из файла с режимом --dry-run

*Parent: #8. Spec: docs/specs/feature-8-menu-import.md (AC-6).*

---

## 📋 Задача (analyst)

**AC:** Given миграции применены, есть заведение и синтетический CSV When `python -m app.menu_sync import FILE --tenant UUID` с `--dry-run`, затем без него, затем повторно Then план без изменений БД (код 0), затем `applied` (код 0), затем `unchanged` (код 0)
**Роли:** оператор (разработчик, владелец платформы на сервере)
**ТЗ:** 4.2, 9.2, NFR-8
**Arch:** ADR-8.6 — `app/menu_sync/__main__.py`: `check FILE [--sheet] [--json]` (без БД), `import FILE --tenant UUID [--dry-run] [--force] [--allow-mass-hide] [--sheet] [--database-url] [--json]`; коды 0 успех, 1 окружение, 2 данные, 3 lock занят
**Ограничения:** загрузка через админку (#29 после #19), встроенный импорт по расписанию (Планировщик заданий/cron с тем же CLI), HTTP-эндпоинты; разрешена при APP_ENV=prod
**Зависимости:** #63, #64
**Spec:** docs/specs/feature-8-menu-import.md

---

## 🏗️ Архитектура (architect)

**ADR:** ADR-8.6 (CLI, коды выхода, single на Windows, без EventBus); DEC-011, DEC-012
**Таблицы:** через сервис (#62, #63)
**Миграция:** нет
**API:** нет (контракт будущего `POST /api/admin/menu/import` — в arch doc, реализация в #29)
**События/задачи:** нет; импорт по расписанию — вне scope (Планировщик Windows / cron запускает тот же CLI)
**ИИ-tools:** не затронуты
**Security:** разрешён при `APP_ENV=prod`; ошибки БД — через `Database.describe_error` (без пароля); в журнал пишется только имя файла (`Path(file).name`)
**Code stubs:**
- `backend/app/menu_sync/__main__.py` — `build_parser()`, `run_check(args) -> int`, `run_import(args) -> int`, `main(argv=None) -> int`; `EXIT_OK = 0`, `EXIT_ERROR = 1`, `EXIT_INVALID_DATA = 2`, `EXIT_BUSY = 3`
**Команды:** `python -m app.menu_sync check FILE [--sheet] [--json]` (без БД и `.env`); `python -m app.menu_sync import FILE --tenant UUID [--dry-run] [--force] [--allow-mass-hide] [--sheet] [--database-url] [--json]`
**Поведение:** `import` — разбор → `apply_menu_snapshot` в `session.begin()`; ошибки разбора или `rejected` → `record_rejected_run` в новой транзакции (кроме `--dry-run`) и код 2; `MenuSyncBusyError` → 3; нет файла/конфигурации/БД/заведения → 1; отчёт по-русски в stdout, ошибки окружения — в stderr
**Тесты:** unit `tests/test_menu_sync_cli.py` (check, аргументы, `--json`, коды 0/1/2); db `tests/db/test_menu_sync_cli.py` (AC #66: dry-run → applied → unchanged, коды 0; ошибки → 2 и `rejected`; нет заведения → 1; lock → 3)
**Зависимости:** #63, #64 (XLSX — если #65 влит)
**Arch doc:** docs/arch/feature-8-menu-import.md (раздел «Истории — файлы, тесты, порядок»)

---

## 💻 Разработка (developer)

**Branch:** story/66-menu-import (от feature/8-menu-import на 2bfd1ed, worktree s66)
**Новые файлы:**
- backend/tests/test_menu_sync_cli.py — unit без БД: аргументы (`--tenant` обязателен, неверный UUID, нет подкоманды → 1; `--help` → 0), `check` (CSV, XLSX с `--sheet`, неизвестный формат, > 100 проблем, нет файла, каталог, нет прав, управляющие символы в пути), `--json`, `import` с подменённым сервисом (коды 0/1/2/3, строки файла у проблем `check_snapshot`, журнал `rejected`, пароль не печатается, разрешён при `APP_ENV=prod`), точка входа (subprocess и runpy)
- backend/tests/db/test_menu_sync_cli.py — db: AC #66 (dry-run → applied → unchanged → `--force`), ошибки разбора → 2 и `rejected` с именем файла без каталога, чужая валюта → строка файла в журнале, `issues_truncated` в журнале, нет колонки `is_available` → наличие не меняется, mass-hide → 2 и обход `--allow-mass-hide`, пустой файл → 2 даже с `--allow-mass-hide`, нет заведения → 1, lock занят → 3, неверный пароль не печатается

**Изменённые файлы:**
- backend/app/menu_sync/__main__.py — реализация заглушки: `build_parser`, `run_check`, `run_import`, `main`
- backend/app/menu_sync/service.py — `record_rejected_run(..., issues_truncated=0)`: число проблем, уже отброшенных вызывающим, прибавляется к своим (иначе журнал терял «и ещё N» для файла с > 100 ошибками)
- README.md — «Команда импорта» (параметры, коды выхода, пример отчёта, PowerShell и Linux), «Импорт по расписанию» (Планировщик заданий / cron, без кода в ядре), «Выгрузка меню из кассы „restoran“» (`php yii ai-export-menu`, затем `check` и `import --dry-run`, предупреждение про Excel и `local-data/`)

**Решения:**
- Ошибка в аргументах (нет `--tenant`, неверный UUID, нет подкоманды) — код 1, а не 2 argparse: код 2 зарезервирован за ошибками в данных файла. Тексты argparse («the following arguments are required», «usage:») остаются английскими — переводить стандартные сообщения argparse не стали; свои сообщения и справка по-русски.
- `import` сначала читает файл (нет файла → 1, конфигурация не нужна), затем `Settings`. `--dry-run` с ошибками разбора файла в БД не ходит (код 2, журнала нет). Без `--dry-run` ошибки разбора журналируются: перед `record_rejected_run` проверяется, что заведение есть (иначе 1 вместо ошибки FK).
- Проблемы из `apply_menu_snapshot` проходят `locate_issues(…, item_rows)` и повторную сортировку `limit_issues`; в журнал `rejected` пишутся уже со строкой и колонкой файла. У `applied` с предупреждениями (`zero_price`) журнал пишет сервис — там строк файла нет, в выводе CLI они есть.
- `started_at` — момент запуска CLI (до чтения файла), передаётся в `record_rejected_run`.
- Вывод: имя файла без каталога (`Path(file).name`), невидимые символы экранированы (`safe_text`); `DATABASE_URL` не печатается, ошибки БД — `Database.describe_error`. `--json` — ASCII (`ensure_ascii=True`), чтобы JSON был корректным при любой кодировке консоли и перенаправления; деньги в отчёте не встречаются (только счётчики), значения проблем — строки.
- stdout/stderr переключаются на `errors="backslashreplace"`: на Windows при перенаправлении в файл (cp1251) символ `ə` печатается как `ə`, а не роняет команду `UnicodeEncodeError`. README советует `PYTHONUTF8=1` для журналов планировщика.

**Build:** ruff check / format OK · pytest 1649 passed, 3 skipped (с db; без Redis) · покрытие `app/menu_sync/__main__.py` и всего `app/menu_sync` — 100 %
