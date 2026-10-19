# Test Cases: Story #63 — Журнал синхронизаций меню с пропуском неизменённого снимка

**Feature:** #8 «Импорт меню из CSV/XLSX» (story #63, AC-3)
**Spec:** docs/specs/feature-8-menu-import.md (FR-1 хеш, FR-4, NFR-6, NFR-8, AC-3)
**Arch:** docs/arch/feature-8-menu-import.md (ADR-8.5, ревизия `0005_menu_sync_runs`)
**Created:** 2026-10-19

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — прогон qa-lead 2026-10-19: полный `uv run pytest -q --cov=app` — 1669 passed, 3 skipped (тесты настоящего Redis), покрытие `app` 100%.

AC story: **Given** снимок применён, в `menu_sync_runs` запись `applied` с хешем / **When** тот же снимок (другой порядок позиций) без `force` применяется снова / **Then** таблицы меню не меняются (`updated_at`, `synced_at` прежние), в `menu_sync_runs` запись `unchanged` с тем же хешем, источником и временем запуска.

Код: `app/models/menu_sync.py` (`MenuSyncRun`), `alembic/versions/0005_menu_sync_runs.py`, `app/menu_sync/snapshot.py::snapshot_hash`, `app/menu_sync/service.py` (`last_applied_hash`, `record_rejected_run`, `journal_source_ref`, шаги 3 и 6 `apply_menu_snapshot`).

---

## TC-63-001: Тот же снимок в другом порядке — unchanged, меню не тронуто

**Priority:** Critical
**Type:** Functional
**AC:** AC-3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_runs.py::test_ac63_same_snapshot_in_other_order_is_unchanged`.
**Статус прогона:** PASS

### Preconditions
- Снимок применён, в `menu_sync_runs` запись `applied` с хешем.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запомнить `updated_at`, `synced_at` строк меню | — |
| 2 | Применить тот же снимок с позициями в обратном порядке, без `force` | Статус `unchanged` |
| 3 | Сравнить `updated_at`, `synced_at` | Прежние |
| 4 | Проверить новую запись журнала | `status = unchanged`, тот же `snapshot_hash`, тот же `source`, `started_at`/`finished_at` заполнены, `finished_at >= started_at`, счётчики нулевые |

---

## TC-63-002: Хеш снимка — канонический и устойчивый

**Priority:** High
**Type:** Functional
**AC:** AC-3 (тот же хеш при другом порядке); FR-1 spec (SHA-256 канонического JSON)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_menu_sync_runs.py::test_hash_is_sha256_hex_matching_db_check`, `test_hash_is_stable_between_calls`, `test_hash_does_not_depend_on_order_of_items_categories_and_tiers`, `test_hash_does_not_depend_on_money_notation`, `test_hash_changes_with_data`, `test_hash_changes_with_categories_and_item_set`, `test_hash_after_resolve_currency_equals_explicit_currency`, `test_hash_with_duplicate_ids_does_not_depend_on_order`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `snapshot_hash` дважды | Одинаков, `^[0-9a-f]{64}$` (как CHECK БД) |
| 2 | Переставить позиции, категории, тарифы | Хеш тот же |
| 3 | `8.5` вместо `8.50` | Хеш тот же |
| 4 | Изменить цену, название, набор позиций или категорий | Хеш другой |

---

## TC-63-003: force, изменённый снимок, другой источник

**Priority:** High
**Type:** Functional
**AC:** FR-4 spec (хеш сравнивается с последней записью `applied`/`unchanged` любого источника; `--force` пересчитывает)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_runs.py::test_force_applies_same_snapshot_again`, `test_changed_snapshot_is_applied_and_hash_moves`, `test_other_source_with_same_hash_is_unchanged`, `test_last_applied_hash_takes_latest_applied_or_unchanged`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Тот же снимок с `force=True` | `applied`, новая запись журнала |
| 2 | Изменённый снимок | `applied`, новый хеш становится последним |
| 3 | Тот же снимок от источника `connector` после `file` | `unchanged` |
| 4 | Последняя запись — `rejected` | `last_applied_hash` берёт последнюю `applied`/`unchanged` |

---

## TC-63-004: Отклонённый снимок журналируется после отката

**Priority:** High
**Type:** Negative
**AC:** FR-4 spec (`record_rejected_run` — отдельная транзакция); NFR-6 spec (значения ≤ 60, проблем ≤ 100)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_runs.py::test_rejected_is_journaled_after_rollback`, `test_rejected_by_plan_has_hash_and_does_not_count_as_applied`, `test_rejected_issues_are_limited_and_values_truncated`, `test_applied_with_warnings_keeps_them_in_journal`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Снимок с ошибкой `check_snapshot`, откат, `record_rejected_run` | Запись `rejected`, `snapshot_hash = NULL`, `counts = {}`, меню не изменилось |
| 2 | Снимок, отклонённый планом (`mass_hide`) | `rejected` с хешем; следующий такой же снимок не `unchanged` |
| 3 | > 100 проблем, длинные значения | В `issues` 100 записей, `issues_truncated`, значения ≤ 60 символов |
| 4 | `applied` с `zero_price` | Предупреждение сохранено в `issues` |

---

## TC-63-005: Пробный прогон не пишет журнал

**Priority:** Medium
**Type:** Functional
**AC:** FR-3, FR-4 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_runs.py::test_dry_run_is_not_journaled`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `apply_menu_snapshot(…, dry_run=True)` | Статус, который дало бы применение; `run_id = None`; новых строк в `menu_sync_runs` нет |

---

## TC-63-006: В журнал попадает только имя файла

**Priority:** High
**Type:** Security
**AC:** NFR-6 spec (путь к файлу не попадает в журнал)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_runs.py::test_source_ref_is_file_name_without_directory`; `tests/test_menu_sync_runs.py::test_journal_source_ref_keeps_only_file_name`, `test_journal_source_ref_is_truncated_to_db_limit`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `source_ref = "C:\dir\sub\menu.csv"` и `"/srv/x/menu.csv"` на любой ОС | В журнале `menu.csv` |
| 2 | Имя длиннее 255 символов | Обрезано до 255 |

---

## TC-63-007: Журнал и хеш изолированы по заведению

**Priority:** Critical
**Type:** Security (мультиарендность)
**AC:** NFR-1 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_runs.py::test_journal_and_hash_are_tenant_scoped`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Снимок применён в заведении A | `applied` в журнале A |
| 2 | Тот же снимок в заведении B | `applied` (не `unchanged`): хеш A не влияет на B |

---

## TC-63-008: Таблица menu_sync_runs — ревизия 0005 и CHECK

**Priority:** High
**Type:** Functional (схема)
**AC:** FR-4 spec (ревизия `0005_menu_sync_runs`, обратимая)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu_sync_runs.py::test_checks_reject_invalid_rows`, `test_valid_rows_accepted_with_defaults`; `tests/test_migrations_offline.py::test_chain_is_linear_and_ordered`, `test_each_revision_creates_and_drops_its_tables`, `test_offline_upgrade_head_creates_all_tables`; `tests/db/test_migrations.py::test_downgrade_one_step_drops_only_revision_tables`, `test_check_constraint_values_match_enums`; `tests/db/test_alembic.py::test_upgrade_downgrade_upgrade`, `test_models_match_migrations`; `tests/test_models_metadata.py::test_expected_tables_registered`, `test_expected_checks_present`, `test_tenant_id_not_null_with_fk_to_tenants`, `test_datetimes_are_timestamptz`; `tests/db/test_seed.py` (`menu_sync_runs` = 0 после сида).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `alembic upgrade head` → `downgrade -1` → `upgrade head`, `alembic check` | Цепочка линейна, head — `0005`, `downgrade` удаляет только `menu_sync_runs`, расхождений нет |
| 2 | Вставить строку с неверным `source`, `status`, хешем не из 64 hex, `applied` без хеша, `finished_at < started_at`, `counts` не объект, `issues` не массив | `IntegrityError` по соответствующему CHECK |
| 3 | Вставить корректную строку | Принята, значения по умолчанию заполнены |
| 4 | Инварианты схемы | `tenant_id NOT NULL` с FK, время — `timestamptz` |

---

## Related TCs
- TC-54-002, TC-54-003, TC-54-005 (инварианты схемы распространяются на новую таблицу)
- TC-61-002 (хеш не зависит от порядка позиций)
- TC-62-001, TC-62-005 (применение и отклонение снимка)
- TC-66-001, TC-66-003 (CLI пишет `applied`/`unchanged`/`rejected`)

## Замечание
NFR-8 spec («структурированная запись в лог: заведение, источник, статус, счётчики, длительность, хеш») в части лога в `app/menu_sync` не найдена (нет вызовов логгера); итог запуска фиксируется только строкой `menu_sync_runs`. Передано qa-lead для решения.
