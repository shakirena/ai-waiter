# Test Cases: Story #61 — Снимок меню: модель с проверкой согласованности

**Feature:** #8 «Импорт меню из CSV/XLSX» (story #61, AC-1)
**Spec:** docs/specs/feature-8-menu-import.md (FR-1, NFR-4, NFR-6, NFR-10, AC-1)
**Arch:** docs/arch/feature-8-menu-import.md (ADR-8.1, ADR-8.2, ADR-8.3, ADR-8.5)
**Created:** 2026-10-19

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — прогон qa-lead 2026-10-19: полный `uv run pytest -q --cov=app` — 1669 passed, 3 skipped (тесты настоящего Redis), покрытие `app` 100%.

AC story: **Given** заведение с валютой AZN и снимок из трёх позиций (у одной нет цены `default`, у второй валюта USD, третья ссылается на категорию, которой нет в снимке) / **When** снимок проверяется / **Then** ровно три ошибки (среди них `currency_mismatch`), каждая с `external_id` позиции, полем и причиной на русском; корректный снимок того же размера проходит без ошибок, и его хеш не зависит от порядка позиций.

Код: `app/schemas/money.py` (`MoneyStr`, `parse_money`, `format_money`), `app/menu_sync/snapshot.py` (`MenuSnapshot`, `parse_snapshot`, `check_snapshot`, `resolve_currency`, `snapshot_hash`), `app/menu_sync/report.py` (`SyncIssue`, `limit_issues`, `MenuSyncReport`). БД не нужна.

---

## TC-61-001: Три ошибки снимка собираются за одну проверку

**Priority:** Critical
**Type:** Functional / Negative
**AC:** AC-1 (ровно три ошибки, среди них `currency_mismatch`, с `external_id`, полем и причиной на русском)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_snapshot.py::test_ac61_three_errors_at_once`, `test_shape_error_does_not_hide_cross_errors_of_other_items`.
**Статус прогона:** PASS

### Preconditions
- Валюта заведения — `AZN`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `parse_snapshot` для снимка: позиция `101` только с тарифом `vip`, позиция `102` с `currency = "USD"`, позиция `103` с `category_external_id = "77"` (категории нет) | Снимок не возвращается (`None`), ровно 3 проблемы, все `severity = error` |
| 2 | Проверить проблему позиции `101` | `code = required`, `column = prices.default` |
| 3 | Проверить проблему позиции `102` | `code = currency_mismatch`, `column = currency`, `value = "USD"` |
| 4 | Проверить проблему позиции `103` | `code = unknown_category`, `column = category_external_id`, `value = "77"` |
| 5 | Проверить тексты сообщений | Каждое сообщение — на русском (кириллица) |
| 6 | Ошибка формы у одной позиции и межэлементные ошибки у других | Ошибка формы не скрывает межэлементные проверки остальных позиций |

### Expected Result
Оператор видит все три проблемы сразу, а не по одной за запуск.

---

## TC-61-002: Корректный снимок того же размера проходит, хеш не зависит от порядка

**Priority:** Critical
**Type:** Functional
**AC:** AC-1 (корректный снимок без ошибок; хеш не зависит от порядка позиций)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_snapshot.py::test_ac61_valid_snapshot_of_same_size_has_no_issues`, `test_ac61_valid_snapshot_hash_does_not_depend_on_item_order`, `test_snapshot_json_uses_money_strings`, `test_check_snapshot_on_model_built_in_code`; `tests/test_menu_sync_runs.py::test_hash_does_not_depend_on_order_of_items_categories_and_tiers`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `parse_snapshot` для корректного снимка из трёх позиций, валюта `AZN` | Проблем нет, снимок из 3 позиций |
| 2 | Проверить цены | `Decimal("8.00")`, `Decimal("10.00")`, `Decimal("5.50")` |
| 3 | Проверить необязательные поля | Пустая валюта — `None`, нет `is_available` — `None`, `no` — `False` |
| 4 | `check_snapshot` над моделью, собранной в коде | `[]` |
| 5 | Тот же снимок с позициями в обратном порядке → `snapshot_hash(resolve_currency(...))` | Хеш совпадает, 64 символа `[0-9a-f]` |
| 6 | `model_dump(mode="json")` | Деньги — строки с двумя знаками |

---

## TC-61-003: Тип денег MoneyStr — Decimal без float

**Priority:** Critical
**Type:** Functional / Negative
**AC:** AC-1 (цены снимка); NFR-4 spec (деньги `Decimal`, без `float`, ≤ 2 знаков, ≥ 0, ≤ `99999999.99`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_money.py::test_parse_money_accepts`, `test_parse_money_rejects`, `test_format_money`, `test_format_money_rejects`, `test_money_str_field_python_and_json`, `test_money_str_field_rejects_json_number`, `test_money_str_field_accepts_json_string`; `tests/test_menu_snapshot.py::test_float_price_value_is_shown`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `parse_money("8")`, `"8.5"`, `"8.50"`, `Decimal("8.500")`, `"99999999.99"` | `Decimal` с двумя знаками, без округления |
| 2 | `parse_money(8.5)` (float), `True`, `"8.505"`, `"-1"`, `"1e3"`, `"1 000"`, `"100000000.00"`, `"１２"` (не ASCII) | `MoneyError` с причиной `float` / `invalid` / `too_many_decimals` / `negative` / `too_large` |
| 3 | `format_money(Decimal("4.5"))` | `"4.50"` |
| 4 | Поле `MoneyStr` в модели: JSON-число | Отклоняется |
| 5 | Поле `MoneyStr`: JSON-строка `"4.50"`, сериализация в JSON | Принимается; в JSON — строка `"4.50"` |

---

## TC-61-004: Ошибки формы снимка, дубли, тарифы, пустой снимок, лимиты

**Priority:** High
**Type:** Negative
**AC:** AC-1 (проверка собирает все проблемы); FR-1 spec (повтор `external_id`, недопустимый тариф, длины и шаблоны, `empty_snapshot`); ADR-8.2 (лимиты 500 категорий / 5000 позиций / 10 тарифов)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_snapshot.py::test_shape_errors`, `test_category_error_is_marked_in_message`, `test_invalid_tier_lists_all_bad_names`, `test_strings_are_stripped_and_empty_station_is_none`, `test_models_are_frozen`, `test_limits_categories_and_items`, `test_non_mapping_data`, `test_empty_snapshot_is_rejected`, `test_duplicate_external_ids`, `test_reference_to_invalid_category_is_not_unknown`, `test_all_items_invalid_is_not_reported_as_empty`, `test_cross_checks_skipped_for_broken_structure`, `test_issues_from_validation_error_with_odd_raw_data`, `test_unmapped_pydantic_error_gets_generic_reason`, `test_invalid_category_with_non_string_id`, `test_parse_snapshot_does_not_mutate_input`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Неизвестный ключ (`extra="forbid"`), пустое `name`, слишком длинный `external_id`, неверный шаблон тарифа | Проблема с полем и причиной на русском |
| 2 | Ошибка в категории | Сообщение с префиксом «категория: » |
| 3 | Несколько недопустимых имён тарифов | Перечислены все, в `value`, а не в `message` |
| 4 | Повтор `external_id` позиции и категории | `duplicate_external_id` |
| 5 | Снимок без позиций | `empty_snapshot` |
| 6 | Все позиции с ошибками формы | Нет ложного `empty_snapshot` |
| 7 | Ссылка на категорию, у которой ошибка формы | Нет ложного `unknown_category` |
| 8 | Снимок не словарь / превышен лимит категорий или позиций | Ошибка структуры, межэлементные проверки пропущены |
| 9 | Повторный вызов на том же входе | Входные данные не изменены; модели неизменяемы (frozen) |

---

## TC-61-005: Валюта заведения и нулевая цена

**Priority:** High
**Type:** Functional
**AC:** AC-1 (`currency_mismatch`); ADR-8.3 (чужая валюта отклоняет весь снимок, пустая — валюта заведения); FR-1 spec (`zero_price` — предупреждение)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_snapshot.py::test_matching_currency_is_accepted`, `test_resolve_currency_fills_only_missing`, `test_zero_price_is_warning_and_snapshot_is_returned`; `tests/test_menu_sync_runs.py::test_hash_after_resolve_currency_equals_explicit_currency`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Позиция с `currency = "AZN"` в заведении `AZN` | Без проблем |
| 2 | `resolve_currency(snapshot, "AZN")` | Пустая валюта заполнена `AZN`, явная не тронута |
| 3 | Хеш снимка с пустой валютой после `resolve_currency` и со явной `AZN` | Совпадает |
| 4 | Цена `0.00` | Предупреждение `zero_price` (`severity = warning`), снимок возвращается |

---

## TC-61-006: Безопасность текста — управляющие символы и санитизация отчёта

**Priority:** High
**Type:** Security
**AC:** AC-1 (причины в отчёте); NFR-6 spec (названия — данные, не инструкции; управляющие символы отвергаются; значения в отчёте ≤ 60 символов); ТЗ AI-3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_snapshot.py::test_invisible_characters_are_rejected`, `test_visible_text_is_accepted`, `test_issue_value_formatting`, `test_sync_issue_truncates_value_and_to_dict_skips_none`, `test_external_id_limit_matches_snapshot_limit`, `test_sync_issue_truncates_huge_external_id`, `test_sync_issue_escapes_terminal_sequence_in_external_id`, `test_sync_issue_sanitizes_message_and_column`, `test_parse_snapshot_huge_external_id_is_truncated_in_report`, `test_parse_snapshot_external_id_with_escape_sequence`, `test_parse_snapshot_long_tier_names_with_escape_are_not_in_message`, `test_parse_snapshot_unknown_key_with_escape_is_sanitized_in_column`, `test_all_issue_dicts_are_safe_for_malicious_snapshot`, `test_escape_invisible`, `test_safe_text_limits_after_escaping`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | В `name` — `\x00`, `\x1b[31m`, U+0085, U+2028, bidi U+202E, zero-width U+200B, BOM | Ошибка проверки |
| 2 | Название на AZ/RU с `ə`, `ğ`, `ё`, эмодзи | Принимается |
| 3 | `external_id` 10 000 символов, с ESC-последовательностью | В отчёте обрезан до 64, ESC экранирован |
| 4 | Неизвестный ключ с ESC | `column` экранирован и обрезан до 100 |
| 5 | Длинные имена тарифов с ESC | В `message` не попадают |
| 6 | Любой `SyncIssue.to_dict()` вредоносного снимка | `message` ≤ 500, `value` ≤ 60, нет невидимых символов |

---

## TC-61-007: Отчёт синхронизации — ограничение числа проблем

**Priority:** Medium
**Type:** Functional
**AC:** FR-3 spec (полный список проблем до 100 и «ещё N»)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_snapshot.py::test_limit_issues_orders_and_truncates`, `test_has_errors`, `test_menu_sync_report_dicts`, `test_menu_sync_report_run_id_is_string`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `limit_issues` для 150 проблем | 100 проблем (ошибки раньше предупреждений), остаток 50 |
| 2 | `has_errors` для списка только с предупреждениями | `False` |
| 3 | `MenuSyncReport.to_dict()` | Счётчики, статус, `run_id` строкой |

---

## TC-61-008: Границы импортов app.menu_sync и app.schemas

**Priority:** Medium
**Type:** Functional (архитектура)
**AC:** NFR-10 spec (`app/menu_sync/**` не импортирует FastAPI; `app/core/**` не импортирует `app.menu_sync`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_import_boundaries.py::test_menu_sync_does_not_import_fastapi_or_api`, `test_core_does_not_import_menu_sync`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Просканировать импорты `app/menu_sync/**`, `app/schemas/**` | Нет `fastapi`, `app.api` |
| 2 | Просканировать импорты `app/core/**` | Нет `app.menu_sync` |

---

## Related TCs
- TC-50-001, TC-50-004 (длины, шаблоны и уникальность `0002_menu`, которым следует модель снимка)
- TC-62-005 (`currency_mismatch` отклоняет весь снимок при применении)
- TC-63-002 (хеш снимка)
- TC-64-001 (строки и колонки файла у проблем снимка)
