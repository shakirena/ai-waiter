# Test Cases: Story #49 — Модель данных: tenants, halls, tables

**Feature:** #7 «Модель данных v1 и миграции Alembic» (story #49, AC-2)
**Spec:** docs/specs/feature-7-data-model.md (FR-4, NFR-1)
**Arch:** docs/arch/feature-7-data-model.md (ADR-7.1, ADR-7.2, ADR-7.3, ревизия `0001_tenants_tables`)
**Created:** 2026-10-12

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-12: локально (Windows, PostgreSQL 16, `ai_waiter_test`) 1017 passed, 3 skipped, все db-тесты PASS; CI PR #57 — 5/5.

Общее предусловие для всех TC: применена миграция `0001_tenants_tables` (или `upgrade head`) на тестовой базе `*_test`, тест работает через фикстуру `db_session` с откатом.

---

## TC-49-001: qr_token стола уникален на всю таблицу

**Priority:** Critical
**Type:** Functional / Security
**AC:** AC-2 (повтор `qr_token` отклоняется уникальным индексом на всю таблицу)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenants_tables.py::test_qr_token_unique_across_all_tenants`; `tests/test_migrations_offline.py::test_offline_sql_contains_composite_fk_and_global_qr_unique`; `tests/test_models_metadata.py::test_table_defaults_and_uniques`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вставить заведение A, зал и стол с `qr_token = T` | Успех |
| 2 | Вставить второй стол заведения A с тем же `qr_token = T` | `IntegrityError`, ограничение `uq_tables_qr_token` |
| 3 | Вставить стол заведения B с `qr_token = T` | `IntegrityError` (уникальность глобальная: по токену определяется заведение) |

### Expected Result
По `qr_token` однозначно определяется стол и заведение.

---

## TC-49-002: external_id стола уникален только внутри заведения

**Priority:** Critical
**Type:** Functional
**AC:** AC-2 (повтор `external_id` внутри заведения отклоняется, тот же `external_id` в другом заведении принимается)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenants_tables.py::test_external_id_unique_within_tenant_only`, `test_null_external_ids_do_not_conflict`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Стол заведения A с `external_id = '5'` | Успех |
| 2 | Второй стол заведения A с `external_id = '5'` | `IntegrityError`, ограничение `uq_tables_tenant_id_external_id` (частичное, где `external_id` не NULL) |
| 3 | Стол заведения B с `external_id = '5'` | Успех |
| 4 | Несколько столов заведения A с `external_id = NULL` | Успех (NULL не конфликтуют) |

---

## TC-49-003: Значения по умолчанию tenants и tables

**Priority:** High
**Type:** Functional
**AC:** AC-2 (значения по умолчанию соответствуют spec: `price_tier = 'default'`, `is_active = true`, тип стола из допустимых)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenants_tables.py::test_tenant_defaults`, `test_table_defaults`, `test_cabin_type_accepted`, `test_tenant_languages_subset_accepted`, `test_tenant_text_and_cyrillic_roundtrip`; `tests/test_models_metadata.py::test_tenant_defaults`, `test_table_defaults_and_uniques`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вставить заведение только с обязательными полями | `languages = {az,ru}`, `settings = {}`, `created_at`/`updated_at` — aware-datetime; `id` — UUIDv7 |
| 2 | Вставить стол только с обязательными полями | `type = 'table'`, `price_tier = 'default'`, `is_active = true`, `hall_id` и `external_id` — NULL, `token_issued_at` — aware-datetime |
| 3 | Стол с `type = 'cabin'`, `price_tier = 'vip'` | Принимается |
| 4 | Название `Şəki çayxanası — «Чайхана»`, `settings = {"escalate_after_minutes": 7}` | Сохраняется и читается без искажений |

---

## TC-49-004: Ограничения CHECK tenants, halls, tables

**Priority:** High
**Type:** Negative
**AC:** AC-2 (недопустимый `type` отклоняется CHECK)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenants_tables.py::test_table_checks` (13 случаев), `test_tenant_checks` (8 случаев), `test_hall_name_unique_within_tenant`; `tests/db/test_migrations.py::test_check_constraint_values_match_enums[ck_tables_type]`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Стол с `type = 'bar'` и `type = 'cabinet'` | `ck_tables_type` |
| 2 | `price_tier` = `VIP`, `1vip`, пустая строка | `ck_tables_price_tier` |
| 3 | `external_id` пустой или длиннее 64 | `ck_tables_external_id` |
| 4 | `qr_token` короче 22 символов, длиннее 64 или с символом `+` | `ck_tables_qr_token` |
| 5 | Пустое `name` стола или зала | `ck_tables_name` / `ck_halls_name` |
| 6 | Заведение: пустое имя или > 200 символов; `currency` = `azn`, `AZNX`; `languages` = `{}`, `{az,en}`; `settings` — массив или строка | `ck_tenants_name`, `ck_tenants_currency`, `ck_tenants_languages`, `ck_tenants_settings` |
| 7 | Два зала с одинаковым именем в одном заведении | `IntegrityError` (уникальность `(tenant_id, name)`) |

### Notes
Тип кабинета в схеме — `cabin` (`TableType.CABIN`), в технических заметках issue — `cabinet`; значение `cabinet` отклоняется. Значения CHECK сверены с `StrEnum` тестом.

---

## TC-49-005: Межарендная ссылка стола на зал отклоняется БД

**Priority:** Critical
**Type:** Security (tenant-изоляция)
**AC:** AC-2 (стол со ссылкой на зал другого заведения отклоняется составным внешним ключом); NFR-1 spec; ADR-7.3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenant_isolation.py::test_table_cannot_reference_hall_of_other_tenant`, `test_table_hall_of_same_tenant_and_null_hall_accepted`, `test_moving_table_to_hall_of_other_tenant_rejected`, `test_changing_tenant_of_table_in_hall_rejected`; `tests/test_models_metadata.py::test_references_inside_tenant_are_composite`, `test_tenant_tables_with_id_have_unique_tenant_id_id`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Заведения A и B, зал H в B; вставить стол A с `hall_id = H` | `IntegrityError` по составному FK `(tenant_id, hall_id)` |
| 2 | Стол A с залом A или с `hall_id = NULL` | Успех |
| 3 | `UPDATE` стола A: `hall_id` → зал B | Отклоняется |
| 4 | `UPDATE` стола A в зале A: `tenant_id` → B | Отклоняется |

### Expected Result
Даже при ошибке в коде сервиса БД не допускает связь между заведениями.

---

## TC-49-006: downgrade -1 удаляет ровно три таблицы ревизии

**Priority:** High
**Type:** Functional
**AC:** AC-2 (`alembic downgrade -1` полностью удаляет эти три таблицы)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_migrations.py::test_downgrade_one_step_drops_only_revision_tables[0001_tenants_tables]`, `test_database_is_utf8_and_check_passes`; `tests/test_migrations_offline.py::test_each_revision_creates_and_drops_its_tables`, `test_server_encoding_utf8_accepted`, `test_server_encoding_other_rejected_with_clear_message`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `alembic downgrade 0001_tenants_tables` | Есть `tenants`, `halls`, `tables` |
| 2 | `alembic downgrade -1` | Удалены ровно `tenants`, `halls`, `tables`, другие таблицы не затронуты |
| 3 | `alembic upgrade 0001_tenants_tables` | Таблицы созданы снова |
| 4 | Применить `0001` к базе с `server_encoding` ≠ UTF8 | Миграция прерывается с понятным сообщением |

---

## TC-49-007: RESTRICT при удалении и перевыпуск qr_token

**Priority:** Medium
**Type:** Functional / Negative
**AC:** AC-2 (расширение: `hall_id` — FK RESTRICT; отзыв и перевыпуск токена — смена значения)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenants_tables.py::test_delete_restricted_while_referenced`, `test_qr_token_reissue_updates_token`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Удалить зал, на который ссылается стол | `IntegrityError`, `fk_tables_tenant_id_hall_id_halls` (RESTRICT) |
| 2 | Удалить заведение, у которого есть залы | `IntegrityError`, `fk_halls_tenant_id_tenants` |
| 3 | Заменить `qr_token` стола новым значением (`UPDATE`) | Старый токен больше не находит стол, новый — находит |

---

## Related TCs
- TC-48-005 (миксины и соглашение об именах)
- TC-50-005, TC-51-006, TC-52-008 (та же схема составных FK для меню, визитов, заказов)
- TC-53-001 (сид создаёт столы с уникальными `qr_token`)
- TC-54-003 (инвариант `tenant_id` на реальной схеме)
