# Story #64: Разбор CSV-файла меню в снимок с построчным отчётом ошибок

*Parent: #8. Spec: docs/specs/feature-8-menu-import.md (AC-4).*

---

## 📋 Задача (analyst)

**AC:** Given CSV UTF-8 с BOM, разделитель `;`, цены с запятой, строка 4 — цена `abc`, строка 7 повторяет `external_id` строки 3 When файл разбирается Then ошибки «строка 4, колонка `price_default`» и «строка 7, колонка `external_id`: повтор (строка 3)», снимка нет; исправленный файл даёт `Decimal("4.50")`
**Роли:** администратор (готовит файл), оператор (запускает)
**ТЗ:** 4.2, INT-2, C-07
**Arch:** ADR-8.2 — `app/menu_sync/files/{__init__,format,csv_reader}.py`, пример `backend/tests/fixtures/menu/menu_valid.csv`, описание формата в README; колонки с `#` игнорируются, иная неизвестная — ошибка; запятая в числах только при `;`; лимиты 5 МБ / 5000 строк
**Ограничения:** XLSX (#65), запись в БД, CLI, выгрузка «restoran» (#67); в репозитории только синтетический пример
**Зависимости:** #61
**Spec:** docs/specs/feature-8-menu-import.md

---

## 🏗️ Архитектура (architect)

**ADR:** ADR-8.2 (формат, CSV, лимиты), ADR-8.7 (безопасность); DEC-011 (границы: `files` без SQLAlchemy)
**Таблицы:** нет
**Миграция:** нет
**API:** нет; `parse_menu_bytes` — общая точка для CLI (#66) и будущей загрузки в админке
**События/задачи:** нет
**ИИ-tools:** не затронуты
**Security:** лимит 5 МБ проверяется через `stat` до чтения; 5000 строк, 50 колонок, 1000 символов на ячейку; только UTF-8; управляющие символы → ошибка; путь — только из аргумента
**Code stubs:**
- `backend/app/menu_sync/files/__init__.py` — `FileFormat`, `ParsedMenuFile(file_format, snapshot, issues, rows_total, item_rows, has_availability)`, `detect_format(filename, head) -> FileFormat | None`, `parse_menu_bytes(data, filename, *, sheet=None) -> ParsedMenuFile`, `read_menu_file(path, *, sheet=None) -> ParsedMenuFile`; `MAX_FILE_BYTES`
- `backend/app/menu_sync/files/format.py` — константы колонок, `Cell`, `SheetRow`, `TabularData(header, header_row, rows, decimal_comma)`, `ColumnLayout`; `parse_header`, `cell_to_text`, `cell_to_external_id`, `cell_to_money(cell, *, decimal_comma)`, `cell_to_bool`, `rows_to_snapshot(table) -> (snapshot | None, issues, item_rows, has_availability)`
- `backend/app/menu_sync/files/csv_reader.py` — `read_csv_table(data) -> (TabularData | None, issues)`
- `backend/tests/fixtures/menu/menu_valid.csv` — синтетический пример (есть)
**Правила:** колонки — ADR-8.2; `#`-колонки игнорируются, другие неизвестные → ошибка; разделитель `,`/`;` по заголовку; десятичная запятая только при `;`; номер строки = физическая строка начала записи (заголовок = 1); ошибки Pydantic и `check_snapshot` переводятся в номер строки через `item_rows`
**Тесты:** unit `tests/test_menu_csv.py` (AC #64 и список из arch doc); граница: `app/menu_sync/files` без `sqlalchemy`/`app.db`/`app.models` (кроме `enums`)
**Зависимости:** #61; новых пакетов нет (стандартный `csv`)
**Arch doc:** docs/arch/feature-8-menu-import.md (раздел «Истории — файлы, тесты, порядок»)

---

## 💻 Разработка (developer)

**Branch:** story/64-menu-import (worktree s64, от feature/8-menu-import на c7bec9c)
**Новые файлы:**
- backend/tests/test_menu_csv.py

**Изменённые файлы:**
- backend/app/menu_sync/files/__init__.py — `detect_format`, `parse_menu_bytes`, `read_menu_file` (stat до чтения + чтение не больше `MAX_FILE_BYTES + 1`), `locate_issues`; `ParsedMenuFile.file_format: FileFormat | None`, новое поле `issues_truncated`, свойство `has_errors`; XLSX — ветка в `_read_table` с `unsupported_format` (точка подключения #65)
- backend/app/menu_sync/files/format.py — `CellError(code, message)`, `cell_to_*`, `parse_header`, `rows_to_snapshot`, `file_column`; `ColumnLayout.ignored` (колонки `#…`)
- backend/app/menu_sync/files/csv_reader.py — `read_csv_table`, `detect_delimiter`
- backend/tests/test_import_boundaries.py — `files` без прямых импортов `sqlalchemy`/`app.db`/`app.models` (кроме `enums`)
- README.md — раздел «Импорт меню из файла» / «Формат файла меню»

**Решения:**
- Строка с ошибкой в ячейке или с повтором `external_id` в модель снимка не передаётся (одна причина — одно сообщение); остальные строки проверяются моделью `MenuSnapshot`, ошибки Pydantic получают строку по индексу элемента и колонку файла (`prices.vip` → `price_vip`, поля категории → `category_*`, строка — первая строка категории).
- Валюта заведения в разборе файла неизвестна: `currency_mismatch` и `zero_price` даёт `check_snapshot` при применении; `locate_issues(issues, item_rows)` добавляет к ним строку и колонку файла (для CLI #66).
- Имена колонок без учёта регистра, кроме имени тарифа: `price_VIP` → `invalid_tier` (ADR-8.2 требует, чтобы такая опечатка не пропала молча); `price_default` — в любом регистре.
- Колонка с пустым заголовком допустима, если пуста во всех строках (Excel дописывает пустые колонки); значение в ней или за последней колонкой заголовка — `unknown_column` («колонка N»).
- Нарушение кавычек CSV — `unsupported_format` с номером строки (новых `IssueCode` нет). `csv.field_size_limit` не меняется (глобальное состояние процесса): лимит 1000 символов проверяет `format`, поле > 128 КиБ — ошибка разбора CSV.
- Список проблем ограничен `limit_issues` (100), остаток — `ParsedMenuFile.issues_truncated`.
- Транзитивно `app.models.enums` загружает пакет `app.models` с ORM (его `__init__`); граница проверяется по прямым импортам.

**Build:** ruff check / format OK · pytest -m "not db": 1101 passed, 3 skipped (db-тесты не запускались — общая тестовая БД занята #62) · покрытие `files/__init__.py`, `csv_reader.py`, `format.py` — 100 % (ветви включены)
