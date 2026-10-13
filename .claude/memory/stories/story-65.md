# Story #65: Разбор XLSX-файла меню в снимок

*Parent: #8. Spec: docs/specs/feature-8-menu-import.md (AC-5).*

---

## 📋 Задача (analyst)

**AC:** Given XLSX с данными синтетического CSV-примера на втором листе `Menu` (первый — другой), цены числами When разбор без указания листа Then выбран лист `Menu`, снимок совпадает со снимком CSV-примера, цены `Decimal` с двумя знаками без двоичной погрешности
**Роли:** администратор, оператор
**ТЗ:** 4.2
**Arch:** ADR-8.2, 8.7 — `app/menu_sync/files/xlsx_reader.py` (openpyxl только здесь), `defusedxml`, защита от zip-бомбы; лист `--sheet`, иначе `menu`, иначе первый; size:s → size:m
**Ограничения:** `.xls`, ODS, несколько листов за раз, CLI
**Зависимости:** #64
**Spec:** docs/specs/feature-8-menu-import.md

---

## 🏗️ Архитектура (architect)

**ADR:** ADR-8.2 (XLSX: лист, типы ячеек), ADR-8.7 (зависимости, zip-бомба, `defusedxml`, формулы, макросы)
**Таблицы:** нет
**Миграция:** нет
**API:** нет
**События/задачи:** нет
**ИИ-tools:** не затронуты
**Security:** `check_xlsx_archive` до openpyxl — сигнатура zip, `vbaProject.bin`/`.xlsm` → отказ, сумма распакованных ≤ 50 МБ, сжатие ≤ 100×; `load_workbook(read_only=True, data_only=True)`; формулы не вычисляются; книга закрывается в `finally`
**Code stubs:**
- `backend/app/menu_sync/files/xlsx_reader.py` — `check_xlsx_archive(data) -> list[SyncIssue]`, `read_xlsx_table(data, *, sheet=None) -> (TabularData | None, issues)`; `DEFAULT_SHEET_NAME = "menu"`, `MAX_UNCOMPRESSED_BYTES`, `MAX_COMPRESSION_RATIO`
**Правила:** лист — `sheet` из аргумента, иначе `menu` (без учёта регистра), иначе первый; числовой `external_id` 7.0 → `"7"`, дробный → `invalid_id`; float-цена через `repr`, шум < 1e-9 округляется, остальное > 2 знаков → ошибка; дата/время/`#N/A` → `invalid_cell_type`; формула без кеша → `formula_without_value`
**Зависимости пакетов:** `openpyxl>=3.1`, `defusedxml>=0.7` — основная группа `backend/pyproject.toml` + `uv.lock`; ruff `banned-api` `openpyxl` с `per-file-ignores` для `app/menu_sync/files/xlsx_reader.py`; `RESTRICTED["openpyxl"] = ("menu_sync/files/xlsx_reader.py",)` в `tests/test_import_boundaries.py`
**Тесты:** unit `tests/test_menu_xlsx.py` (книги собираются в тесте; AC #65 — снимок совпадает со снимком `menu_valid.csv`; `openpyxl.xml.DEFUSEDXML is True`)
**Зависимости:** #64
**Arch doc:** docs/arch/feature-8-menu-import.md (раздел «Истории — файлы, тесты, порядок»)
