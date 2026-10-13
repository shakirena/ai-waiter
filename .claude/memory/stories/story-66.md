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
