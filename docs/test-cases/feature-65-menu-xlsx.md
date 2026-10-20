# Test Cases: Story #65 — Разбор XLSX-файла меню в снимок

**Feature:** #8 «Импорт меню из CSV/XLSX» (story #65, AC-5)
**Spec:** docs/specs/feature-8-menu-import.md (раздел «Формат файла», FR-6, NFR-4, NFR-6, NFR-7, NFR-10, AC-5)
**Arch:** docs/arch/feature-8-menu-import.md (ADR-8.2, ADR-8.7)
**Created:** 2026-10-19

Обозначения: **Авто** — тест в `backend/tests/...`; **Ручной** — шаги вручную; **Статус прогона** — прогон qa-lead 2026-10-19: полный `uv run pytest -q --cov=app` — 1669 passed, 3 skipped (тесты настоящего Redis), покрытие `app` 100%.

AC story: **Given** XLSX с данными синтетического CSV-примера на втором листе `Menu` (первый — другой), цены числами / **When** разбор без указания листа / **Then** выбран лист `Menu`, снимок совпадает со снимком CSV-примера, цены `Decimal` с двумя знаками без двоичной погрешности.

Код: `app/menu_sync/files/xlsx_reader.py` (`check_xlsx_archive`, `read_xlsx_table`; `openpyxl` только здесь, `defusedxml`). Книги собираются в тестах; БД не нужна.

---

## TC-65-001: Лист Menu выбран, снимок совпадает с CSV-примером

**Priority:** Critical
**Type:** Functional
**AC:** AC-5
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_ac65_menu_sheet_matches_csv_example`.
**Статус прогона:** PASS

### Preconditions
- Книга: лист 1 `Prices` (посторонние данные), лист 2 `Menu` — строки `menu_valid.csv`, цены числами (`float`).

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `parse_menu_bytes(book, "menu.xlsx")` без `sheet` | Проблем нет, `file_format = xlsx` |
| 2 | Сравнить со снимком `read_menu_file(menu_valid.csv)` | Снимки равны, равны `item_rows` и `rows_total` |
| 3 | Проверить цены | Все `Decimal` с экспонентой −2: `4.50`, `7.80`, `6.00` |

---

## TC-65-002: Выбор листа — --sheet, menu, первый

**Priority:** High
**Type:** Functional / Negative
**AC:** AC-5 (выбор без указания листа); spec «Формат файла» (лист из `--sheet`, иначе `menu` без учёта регистра, иначе первый)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_without_menu_sheet_first_is_used`, `test_menu_sheet_name_is_case_insensitive`, `test_sheet_argument_exact_then_case_insensitive`, `test_sheet_argument_overrides_menu_sheet`, `test_sheet_argument_exact_name_wins_over_case_insensitive`, `test_sheet_not_found_lists_sheets`, `test_workbook_without_worksheets`, `test_read_menu_file_xlsx_from_disk_with_sheet`; `tests/test_menu_sync_cli.py::test_check_xlsx_with_sheet`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Нет листа `menu` | Берётся первый лист |
| 2 | Лист ` MENU ` | Выбран как `menu` |
| 3 | `sheet="Data"` при наличии `Menu` | Берётся `Data` |
| 4 | `sheet="data"` при листах `Data` и `data` | Точное совпадение важнее |
| 5 | `sheet="Нет"` | `sheet_not_found` с перечнем листов |
| 6 | `check FILE.xlsx --sheet Data` | Код 0 |

---

## TC-65-003: Числа в ячейках — external_id, цены, наличие

**Priority:** High
**Type:** Functional / Negative
**AC:** AC-5 (цены без двоичной погрешности); NFR-4 spec (float через `repr`, шум < 1e-9 округляется, остальное > 2 знаков — ошибка)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_numeric_external_id_without_fraction`, `test_fractional_external_id_is_invalid_id`, `test_text_external_id_keeps_leading_zeros`, `test_numeric_prices_are_exact`, `test_float_noise_from_formula_is_rounded`, `test_price_cell_errors`, `test_bool_and_numbers_in_is_available`, `test_read_xlsx_table_returns_typed_values`; `tests/test_menu_csv.py::test_typed_cells_from_xlsx_like_table`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `external_id` числом `7.0` / `7.5` / текстом `007` | `"7"` / `invalid_id` / `"007"` |
| 2 | Цена `4.5`, `0.1 + 0.2` (шум формулы) | `Decimal("4.50")`, `Decimal("0.30")` |
| 3 | Цена `8.505` | `too_many_decimals` |
| 4 | `is_available` — `TRUE`/`FALSE`, `1`/`0` | `True`/`False` |

---

## TC-65-004: Даты, ошибки Excel, формулы

**Priority:** High
**Type:** Negative
**AC:** spec «Формат файла» (формулы не вычисляются, берутся сохранённые значения; даты и ошибки Excel — `invalid_cell_type`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_date_in_external_id_is_invalid_id`, `test_excel_error_message_names_error`, `test_unknown_excel_error_value_is_not_shown`, `test_known_excel_errors_are_shown`, `test_excel_error_in_external_id_keeps_its_code`, `test_formula_with_cached_value_uses_value`, `test_text_formula_with_cached_value`, `test_formula_without_value_is_reported_with_row_and_column`, `test_formula_without_value_in_comment_column_is_ignored`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Дата в `external_id` или цене | `invalid_cell_type` / `invalid_id` со строкой и колонкой |
| 2 | `#N/A`, `#DIV/0!` в ячейке | `invalid_cell_type`, код ошибки Excel назван; неизвестный код — «ошибка Excel» |
| 3 | Формула с сохранённым значением | Берётся значение |
| 4 | Формула без сохранённого значения | `formula_without_value` со строкой и колонкой; в `#`-колонке игнорируется |

---

## TC-65-005: Заголовок и пустые листы

**Priority:** Medium
**Type:** Negative
**AC:** FR-6 spec (тот же отчёт, что у CSV: лист, строка, колонка)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_value_in_column_without_header_is_error`, `test_header_after_blank_rows_and_gaps_keep_sheet_row_numbers`, `test_header_cell_with_excel_error`, `test_header_formula_without_value`, `test_numeric_header_cell_is_unknown_column`, `test_header_with_empty_cells_between_columns`, `test_empty_sheet`, `test_header_only`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Заголовок после пустых строк | Номера строк — как на листе |
| 2 | Значение в колонке без заголовка | `unknown_column` |
| 3 | Ошибка Excel или число в заголовке | Ошибка «колонка N» / `unknown_column` |
| 4 | Пустой лист; только заголовок | `empty_snapshot` |

---

## TC-65-006: Не-XLSX, макросы, повреждённая книга

**Priority:** Critical
**Type:** Security / Negative
**AC:** spec «Формат файла» (`.xls`, `.xlsm` — `unsupported_format`); ADR-8.7 (макросы отвергаются)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_valid_book_passes_archive_check`, `test_not_a_zip_is_unsupported_format`, `test_zip_without_workbook_is_unsupported_format`, `test_macros_are_rejected`, `test_damaged_workbook_xml_is_unreadable`, `test_sheet_path_unknown_is_unreadable`; `tests/test_menu_csv.py::test_damaged_xlsx_is_unsupported_format`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Файл `.xlsx`, не zip | `unsupported_format` |
| 2 | Zip без `xl/workbook.xml` | `unsupported_format` |
| 3 | Книга с `vbaProject.bin` (любой каталог, регистр) | `unsupported_format` |
| 4 | Повреждённый XML книги | `unsupported_format` с подсказкой пересохранить; текст исключения в отчёт не попадает |

---

## TC-65-007: XXE и XML-бомбы — defusedxml

**Priority:** Critical
**Type:** Security
**AC:** NFR-6 spec (защита от XML-бомб и XXE)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_defusedxml_is_used_by_openpyxl`, `test_xml_entities_are_rejected`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `openpyxl.xml.DEFUSEDXML` | `True` |
| 2 | Лист с `<!DOCTYPE>` и сущностями (внешняя сущность, «billion laughs») | `unsupported_format`, сущности не раскрываются |

---

## TC-65-008: Zip-бомба и лимиты архива

**Priority:** Critical
**Type:** Security
**AC:** ADR-8.7 (распакованный XLSX ≤ 50 МБ, сжатие члена ≤ 100×; проверка до openpyxl)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_zip_bomb_by_compression_ratio`, `test_compression_ratio_limit_is_inclusive`, `test_uncompressed_total_over_limit`, `test_real_size_limit_is_50_mb`, `test_non_sheet_parts_over_byte_limit`, `test_non_sheet_parts_over_tag_limit`, `test_book_over_tag_limit_counts_other_sheets`, `test_book_budget_smaller_than_non_sheet_budget_reports_book`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Член архива со сжатием > 100× | `unsafe_archive` |
| 2 | Сжатие ровно 100× | Принимается |
| 3 | Сумма распакованных > 50 МБ | `unsafe_archive` |
| 4 | Части вне листов > 20 МБ или > 200 000 элементов (под любым именем) | `unsafe_archive` |

---

## TC-65-009: DoS по CPU — строки, ячейки, элементы XML

**Priority:** High
**Type:** Security
**AC:** ADR-8.7; лимиты ADR-8.2 (5000 строк, 50 колонок)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_too_many_rows`, `test_huge_row_number_stops_quickly`, `test_many_blank_formatted_rows_stop_before_parsing`, `test_rows_with_repeated_number_are_counted_before_parsing`, `test_many_rows_with_formatted_cell_in_xfd_stop_at_cell_budget`, `test_sheet_row_limit_is_inclusive`, `test_sheet_xml_limits`, `test_many_merged_cells_rejected_before_parsing`, `test_count_tags_ignores_closing_and_prefixes`, `test_non_ascii_prefix_with_repeated_rows_rejected_before_parsing`, `test_non_ascii_prefix_with_many_cells_in_one_row_rejected_before_parsing`, `test_cell_content_without_cells_counts_as_other`, `test_utf16_sheet_is_counted_and_parsed`, `test_scanned_cells_limit_is_inclusive`, `test_sheet_limits_follow_csv`, `test_value_beyond_max_columns`, `test_formatted_empty_cell_far_right_is_ignored`, `test_sheet_and_tag_limits`, `test_many_row_errors_are_limited`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Строка с `r = 10^12` | `too_many_rows` быстро (доли секунды) |
| 2 | Много пустых отформатированных строк; строки с повторным `r`; много `mergeCell` | Отказ до разбора openpyxl |
| 3 | Ячейка в колонке XFD во многих строках | `too_many_columns` по бюджету ячеек |
| 4 | Теги с префиксом не из ASCII (`<é:row>`), лист в UTF-16 | Считаются так же, обход невозможен |
| 5 | Пустая отформатированная ячейка далеко справа / значение правее 50-й колонки | Игнорируется / `too_many_columns` |
| 6 | > 100 ошибок строк | 100 в отчёте, остаток — `issues_truncated` |

---

## TC-65-010: Книга открывается только для чтения и всегда закрывается; openpyxl изолирован

**Priority:** Medium
**Type:** Functional (ресурсы, архитектура)
**AC:** ADR-8.7 (`read_only=True`, `data_only=True`, закрытие в `finally`); NFR-10 spec (`openpyxl` только в `xlsx_reader.py`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_xlsx.py::test_workbooks_are_opened_read_only_and_closed`, `test_workbook_closed_when_sheet_not_found`, `test_workbooks_closed_on_error_while_reading`, `test_error_before_any_workbook_opened`, `test_read_only_worksheet_has_worksheet_path`; `tests/test_import_boundaries.py::test_restricted_imports_only_in_implementation_packages` (`RESTRICTED["openpyxl"]`).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Разбор корректной книги | Книги открыты с `read_only=True`, после разбора закрыты |
| 2 | Лист не найден / исключение при чтении | Книги закрыты |
| 3 | Просканировать импорты `app/**` | `openpyxl` только в `menu_sync/files/xlsx_reader.py` |

---

## Related TCs
- TC-64-001…TC-64-011 (общий формат колонок и отчёт)
- TC-66-002 (`check FILE.xlsx --sheet`)
