# Test Cases: Story #66 — CLI-команда импорта меню из файла с режимом --dry-run

**Feature:** #8 «Импорт меню из CSV/XLSX» (story #66, AC-6)
**Spec:** docs/specs/feature-8-menu-import.md (FR-7, NFR-6, NFR-7, AC-6)
**Arch:** docs/arch/feature-8-menu-import.md (ADR-8.6)
**Created:** 2026-10-19

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — прогон qa-lead 2026-10-19: полный `uv run pytest -q --cov=app` — 1669 passed, 3 skipped (тесты настоящего Redis), покрытие `app` 100%.

AC story: **Given** миграции применены, есть заведение и синтетический `menu_valid.csv` / **When** `python -m app.menu_sync import FILE --tenant UUID` с `--dry-run`, затем без него, затем повторно / **Then** план без изменений БД (код 0), затем `applied` (код 0), затем `unchanged` (код 0). По spec AC-6 дополнительно: файл с ошибками в данных — код 2 без изменений меню, занятая блокировка — код 3.

Коды выхода (FR-7): 0 — успех; 1 — окружение (файл, конфигурация, БД, нет заведения, аргументы); 2 — ошибки в данных; 3 — синхронизация уже идёт. Код: `app/menu_sync/__main__.py`.

---

## TC-66-001: dry-run → applied → unchanged, код 0

**Priority:** Critical
**Type:** Functional
**AC:** AC-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_cli.py::test_ac66_dry_run_then_applied_then_unchanged`; `tests/test_menu_sync_cli.py::test_import_applied_prints_counts`, `test_import_passes_flags_and_dry_run_label`, `test_import_unchanged_is_exit_0_without_counts`.
**Статус прогона:** PASS

### Preconditions
- `alembic upgrade head`, заведение создано, `DATABASE_URL` в `.env`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `python -m app.menu_sync import menu_valid.csv --tenant <uuid> --dry-run` | Код 0; «пробный прогон», план со счётчиками; меню и `menu_sync_runs` пусты |
| 2 | То же без `--dry-run` | Код 0; статус `applied`; позиции созданы; запись `applied` с `source = file`, `source_ref = menu_valid.csv` |
| 3 | Ещё раз тот же файл | Код 0; статус `unchanged`; меню не тронуто; запись `unchanged` |
| 4 | Ещё раз с `--force` | Код 0; `applied` |

---

## TC-66-002: check без БД и .env

**Priority:** High
**Type:** Functional
**AC:** FR-7 spec (`check FILE [--sheet] [--json]` — без БД)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_sync_cli.py::test_check_valid_csv_without_database`, `test_check_without_availability_column_says_it_is_kept`, `test_check_json_valid`, `test_check_xlsx_with_sheet`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `check menu_valid.csv` без `DATABASE_URL` | Код 0, число позиций и категорий |
| 2 | Файл без колонки `is_available` | Сообщение, что наличие не меняется |
| 3 | `check FILE.xlsx --sheet Data` | Код 0 |

---

## TC-66-003: Ошибки в данных — код 2, rejected, меню не изменено

**Priority:** Critical
**Type:** Negative
**AC:** AC-6 (spec: файл с ошибками — код 2 без изменений меню); FR-7 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_cli.py::test_parse_errors_are_rejected_and_journaled`, `test_snapshot_errors_get_file_rows_in_journal`, `test_truncated_issues_are_counted_in_journal`, `test_empty_file_is_always_rejected`; `tests/test_menu_sync_cli.py::test_check_errors_are_exit_2_with_rows`, `test_check_unsupported_format_is_exit_2`, `test_check_too_many_issues_reports_truncated`, `test_import_rejected_is_journaled_with_rows_and_exit_2`, `test_import_rejected_dry_run_is_not_journaled`, `test_import_parse_errors_are_journaled_without_apply`, `test_import_dry_run_with_parse_errors_does_not_need_database`, `test_import_warnings_get_file_rows`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `import` файла с ошибкой цены | Код 2; меню не изменилось; запись `rejected` с проблемами со строкой и колонкой, `source_ref` — имя без каталога |
| 2 | Файл с позицией в чужой валюте | Код 2; в журнале строка файла у `currency_mismatch` |
| 3 | > 100 ошибок | Код 2; «и ещё N» в выводе и журнале |
| 4 | Пустой файл, в т. ч. с `--allow-mass-hide` | Код 2 |
| 5 | Ошибки разбора с `--dry-run` | Код 2, БД не нужна, журнала нет |
| 6 | `check` файла с ошибками / `.txt` | Код 2 |

---

## TC-66-004: Массовое скрытие и --allow-mass-hide

**Priority:** High
**Type:** Negative
**AC:** FR-3, FR-7 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_cli.py::test_mass_hide_needs_explicit_permission`; `tests/test_menu_sync_cli.py::test_all_import_options_are_parsed`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Применено меню из ≥ 10 позиций; файл без большей их части | Код 2, `mass_hide`, меню не изменилось |
| 2 | То же с `--allow-mass-hide` | Код 0, позиции скрыты |

---

## TC-66-005: Блокировка занята — код 3

**Priority:** High
**Type:** Negative (параллельность)
**AC:** AC-6 (spec: занятая блокировка — код 3); NFR-3 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_cli.py::test_busy_lock_is_exit_3`; `tests/test_menu_sync_cli.py::test_import_busy_is_exit_3`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Удерживать advisory lock заведения во втором соединении; запустить `import` | Код 3 без ожидания; меню не изменилось |

---

## TC-66-006: Ошибки окружения и аргументов — код 1

**Priority:** High
**Type:** Negative
**AC:** FR-7 spec (код 1 — нет файла, конфигурации, БД, заведения)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_cli.py::test_unknown_tenant_is_exit_1`; `tests/test_menu_sync_cli.py::test_argument_errors_are_exit_1`, `test_exit_codes_are_stable`, `test_check_missing_file_is_exit_1`, `test_check_directory_is_exit_1`, `test_check_unreadable_file_is_exit_1`, `test_import_missing_file_is_exit_1`, `test_import_config_error_is_exit_1_without_value`, `test_import_without_database_url_is_exit_1`, `test_import_unknown_tenant_is_exit_1`, `test_import_parse_errors_for_unknown_tenant_is_exit_1`, `test_not_regular_file_is_exit_1_without_reading`, `test_null_device_is_not_read`, `test_stat_error_is_exit_1`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Нет подкоманды; `import` без `--tenant`; `--tenant not-a-uuid` | Код 1 (не 2 argparse) |
| 2 | Нет файла; путь — каталог; нет прав; устройство (`NUL`, `/dev/null`) | Код 1, файл не читается |
| 3 | Нет `DATABASE_URL`; неверная конфигурация | Код 1, значение переменной не печатается |
| 4 | `--tenant` несуществующего заведения (в т. ч. с ошибками в файле) | Код 1, без ошибки FK |

---

## TC-66-007: Пароль БД и путь не раскрываются

**Priority:** Critical
**Type:** Security
**AC:** NFR-6 spec (в вывод и журнал не попадают пароль БД и путь к файлу)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_cli.py::test_wrong_password_is_not_shown`; `tests/test_menu_sync_cli.py::test_import_database_error_hides_password`, `test_output_never_contains_database_url`, `test_mask_url_passwords`, `test_argument_error_hides_password`, `test_unparsable_database_url_is_exit_1_without_password`, `test_database_error_text_is_escaped_and_limited`, `test_control_characters_in_path_are_escaped`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `import … --database-url` с неверным паролем | Код 1; пароля и строки подключения нет в stdout/stderr |
| 2 | Ошибка разбора аргументов с `--database-url` | Пароль замаскирован |
| 3 | Неразбираемый `DATABASE_URL` | Код 1, без пароля |
| 4 | Путь к файлу с ESC-последовательностью | В выводе — имя файла без каталога, невидимые символы экранированы |

---

## TC-66-008: Вывод --json и устойчивость к кодировке консоли

**Priority:** Medium
**Type:** Functional
**AC:** FR-7 spec (`--json`); NFR-7 spec (одинаково на Windows и Linux)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_sync_cli.py::test_check_json`, `test_import_json`, `test_import_json_parse_errors_dry_run`, `test_tolerant_output_reconfigures_text_streams`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `check FILE --json`, `import … --json` | Корректный JSON (ASCII), статус, счётчики, проблемы |
| 2 | Вывод в файл в кодировке cp1251 с символом `ə` | Команда не падает (`backslashreplace`) |

---

## TC-66-009: Нет колонки is_available — наличие не меняется

**Priority:** High
**Type:** Functional
**AC:** spec «Формат файла» (нет колонки — наличие не меняется)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_cli.py::test_missing_availability_column_keeps_availability`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Позиция снята с продажи (`is_available = false`); `import` файла без колонки `is_available` | Код 0, `is_available` остаётся `false` |

---

## TC-66-010: Запуск при APP_ENV=prod, точка входа, справка

**Priority:** Medium
**Type:** Functional
**AC:** FR-7 spec (разрешено при `APP_ENV=prod`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_sync_cli.py::test_import_is_allowed_in_prod`, `test_help_is_exit_0`, `test_tenant_uuid_accepts_spaces_and_upper_case`, `test_load_settings_prefers_argument`, `test_module_entry_point_in_subprocess`, `test_module_guard_raises_system_exit_with_main_code`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `APP_ENV=prod`, `import` | Выполняется (в отличие от сида) |
| 2 | `python -m app.menu_sync --help` в отдельном процессе | Код 0, справка по-русски |
| 3 | `--tenant " ABCD…"` (пробелы, верхний регистр) | UUID принят |
| 4 | `--database-url` и `DATABASE_URL` одновременно | Используется аргумент |

---

## TC-66-011: README — команда импорта, коды выхода, расписание

**Priority:** Low
**Type:** Functional (документация)
**AC:** FR-7 spec; ТЗ 9.2
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет.
**Статус прогона:** PASS (ручная проверка документа, 2026-10-19)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | README, «Команда импорта» | Параметры `check`/`import`, коды 0–3, пример отчёта, команды для PowerShell и Linux |
| 2 | README, «Импорт по расписанию» | Планировщик заданий Windows и cron с тем же CLI; `DATABASE_URL` из `.env`, без `--database-url` в аргументах задания |
| 3 | Проверить отсутствие IP, ключей, данных заведения | Только плейсхолдеры `<UUID>`, `<каталог ai-waiter>` |

---

## Related TCs
- TC-62-001, TC-62-006, TC-62-008 (применение, mass-hide, lock)
- TC-63-001, TC-63-004, TC-63-006 (журнал `unchanged`/`rejected`, имя файла)
- TC-64-001 (`check` печатает строки 4 и 7)
- TC-48-003 (ошибка подключения без пароля)
- TC-53-003 (сид при `APP_ENV=prod` отказывает, импорт меню — нет)
