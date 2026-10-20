# Test Cases: Story #64 — Разбор CSV-файла меню в снимок с построчным отчётом ошибок

**Feature:** #8 «Импорт меню из CSV/XLSX» (story #64, AC-4)
**Spec:** docs/specs/feature-8-menu-import.md (раздел «Формат файла», FR-5, NFR-4, NFR-6, NFR-7, NFR-10, AC-4)
**Arch:** docs/arch/feature-8-menu-import.md (ADR-8.2, ADR-8.7)
**Created:** 2026-10-19

Обозначения: **Авто** — тест в `backend/tests/...`; **Ручной** — шаги вручную; **Статус прогона** — прогон qa-lead 2026-10-19: полный `uv run pytest -q --cov=app` — 1669 passed, 3 skipped (тесты настоящего Redis), покрытие `app` 100%.

AC story: **Given** CSV UTF-8 с BOM, разделитель `;`, цены с запятой, строка 4 — цена `abc`, строка 7 повторяет `external_id` строки 3 / **When** файл разбирается / **Then** ошибки «строка 4, колонка `price_default`: …» и «строка 7, колонка `external_id`: повтор (строка 3)», снимка нет; исправленный файл даёт `Decimal("4.50")`.

Код: `app/menu_sync/files/__init__.py` (`detect_format`, `parse_menu_bytes`, `read_menu_file`, `locate_issues`), `files/format.py` (`parse_header`, `cell_to_*`, `rows_to_snapshot`), `files/csv_reader.py` (`read_csv_table`, `detect_delimiter`). Синтетический пример — `backend/tests/fixtures/menu/menu_valid.csv`. БД не нужна. Номер строки — физическая строка файла (заголовок = 1).

---

## TC-64-001: Ошибки с номером строки и колонкой, снимок не возвращается

**Priority:** Critical
**Type:** Negative
**AC:** AC-4 (ошибки строк 4 и 7, снимка нет)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_ac64_errors_with_rows_and_no_snapshot`; `tests/test_menu_sync_cli.py::test_ac64_check_reports_row_4_price_and_row_7_duplicate_of_row_3`.
**Статус прогона:** PASS

### Preconditions
- CSV UTF-8 с BOM, разделитель `;`, 6 строк данных: строка 4 — `price_default = abc`, строка 7 — `external_id` строки 3.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `parse_menu_bytes(data, "menu.csv")` | `file_format = csv`, `snapshot = None`, `rows_total = 6` |
| 2 | Проверить проблемы | Ровно две: `(4, price_default, invalid_money)` со значением `abc`; `(7, external_id, duplicate_external_id)` |
| 3 | Текст второй проблемы | Содержит «повтор» и «строка 3» |
| 4 | `python -m app.menu_sync check FILE` | Код 2; в выводе «строка 4», «price_default», «строка 7», «повтор (строка 3)» |

---

## TC-64-002: Исправленный файл даёт снимок с Decimal("4.50")

**Priority:** Critical
**Type:** Functional
**AC:** AC-4 (исправленный файл → `Decimal("4.50")`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_ac64_fixed_file_gives_snapshot_with_decimal_comma`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Исправить строки 4 и 7, разобрать снова | Проблем нет, снимок есть |
| 2 | Цена позиции из `4,50` | `Decimal("4.50")`; `1,5` → `Decimal("1.50")` |
| 3 | `item_rows` | Каждый `external_id` сопоставлен с физической строкой (2…7) |

---

## TC-64-003: Синтетический пример, разделители и BOM

**Priority:** High
**Type:** Functional
**AC:** AC-4 (BOM, `;`); FR-5 spec (разделитель `,` или `;` по заголовку, BOM допускается)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_valid_fixture_parses_completely`, `test_comma_and_semicolon_files_give_same_snapshot`, `test_bom_is_optional`, `test_detect_delimiter`, `test_read_csv_table_returns_typed_table`, `test_optional_columns_values`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `read_menu_file(menu_valid.csv)` | Все позиции и категории, проблем нет |
| 2 | Тот же файл с `,` и с `;` (и десятичной запятой) | Одинаковые снимки |
| 3 | С BOM и без | Одинаковый результат |

---

## TC-64-004: Кодировка, кавычки, пустой файл, неизвестный формат

**Priority:** High
**Type:** Negative
**AC:** FR-5 spec (только UTF-8, подсказка «Сохраните как “CSV UTF-8”»; кавычки RFC 4180)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_cp1251_is_encoding_error`, `test_utf16_is_encoding_error`, `test_unclosed_quote_is_format_error`, `test_empty_file_and_header_only`, `test_detect_format`, `test_unsupported_format`, `test_damaged_xlsx_is_unsupported_format`, `test_read_menu_file_missing_raises`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Файл в cp1251, в UTF-16 | `encoding` с подсказкой сохранить как «CSV UTF-8» |
| 2 | Незакрытая кавычка | `unsupported_format` с номером строки |
| 3 | Пустой файл; только заголовок | `empty_snapshot` |
| 4 | Файл `.txt`/`.xls`; повреждённый `.xlsx` | `unsupported_format` |

---

## TC-64-005: Заголовок — регистр, порядок, #-колонки, неизвестные и повторы

**Priority:** High
**Type:** Functional / Negative
**AC:** FR-5 spec (колонки без учёта регистра, `#…` игнорируются, иная неизвестная — `unknown_column`, повтор — `duplicate_column`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_header_names_case_and_spaces_any_order`, `test_comment_columns_are_ignored`, `test_header_errors`, `test_all_header_errors_collected`, `test_too_many_tier_columns`, `test_unnamed_column_allowed_only_when_empty`, `test_blank_lines_before_header_shift_header_row`, `test_header_error_from_rows_to_snapshot`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Заголовок ` External_ID `, колонки в любом порядке | Принимается |
| 2 | Колонка `#comment` с любым содержимым | Игнорируется |
| 3 | `is_avalable`, повтор `name`, нет `price_default`, `price_VIP` | `unknown_column`, `duplicate_column`, `required`, `invalid_tier` — все сразу |
| 4 | Больше 10 колонок тарифов | Ошибка лимита тарифов |
| 5 | Колонка без имени, пустая во всех строках / со значением | Принимается / `unknown_column` («колонка N») |

---

## TC-64-006: Деньги в ячейках CSV

**Priority:** High
**Type:** Negative
**AC:** AC-4 (цена `abc`); spec «Формат файла» (десятичная запятая только при `;`, без разделителей тысяч, ≤ 2 знаков); NFR-4 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_price_cell_errors`, `test_decimal_comma_not_allowed_with_comma_delimiter`, `test_thousands_separator_rejected_with_semicolon`, `test_optional_tier_empty_means_no_tier_and_errors_use_tier_column`, `test_cell_to_money`, `test_cell_to_money_rejects`, `test_zero_price_is_not_reported_by_file_parser`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `abc`, `-1`, `1e2`, `8.505`, пусто в `price_default` | Ошибка с колонкой `price_default` и строкой |
| 2 | `8,50` при разделителе `,` | Не принимается как цена |
| 3 | `1 000,00` или `1.000,00` при `;` | Ошибка |
| 4 | Пустая `price_vip` | У позиции нет тарифа `vip`, ошибки нет |
| 5 | Цена `0` | Разборщик не сообщает (`zero_price` даёт `check_snapshot`) |

---

## TC-64-007: external_id и категории

**Priority:** High
**Type:** Functional / Negative
**AC:** AC-4 (повтор `external_id` с номером первой строки); spec «Формат файла» (`007` и `7` — разные)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_leading_zeros_kept_in_external_id`, `test_duplicate_external_id_reports_both_rows_and_all_repeats`, `test_category_conflict_name_and_sort_key`, `test_category_without_sort_key_column_defaults_to_empty`, `test_category_model_errors_point_to_first_row_and_category_column`, `test_too_many_categories`, `test_cell_to_external_id`, `test_cell_to_external_id_rejects`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Позиции `007` и `7` | Две разные позиции |
| 2 | Третий повтор `external_id` | Каждый повтор указывает на первую строку |
| 3 | Одна категория с разными `category_name`/`category_sort_key` в строках | Ошибка с номером строки расхождения |
| 4 | Ошибка модели категории | Строка — первая строка категории, колонка `category_*` |

---

## TC-64-008: Колонка is_available

**Priority:** High
**Type:** Functional
**AC:** spec «Формат файла» (нет колонки — наличие не меняется; колонка есть — значение обязательно; `1/0`, `true/false`, `yes/no`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_without_is_available_column_availability_untouched`, `test_is_available_values`, `test_is_available_column_present_value_required`, `test_cell_to_bool`, `test_cell_to_bool_rejects`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Файл без `is_available` | `has_availability = false`, у позиций `None` |
| 2 | `1`, `0`, `TRUE`, `no`, `Yes` | `True`/`False` |
| 3 | Пустая ячейка или `maybe` при наличии колонки | Ошибка со строкой и колонкой `is_available` |

---

## TC-64-009: Физические номера строк и сбор всех ошибок

**Priority:** Medium
**Type:** Functional
**AC:** AC-4 (номер строки); FR-5 spec (номер физической строки)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_quotes_and_newlines_keep_physical_row_numbers`, `test_short_row_missing_cells_are_empty`, `test_all_row_errors_collected_in_row_order`, `test_valid_rows_are_still_validated_when_others_fail`, `test_required_and_length_errors`, `test_optional_columns_validated_by_snapshot_model`, `test_file_column_mapping`, `test_locate_issues_adds_rows_by_external_id`, `test_delimiter_only_rows_between_data_are_skipped`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Значение в кавычках с переводом строки, пустые строки между данными | Номера последующих строк — физические |
| 2 | Ошибки в нескольких строках | Все собраны, по порядку строк |
| 3 | Ошибка модели снимка `prices.vip` | Колонка файла `price_vip` |
| 4 | `locate_issues` для `currency_mismatch` | Добавлены строка и колонка файла |

---

## TC-64-010: Лимиты файла и защита от DoS

**Priority:** High
**Type:** Security
**AC:** ADR-8.2, ADR-8.7 (5 МБ, 5000 строк, 50 колонок, 1000 символов); NFR-6 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_parse_bytes_over_limit`, `test_read_menu_file_checks_size_before_reading`, `test_read_menu_file_exactly_at_limit_is_read`, `test_read_menu_file_grown_after_stat`, `test_max_data_rows_allowed_and_one_more_rejected`, `test_rows_to_snapshot_checks_row_limit_itself`, `test_too_many_columns_in_csv`, `test_parse_header_too_many_columns_directly`, `test_cell_over_limit_value_truncated_in_report`, `test_issue_list_is_limited`, `test_file_of_newlines_rejected_without_reading_it_all`, `test_blank_records_after_header_are_limited`, `test_header_searched_only_in_first_records`, `test_overlong_physical_line_rejected_before_csv`, `test_longest_legitimate_cell_is_not_cut_by_line_limit`, `test_file_of_delimiters_only_has_no_header`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Файл > 5 МБ | `too_large` по `stat`, файл не читается |
| 2 | Ровно 5 МБ; файл вырос после `stat` | Читается / читается не больше лимита + 1 байт, отказ |
| 3 | 5000 строк данных / 5001 | Принимается / `too_many_rows` |
| 4 | 51 колонка; ячейка 1001 символ | Ошибка; значение в отчёте ≤ 60 символов |
| 5 | 5 МБ из `\n`, строк из `,`/`;` | Быстрый отказ, заголовок ищется только в первых 100 записях |
| 6 | Сверхдлинная физическая строка | `too_long` до разбора `csv` |
| 7 | > 100 ошибок | 100 в отчёте, `issues_truncated` |

---

## TC-64-011: Управляющие символы в ячейках

**Priority:** High
**Type:** Security
**AC:** NFR-6 spec (управляющие символы — ошибка; названия — данные, не инструкции), ТЗ AI-3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_csv.py::test_control_char_nul_in_cell`, `test_quoted_name_with_newline_is_control_chars_error`, `test_cell_to_text`, `test_cell_to_text_rejects`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `NUL` в ячейке | Ошибка со строкой и колонкой |
| 2 | Перевод строки внутри названия в кавычках | Ошибка «управляющие символы» |
| 3 | Пробелы по краям; пустая строка | Обрезаются; пустое = «нет значения» |

---

## TC-64-012: Граница импортов пакета files

**Priority:** Medium
**Type:** Functional (архитектура)
**AC:** NFR-10 spec (`app/menu_sync/files/**` без SQLAlchemy, `app.db`, `app.models`, кроме `enums`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_import_boundaries.py::test_menu_sync_files_do_not_import_database`, `test_files_boundary_scanner_detects_database_imports`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Просканировать импорты `app/menu_sync/files/**` | Нет `sqlalchemy`, `app.db`, `app.models.*` кроме `app.models.enums` |

---

## TC-64-013: Описание формата файла в README

**Priority:** Low
**Type:** Functional (документация)
**AC:** FR-5 spec (описание формата для администратора — в README)
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет.
**Статус прогона:** PASS (ручная проверка документа, 2026-10-19)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть README, раздел «Импорт меню из файла» → «Формат файла меню» | Таблица колонок совпадает со spec; описаны деньги, десятичная запятая, кодировка, `#`-колонки, лимиты; ссылка на синтетический пример |
| 2 | Проверить пример | Только вымышленные данные |

---

## Related TCs
- TC-61-001, TC-61-004 (проверки модели снимка, которые разборщик переводит в строки файла)
- TC-65-001 (XLSX даёт тот же снимок)
- TC-66-002, TC-66-003 (`check` и `import` печатают этот отчёт)
- TC-67-001 (выгрузка кассы проходит `check`)
