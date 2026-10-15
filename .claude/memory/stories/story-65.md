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

---

## 💻 Разработка (developer)

**Branch:** story/65-menu-import (worktree s65, от feature/8-menu-import на 1093769)
**Новые файлы:**
- backend/tests/test_menu_xlsx.py

**Изменённые файлы:**
- backend/app/menu_sync/files/xlsx_reader.py — `check_xlsx_archive`, `read_xlsx_table`; константы `ZIP_SIGNATURE` (перенесена из `files/__init__`), `NOT_XLSX_HINT`, `MACRO_HINT`, `UNREADABLE_HINT`, `FORMULA_HINT`
- backend/app/menu_sync/files/__init__.py — ветка XLSX в `_read_table` вызывает `read_xlsx_table(data, sheet=sheet)`; `ZIP_SIGNATURE` импортируется из `xlsx_reader`
- backend/app/menu_sync/files/format.py — `CellProblem(code, message)` в типе `Cell`; `cell_to_*` превращают его в `CellError` с его кодом
- backend/pyproject.toml, backend/uv.lock — `openpyxl>=3.1` (3.1.5, тянет `et-xmlfile` 2.0.0), `defusedxml>=0.7` (0.7.1); ruff `banned-api` для `openpyxl` + `per-file-ignores` для `xlsx_reader.py`
- backend/tests/test_import_boundaries.py — `RESTRICTED["openpyxl"]`
- backend/tests/test_menu_csv.py — тест «XLSX пока не поддерживается» переименован: повреждённый `.xlsx` → `unsupported_format`
- README.md — XLSX поддерживается: выбор листа (`--sheet`, `menu`, первый), числа, формулы, даты, макросы, zip-бомба

**Решения:**
- Формула без сохранённого значения в `data_only=True` неотличима от пустой ячейки. Поэтому вторая книга (`data_only=False`) читается параллельно построчно (`zip(strict=True)`): ячейка пуста в первой и непуста во второй — это `formula_without_value`. Обе книги закрываются в `finally`.
- Проблемные ячейки (ошибка Excel `t="e"`, формула без значения, `timedelta`) передаются в `format` как `CellProblem`: сообщение получает строку и колонку файла, в колонке-комментарии `#…` проблема игнорируется, и одна причина даёт одно сообщение (без лишнего `required`). Проблемная ячейка в заголовке — ошибка с «колонка N».
- Объявленные размеры листа (`<dimension>`) не используются (`reset_dimensions`): строки и колонки берутся из ячеек, и неверный `<dimension>` не теряет данные. Пустые отформатированные ячейки правее `MAX_COLUMNS` отбрасываются: проверка через `tuple.count(None)` без цикла Python, потому что ячейка в XFD даёт строку из 16 384 элементов. Значение правее лимита — `too_many_columns` (CSV строже: там считаются и пустые поля).
- Лист из `sheet` ищется по точному имени, затем без учёта регистра. Если листа нет — `sheet_not_found` с перечнем листов. Лист `menu` ищется после `strip().casefold()`. Берутся только `workbook.worksheets`, листы диаграмм не учитываются.
- Архив: сигнатура, читаемый zip, `xl/workbook.xml`, `vbaProject.bin` (в любом каталоге, любой регистр) → `unsupported_format`; сумма `file_size` > 50 МБ или `file_size > 100 × compress_size` члена → `unsafe_archive`. `zipfile` не распаковывает больше объявленного `file_size`, поэтому проверки заголовков достаточно.
- Любое исключение openpyxl или XML-парсера (включая `EntitiesForbidden` от defusedxml) → `unsupported_format` с подсказкой пересохранить книгу; текст исключения в отчёт не попадает.

**Build:** ruff check / format OK · pytest -m "not db": 1216 passed, 3 skipped (db-тесты не запускались: общая тестовая БД занята #62) · покрытие `xlsx_reader.py`, `files/__init__.py`, `format.py`, `csv_reader.py` — 100 % (с ветвями)

---

## 🔒 Security Review

**Verdict:** FAIL (цикл 1) → исправлено в `fix(#65)`, нужно повторное ревью
**Findings:** CRITICAL 0, HIGH 1, MEDIUM 0, LOW 2, INFO 1 — https://github.com/shakirena/ai-waiter/issues/65#issuecomment-6185832847

**Исправления (`fix(#65)`, только `xlsx_reader.py` и `test_menu_xlsx.py`):**
- [HIGH] DoS по CPU. Обход листа прерывается, если номер строки больше `MAX_SHEET_ROWS` = `MAX_DATA_ROWS` + `MAX_BLANK_ROWS` (10 000, пустых — как `MAX_BLANK_RECORDS` в CSV), это `too_many_rows`. Обход также прерывается, если сумма ширин строк больше `MAX_SCANNED_CELLS` (300 000, около 18 строк с ячейкой в XFD), это `too_many_columns`. Генераторы openpyxl ленивые, поэтому `r=10^12` даёт ошибку за 0,02 с.
- Обнаружено при исправлении: стоимость openpyxl пропорциональна числу XML-элементов, а строки с повторным или убывающим `r` он разбирает, но не отдаёт; 400 тыс. таких строк (2 МБ) разбирались 27 с, 300 тыс. `mergeCell` — 24 с. Поэтому до openpyxl элементы считаются регулярным выражением с ранним выходом (`_count_tags`):
  - части вне `xl/worksheets/`: не больше 20 МБ и 200 000 элементов (имя части не важно);
  - вся книга: не больше `MAX_BOOK_TAGS` (830 000);
  - выбранный лист: `row` ≤ 10 000, `c` ≤ 150 000 (5000 × 30), прочих элементов ≤ 20 000, всего ≤ 630 000.
- Вторая книга (`data_only=False`) открывается, только если на листе есть `<f>`. Это сокращает память и время для книг без формул.
- [LOW] Значение ячейки `t="e"` выводится только из белого списка `EXCEL_ERROR_CODES`, иначе пишется «ошибка Excel».
- [LOW] Вместо лимита `xl/sharedStrings.xml` по имени — лимит всех частей вне листов (`MAX_NON_SHEET_BYTES` = 20 МБ и `MAX_NON_SHEET_TAGS`). Его нельзя обойти переименованием части.

**Замеры после исправления (Windows, одна попытка):** `r=10^7` и `r=10^12` — 0,02 с; 200 тыс. строк с ячейкой в XFD (1 МБ) — 0,54 с; 200 тыс. пустых строк — 0,53 с; 400 тыс. строк с повторным `r` — 0,98 с; 300 тыс. `mergeCell` — 0,76 с. Худший допустимый случай — лист у лимитов, 4999 строк × 30 колонок: без формул 4,0 с, с формулой 9,0 с (две книги).

**Остаток (INFO):** строки с повторным или убывающим `r` openpyxl пропускает молча. Excel таких файлов не пишет, их число ограничено подсчётом `row`.

**Цикл 2 (68d7bf9):** FAIL (security:failed) — https://github.com/shakirena/ai-waiter/issues/65#issuecomment-6190553507; findings CRITICAL 0, HIGH 1, MEDIUM 0, LOW 0, INFO 4. Закрыты HIGH цикла 1 и оба LOW. Новый HIGH: подсчёт тегов обходится префиксом не из ASCII. Исправлено в fix(#65) (цикл 3):
- `_START_TAG` считает любую разметку, кроме `</`: префикс и имя — любые байты, кроме разделителей (`<é:row>` даёт `row`). `<?…`, `<!--…`, CDATA считаются как «прочие» с пустым именем. Перед подсчётом убираются нулевые байты, поэтому лист в UTF-16 считается так же, как в UTF-8. Expat читает только ASCII-совместимые кодировки и UTF-16.
- openpyxl разбирает как ячейку любой дочерний элемент `row`. Поэтому `v`, `f`, `is`, `t` и т. п. сверх 3 на элемент `c` считаются «прочими», лимит 20 000.
- `openpyxl>=3.1,<3.2` (`uv.lock`); тест, что у `ReadOnlyWorksheet` есть `_worksheet_path`.
- `MAX_SHEET_CELLS` = 5000 × `MAX_COLUMNS` (250 000), как в CSV. Худший допустимый лист 4999 × 50: без формул 5,2 с, с формулой 9,4 с.
- Замеры атак: 1 млн `<é:c>` в одной строке — 0,86 с (`unsafe_archive`); лист UTF-16 с 400 тыс. повторных `r` — 1,7 с (`too_many_rows`); `<é:row>` с повторным `r` и 1 млн `<v/>` без `c` отвергаются проверкой сжатия или подсчётом.
