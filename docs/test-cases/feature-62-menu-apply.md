# Test Cases: Story #62 — Применение снимка меню к базе по external_id со скрытием пропавших позиций

**Feature:** #8 «Импорт меню из CSV/XLSX» (story #62, AC-2)
**Spec:** docs/specs/feature-8-menu-import.md (FR-2, FR-3, NFR-1, NFR-2, NFR-3, NFR-5, AC-2)
**Arch:** docs/arch/feature-8-menu-import.md (ADR-8.3, ADR-8.4)
**Created:** 2026-10-19

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — прогон qa-lead 2026-10-19: полный `uv run pytest -q --cov=app` — 1669 passed, 3 skipped (тесты настоящего Redis), покрытие `app` 100%.

AC story: **Given** позиции `1001`, `1002`, `1003` (у `1003` есть `menu_item_meta`), скрытая `1004`, у другого заведения своя `1001` / **When** применяется снимок `1001` (новая цена), `1002`, `1004`, `1005` / **Then** у `1001` новая цена, `1003` скрыта с сохранением meta, `1004` снова видима, `1005` создана, ничего не удалено, чужое заведение не изменилось.

Код: `app/menu_sync/plan.py` (`plan_menu_sync` — чистая функция), `app/menu_sync/service.py` (`apply_menu_snapshot`, `load_current_menu`, advisory lock). Общее предусловие db-тестов: миграции до `head`, `db_session` с откатом.

---

## TC-62-001: Сценарий AC — обновление, скрытие, возврат, создание

**Priority:** Critical
**Type:** Functional
**AC:** AC-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_apply.py::test_ac62_scenario`.
**Статус прогона:** PASS

### Preconditions
- Заведение A: категория, позиции `1001`, `1002`, `1003` (с `menu_item_meta`), `1004` с `is_hidden = true`.
- Заведение B: позиция `1001`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `apply_menu_snapshot(tenant_id=A, …)` со снимком `1001` (новая цена), `1002`, `1004`, `1005` | Статус `applied`, ошибок нет |
| 2 | Проверить `1001` | Новая цена `default` |
| 3 | Проверить `1003` | `is_hidden = true`, строка `menu_item_meta` на месте |
| 4 | Проверить `1004` | `is_hidden = false` (`restored`) |
| 5 | Проверить `1005` | Создана, `is_available = true` |
| 6 | Посчитать строки `categories`, `menu_items` заведения A | Ни одна не удалена |
| 7 | Проверить `1001` заведения B | Не изменилась (цена, `updated_at`, `synced_at`) |
| 8 | Счётчики отчёта | `created = 1`, `updated = 1`, `hidden = 1`, `restored = 1` |

---

## TC-62-002: Изоляция заведений при применении

**Priority:** Critical
**Type:** Security (мультиарендность)
**AC:** AC-2 (чужое заведение не изменилось); NFR-1 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_apply.py::test_ac62_scenario`, `test_load_current_menu_is_tenant_scoped`, `test_unknown_tenant`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `load_current_menu(session, A)` при одинаковых `external_id` у A и B | Только строки A |
| 2 | Применить снимок к A | Меню B не меняется |
| 3 | `apply_menu_snapshot` для несуществующего `tenant_id` | `TenantNotFoundError` |

---

## TC-62-003: План — категории и позиции создаются, обновляются, скрываются, возвращаются

**Priority:** High
**Type:** Functional
**AC:** AC-2; FR-2 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_plan.py::test_new_category_and_item_are_created`, `test_unchanged_rows_are_not_written`, `test_changed_item_fields_are_updated`, `test_currency_change_counts_as_update`, `test_item_moves_to_new_category`, `test_changed_category_is_updated`, `test_hidden_rows_back_in_snapshot_are_restored_even_if_changed`, `test_visible_rows_missing_from_snapshot_are_hidden_and_prices_kept`, `test_already_hidden_rows_missing_from_snapshot_are_not_counted`, `test_empty_plan_defaults`; `tests/db/test_menu_sync_apply.py::test_categories_created_updated_hidden_and_restored`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Снимок с новой категорией и позицией | Обе в плане создания |
| 2 | Снимок без изменений | Записей нет, `updated_at` не меняется |
| 3 | Изменено `name`, `station`, `sort_key`, валюта, категория позиции | Позиция `updated` |
| 4 | Видимая позиция/категория пропала из снимка | `is_hidden = true`, цены не удаляются |
| 5 | Уже скрытая пропала снова | Не считается в `hidden` |
| 6 | Скрытая вернулась с изменениями | `restored`, изменения записаны |

---

## TC-62-004: Цены тарифов и наличие

**Priority:** High
**Type:** Functional
**AC:** FR-2 spec (тарифы вне снимка удаляются; `is_available = None` не меняет наличие, у новой — `true`); NFR-2 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_plan.py::test_prices_created_updated_and_deleted`, `test_same_price_with_other_scale_is_unchanged`, `test_only_deleted_tier_makes_item_updated`, `test_is_available_none_keeps_availability`, `test_is_available_change_is_written_and_counted`, `test_new_item_availability_is_not_counted_as_change`, `test_restored_item_with_availability_change`; `tests/db/test_menu_sync_apply.py::test_prices_and_availability`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Новый тариф `vip`, изменённая цена `default` | Цена создана / обновлена |
| 2 | Тариф позиции пропал из снимка | Строка `menu_item_prices` удалена, позиция `updated` |
| 3 | `8.5` в БД и `8.50` в снимке | Без изменений |
| 4 | `is_available = None` | Наличие в БД не меняется |
| 5 | `is_available = False` у существующей | Записано, `availability_changed = 1` |
| 6 | Новая позиция без `is_available` | `true`, не считается изменением наличия |

---

## TC-62-005: «Всё или ничего» — ошибка отклоняет весь снимок

**Priority:** Critical
**Type:** Negative
**AC:** FR-3 spec (при `severity=error` в таблицы меню ничего не пишется; пустой снимок отвергается всегда); ADR-8.3 (чужая валюта)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_apply.py::test_currency_mismatch_rejects_whole_snapshot`, `test_empty_snapshot_is_always_rejected`, `test_zero_price_warning_does_not_block`, `test_issues_are_limited`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Снимок, где одна позиция в `USD` при валюте `AZN` | `rejected`, `currency_mismatch`, меню не изменилось |
| 2 | Пустой снимок, в т. ч. с `allow_mass_hide=True` | `rejected`, `empty_snapshot` |
| 3 | Цена `0.00` | `applied` с предупреждением `zero_price` |
| 4 | Снимок с > 100 ошибками | В отчёте 100, остаток — `issues_truncated` |

---

## TC-62-006: Защита от массового скрытия

**Priority:** High
**Type:** Negative
**AC:** FR-3 spec (≥ 10 позиций и ≥ 30 % видимых → `mass_hide`, снимается `allow_mass_hide`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_plan.py::test_mass_hide_boundary`, `test_mass_hide_allowed`, `test_mass_hide_ignores_already_hidden_items`, `test_mass_hide_clears_category_and_price_writes`, `test_is_mass_hide`, `test_mass_hide_constants`; `tests/db/test_menu_sync_apply.py::test_mass_hide_rejected_and_allowed`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | План скрывает 9 позиций | Применяется |
| 2 | План скрывает 10 из 33 видимых (≥ 30 %) | `mass_hide`, записи плана очищены |
| 3 | Уже скрытые позиции | В расчёт не входят |
| 4 | Тот же снимок с `allow_mass_hide=True` | `applied` |

---

## TC-62-007: Пробный прогон (dry_run)

**Priority:** High
**Type:** Functional
**AC:** FR-3 spec (`--dry-run` — тот же план под тем же lock, без записи)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_apply.py::test_dry_run_writes_nothing_and_matches_real_counts`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `apply_menu_snapshot(…, dry_run=True)` | Отчёт `applied`, `dry_run = true`, таблицы меню не изменились |
| 2 | То же без `dry_run` | Счётчики совпадают с пробным прогоном |

---

## TC-62-008: Advisory lock — второе применение сразу получает отказ

**Priority:** High
**Type:** Negative (параллельность)
**AC:** FR-3, NFR-3 spec (`MenuSyncBusyError` без ожидания)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_apply.py::test_busy_lock_raises`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Во втором соединении взять `pg_advisory_xact_lock(8, hashtext(tenant_id::text))` | Lock удерживается |
| 2 | `apply_menu_snapshot` для того же заведения | Немедленно `MenuSyncBusyError`, меню не изменилось |

---

## TC-62-009: Снимок максимального размера помещается в лимиты PostgreSQL

**Priority:** Medium
**Type:** Functional (граничное значение)
**AC:** ADR-8.2 (5000 позиций × 10 тарифов); NFR-5 spec (запись пакетами)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_apply.py::test_max_size_snapshot_fits_bind_parameter_limit`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Применить снимок 5000 позиций × 10 тарифов | `applied` |
| 2 | Применить 5000 позиций × 1 тариф | `applied`, 45 000 цен удалены одним запросом, нет ошибки лимита параметров |

---

## TC-62-010: Производительность — 2 000 позиций не дольше 10 с

**Priority:** Medium
**Type:** Functional (NFR)
**AC:** NFR-5 spec (файл на 2 000 позиций разбирается, проверяется и применяется ≤ 10 с на сервере пилота, Windows Server 2019, `single`)
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет.
**Статус прогона:** НЕ ВЫПОЛНЕН (нужен сервер пилота)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Сгенерировать синтетический CSV на 2 000 позиций | Файл готов |
| 2 | `Measure-Command { python -m app.menu_sync import FILE --tenant UUID }` | Код 0, время ≤ 10 с |
| 3 | Повторить с тем же файлом | `unchanged`, таблицы меню не тронуты |

---

## Related TCs
- TC-50-003 (скрытие не удаляет данные; RESTRICT для строк кассы)
- TC-50-005, TC-49-005 (составные FK исключают межарендные ссылки)
- TC-63-001 (`unchanged` для неизменённого снимка)
- TC-66-004, TC-66-005 (mass-hide и lock в CLI)
