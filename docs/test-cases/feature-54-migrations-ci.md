# Test Cases: Story #54 — Проверка миграций в CI: upgrade, downgrade, инварианты схемы

**Feature:** #7 «Модель данных v1 и миграции Alembic» (story #54, AC-7)
**Spec:** docs/specs/feature-7-data-model.md (FR-9, NFR-1, NFR-2, NFR-4)
**Arch:** docs/arch/feature-7-data-model.md (ADR-7.3, ADR-7.4, ADR-7.10, ADR-7.11; DEC-010)
**Created:** 2026-10-13

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-12: локально (Windows, PostgreSQL 16, `ai_waiter_test`) 1017 passed, 3 skipped, все db-тесты PASS; CI PR #57 — 5/5.

Общее предусловие: Linux-джоб CI `backend (postgres + redis)` (`backend-services` в `.github/workflows/ci.yml`) с сервис-контейнером postgres и базой `ai_waiter_test`; ревизии `0001`…`0004`.

---

## TC-54-001: CI выполняет цикл миграций и alembic check до pytest

**Priority:** Critical
**Type:** Functional
**AC:** AC-7 (Given Linux-джоб CI с postgres / When `alembic upgrade head`, `downgrade base`, `upgrade head`, `alembic check` / Then все команды завершаются с кодом 0)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_repo_artifacts.py::test_ci_services_job_checks_migrations_before_pytest`, `test_ci_services_job_uses_dedicated_test_database`, `test_ci_has_services_job_for_db_and_scaled_markers`; на реальной БД — `tests/db/test_alembic.py::test_upgrade_downgrade_upgrade`. Фактический прогон — CI PR #57.
**Статус прогона:** PASS (CI PR #57: 5/5 зелёные; локально цикл и `check` — код 0)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть PR, дождаться джоба `backend (postgres + redis)` | Шаги `uv run alembic upgrade head`, `downgrade base`, `upgrade head`, `alembic check` идут подряд и раньше шага `pytest` |
| 2 | Проверить окружение джоба | `DATABASE_URL` = `TEST_DATABASE_URL` (база `ai_waiter_test`) — Alembic и db-тесты работают с одной тестовой базой |
| 3 | После `downgrade base` | В `public` нет таблиц, кроме `alembic_version`; повторный `upgrade head` создаёт схему, ревизия = head |

---

## TC-54-002: alembic check не находит расхождений моделей и миграций

**Priority:** Critical
**Type:** Functional
**AC:** AC-7 (`alembic check` не находит расхождений между моделями и миграциями)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_alembic.py::test_models_match_migrations`; шаг CI `uv run alembic check`; `tests/test_migrations_offline.py::test_offline_upgrade_head_creates_all_tables`, `test_offline_upgrade_head_has_all_fifteen_tables_and_trigger`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `upgrade head`, затем `alembic check` | Код 0, «No new upgrade operations detected» |
| 2 | (Негатив, мысленно/локально) добавить колонку в модель без миграции | `alembic check` завершается с ненулевым кодом — шаг CI красный |

### Notes
Шаг 2 не автоматизирован отдельным тестом: поведение `alembic check` обеспечивает Alembic; рассинхрон, найденный в ходе #54 (индексы `ix_menu_item_prices_tenant_id_menu_item_id`, `ix_menu_item_meta_tenant_id_menu_item_id`, DEC-010), исправлен изменением `0002_menu`.

---

## TC-54-003: Инвариант tenant_id на реальной схеме

**Priority:** Critical
**Type:** Security (мультиарендность)
**AC:** AC-7 (в каждой таблице заведения есть NOT NULL колонка `tenant_id` с индексом); NFR-1 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_schema_invariants.py::test_every_tenant_table_has_indexed_not_null_tenant_id`, `test_tenant_check_covers_all_tables`, `test_tenant_check_detects_violations`; на моделях — `tests/test_models_metadata.py::test_tenant_id_not_null_with_fk_to_tenants`, `test_tenants_has_no_tenant_id`, `test_tenant_tables_with_id_have_unique_tenant_id_id`, `test_references_inside_tenant_are_composite`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | После `upgrade head` прочитать схему из `information_schema`/`pg_catalog` | Все 15 таблиц ревизий `0001`…`0004` присутствуют |
| 2 | Для каждой таблицы, кроме исключений `tenants`, `alembic_version` | `tenant_id` есть, NOT NULL, есть полный индекс (обычный, UNIQUE или PK), где `tenant_id` — первая колонка |
| 3 | Проверить исключения | Существуют и действительно не содержат `tenant_id` (лишнее исключение — ошибка) |
| 4 | Пробные таблицы: без `tenant_id`, nullable, без индекса, `tenant_id` не первым, частичный индекс | Каждое нарушение найдено с понятным текстом |

---

## TC-54-004: Инвариант денег NUMERIC(10,2) и явное исключение messages.cost_usd

**Priority:** Critical
**Type:** Functional / Negative
**AC:** AC-7 (все денежные колонки — `NUMERIC(10,2)`, исключение `messages.cost_usd` перечислено явно); NFR-2 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_schema_invariants.py::test_money_columns_exist_and_are_numeric_10_2`, `test_every_numeric_column_is_money_or_listed_exception`, `test_numeric_exceptions_exist_with_exact_type`, `test_money_check_detects_wrong_type_and_missing_column`, `test_numeric_check_detects_unlisted_numeric_and_floats`; `tests/test_models_metadata.py::test_numeric_columns_are_money_or_listed_exceptions`; `tests/test_db_base.py::test_money_is_numeric_10_2_decimal`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить список денежных колонок (`price`, `price_at_add`, `price_at_order`, `total`, `pos_total`) | Список не пуст, все колонки есть и имеют тип `numeric(10,2)` |
| 2 | Любая другая `numeric` колонка | Только явные исключения (`messages.cost_usd` = `numeric(12,6)`, `menu_item_meta.weight_amount` = `numeric(8,2)`) с точным типом; денежная колонка не может быть исключением |
| 3 | Пробные таблицы: `numeric(12,2)`, `numeric` без точности, `real`, `double precision`, `money`, пропавшая денежная колонка, `cost_usd numeric(12,6)` не в `messages` | Каждое нарушение найдено (исключение привязано к таблице, а не к имени колонки) |

---

## TC-54-005: Инвариант времени timestamptz

**Priority:** High
**Type:** Functional / Negative
**AC:** AC-7 (все колонки времени имеют тип `timestamptz`); NFR-2 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_schema_invariants.py::test_time_columns_are_timestamptz`, `test_created_at_and_updated_at_are_timestamptz`, `test_timestamp_check_detects_naive_and_non_timestamp_time_columns`, `test_checks_pass_on_valid_probe_tables`; `tests/test_models_metadata.py::test_datetimes_are_timestamptz`, `test_timestamps_present`; статика — правило `DTZ` в `ruff`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Все колонки типа даты/времени в `public` | Только `timestamp with time zone` |
| 2 | `created_at` | Есть во всех таблицах, кроме `alembic_version`; `created_at` и `updated_at` — `timestamptz` |
| 3 | Пробные таблицы: `timestamp`, `timestamp(3)` без зоны, `date` и `text` для колонок `*_at` | Нарушения найдены; колонка `day date` (не время события) и корректная таблица не дают ложных срабатываний |

---

## TC-54-006: Любое нарушение делает джоб красным

**Priority:** High
**Type:** Negative
**AC:** AC-7 (нарушение любого инварианта или рассинхрон моделей и миграций делает джоб красным)
**E2E Automated:** No
**Автоматизация:** Авто — детекторы нарушений из TC-54-003…005 (`test_*_detects_*`); `tests/test_repo_artifacts.py::test_ci_does_not_swallow_failures`, `test_ci_services_job_uses_dedicated_test_database` (нет обработки кода 5 pytest: `code=$?` удалён); `tests/test_db_guards.py::test_missing_url_fails_in_ci`.
**Статус прогона:** PASS (статика и детекторы); намеренно красный прогон CI не выполнялся.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить шаги джоба | Нет `continue-on-error`, нет подавления кода возврата pytest |
| 2 | db-тесты при `CI=true` без `TEST_DATABASE_URL` | Ошибка, а не пропуск (тесты не исчезают молча) |
| 3 | Нарушение инварианта | Тест падает с перечислением нарушений — шаг `pytest` красный |

---

## TC-54-007: Локальная проверка миграций на Windows по README

**Priority:** Medium
**Type:** Functional (переносимость)
**AC:** AC-7 (вне scope CI: на Windows разработчик запускает проверку локально; README, раздел «База данных»)
**E2E Automated:** No
**Автоматизация:** Ручной (команды README); тот же цикл выполняет `tests/db/test_alembic.py` под guard `*_test`.
**Статус прогона:** PASS (2026-10-12, Windows, PostgreSQL 16 как служба, `ai_waiter_test`: `upgrade head` / `downgrade base` / `upgrade head` / `check` — код 0; `pytest -m db` — все PASS)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | По README выполнить `pytest -q -m db` с `TEST_DATABASE_URL` на `ai_waiter_test` | Все db-тесты проходят, ни один не `skipped` |
| 2 | Проверить README | Есть предупреждение: `downgrade base` вручную — только на тестовой базе; ручного блока с `DATABASE_URL` и `downgrade base` нет (замечание security review #54 устранено) |

---

## Related TCs
- TC-48-001, TC-48-004 (цикл Alembic, guard `*_test`)
- TC-49-006, TC-51-007, TC-52-009 (`downgrade -1` по ревизиям)
- TC-50-007, TC-51-005 (деньги и исключение `cost_usd`)
- TC-44-001, TC-44-002 (структура CI, падение шага — красная проверка)
