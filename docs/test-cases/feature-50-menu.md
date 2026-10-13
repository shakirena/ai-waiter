# Test Cases: Story #50 — Модель данных: меню (categories, menu_items, цены, meta, аллергены)

**Feature:** #7 «Модель данных v1 и миграции Alembic» (story #50, AC-3)
**Spec:** docs/specs/feature-7-data-model.md (FR-5, NFR-1, NFR-2, NFR-7)
**Arch:** docs/arch/feature-7-data-model.md (ADR-7.3, ADR-7.4, ADR-7.13, ревизия `0002_menu`)
**Created:** 2026-10-12

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-12: локально (Windows, PostgreSQL 16, `ai_waiter_test`) 1017 passed, 3 skipped, все db-тесты PASS; CI PR #57 — 5/5.

Общее предусловие: применены миграции до `0002_menu` (или `upgrade head`), тест работает через `db_session` с откатом. Базовые данные AC-3: в заведении A категория и позиция с `external_id = '157'`, цены тарифов `default` (12.50) и `vip` (15.00), `menu_item_meta`, один аллерген, связанный с позицией.

---

## TC-50-001: Дубли external_id и тарифа внутри заведения отклоняются

**Priority:** Critical
**Type:** Functional / Negative
**AC:** AC-3 (повтор `external_id` внутри заведения и повтор тарифа для позиции отклоняются уникальными ограничениями)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu.py::test_ac3_scenario`, `test_category_external_id_unique_within_tenant`, `test_allergen_code_unique_within_tenant`; `tests/test_models_metadata.py::test_menu_primary_keys`, `test_menu_uniques_and_indexes`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вставить вторую позицию заведения A с `external_id = '157'` | `IntegrityError`, `uq_menu_items_tenant_id_external_id` |
| 2 | Вставить вторую цену тарифа `vip` для той же позиции | `IntegrityError`, `pk_menu_item_prices` (PK `(menu_item_id, price_tier)`) |
| 3 | Вторая категория заведения A с тем же `external_id` | `uq_categories_tenant_id_external_id` |
| 4 | Второй аллерген заведения A с тем же `code` | `uq_allergens_tenant_id_code` |

---

## TC-50-002: Та же позиция в другом заведении принимается

**Priority:** High
**Type:** Functional (мультиарендность)
**AC:** AC-3 (та же позиция в другом заведении принимается)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu.py::test_ac3_scenario`, `test_category_external_id_unique_within_tenant`, `test_allergen_code_unique_within_tenant`, `test_default_allergen_rows_insert_for_two_tenants`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Позиция заведения B с `external_id = '157'` | Успех |
| 2 | Категория и аллерген заведения B с теми же `external_id` / `code`, что в A | Успех |
| 3 | Скопировать справочник 14 аллергенов ЕС в A и B | Коды в обоих заведениях совпадают с `EU14_ALLERGEN_CODES`, конфликта нет, `id` — UUIDv7 |

---

## TC-50-003: Скрытие позиции не удаляет данные; строки кассы защищены RESTRICT

**Priority:** Critical
**Type:** Functional
**AC:** AC-3 (строка позиции и связанные цены, meta и аллергены после `is_hidden = true` остаются на месте); NFR-7 spec (ТЗ INT-2)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu.py::test_ac3_scenario`, `test_restrict_on_category_and_allergen`, `test_deleting_menu_item_cascades_owned_rows`; `tests/test_models_metadata.py::test_menu_on_delete_rules`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `UPDATE menu_items SET is_hidden = true` для позиции `157` | Позиция на месте, `is_hidden = true` |
| 2 | Посчитать связанные строки | 2 цены, 1 meta, 1 связь с аллергеном — без изменений |
| 3 | Удалить категорию, у которой есть позиции | `IntegrityError`, `fk_menu_items_tenant_id_category_id_categories` (RESTRICT) |
| 4 | Удалить аллерген, привязанный к позиции | `IntegrityError`, `fk_menu_item_allergens_tenant_id_allergen_id_allergens` |
| 5 | (Служебно) удалить саму позицию | Цены, meta и связи удаляются каскадом, аллерген справочника остаётся |

### Expected Result
Пропавшая из кассы позиция скрывается, а не удаляется; приложение не может случайно удалить категорию с позициями.

---

## TC-50-004: Ограничения CHECK меню — цена, острота, вес, путь фото

**Priority:** High
**Type:** Negative / Security
**AC:** AC-3 (отрицательная цена и `spice_level` вне 0..3 отклоняются CHECK)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu.py::test_price_checks` (2 случая), `test_meta_checks` (16 случаев), `test_meta_valid_values_accepted[0]`, `[3]`, `test_menu_item_checks` (3), `test_allergen_checks` (4); `tests/test_models_metadata.py::test_menu_check_texts`, `test_photo_path_pattern_semantics`; `tests/db/test_migrations.py::test_check_constraint_values_match_enums[ck_menu_item_meta_weight_unit]`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Цена `-0.01` | `ck_menu_item_prices_price` |
| 2 | Тариф `VIP` | `ck_menu_item_prices_price_tier` |
| 3 | `spice_level` = -1 и 4 | `ck_menu_item_meta_spice_level` |
| 4 | `spice_level` = 0 и 3, `prep_minutes = 240`, вес `350.5 g`, `photo_path = menu/plov-1.jpg` | Принимается |
| 5 | `prep_minutes` = 0 и 241 | `ck_menu_item_meta_prep_minutes` |
| 6 | Вес `0 g`; вес без единицы; единица без веса; единица `kg` | `ck_menu_item_meta_weight_amount`, `ck_menu_item_meta_weight`, `ck_menu_item_meta_weight_unit` |
| 7 | `photo_path` = `/etc/passwd`, `\\server\share\a.jpg`, `C:/photos/a.jpg`, `d:\photos\a.jpg`, `menu/../../secret` | `ck_menu_item_meta_photo_path` (только относительный путь без `..`) |
| 8 | Слишком длинные `name_ru` (> 200), `description_az` (> 2000), `ingredients_ru` (> 2000) | Соответствующие CHECK длины |
| 9 | `menu_items.currency = 'azn'`, `external_id` пустой или > 64 | `ck_menu_items_currency`, `ck_menu_items_external_id` |
| 10 | Аллерген с кодом `Gluten`, `tree-nuts`, пустым `name_az`, `name_ru` > 100 | `ck_allergens_*` |

---

## TC-50-005: Межарендные ссылки в меню отклоняются БД

**Priority:** Critical
**Type:** Security (tenant-изоляция)
**AC:** AC-3 (ссылка на категорию другого заведения отклоняется составным внешним ключом); NFR-1 spec; ADR-7.3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenant_isolation.py::test_menu_item_cannot_reference_category_of_other_tenant`, `test_price_and_meta_cannot_reference_menu_item_of_other_tenant`, `test_menu_item_cannot_get_allergen_of_other_tenant`, `test_allergen_link_cannot_reference_menu_item_of_other_tenant`; `tests/test_models_metadata.py::test_references_inside_tenant_are_composite`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Позиция заведения A с `category_id` категории B | `IntegrityError` (составной FK `(tenant_id, category_id)`) |
| 2 | Цена и meta с `tenant_id = A` на позицию B | Отклоняются |
| 3 | Связь позиции A с аллергеном B | Отклоняется |
| 4 | Связь с `tenant_id = A` на позицию B | Отклоняется |

---

## TC-50-006: Значения по умолчанию; allergens_verified = false; meta 1:1

**Priority:** High
**Type:** Functional / Security (AI-2: аллергены)
**AC:** AC-3 (`allergens_verified` по умолчанию `false`); ТЗ FR-16a, AI-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu.py::test_ac3_scenario`, `test_menu_item_defaults`, `test_meta_is_one_to_one`, `test_meta_valid_values_accepted`; `tests/test_models_metadata.py::test_menu_defaults`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вставить `menu_item_meta` без указания флагов | `allergens_verified = false`, `visible_to_ai = true`, `tags = []` |
| 2 | Вставить позицию только с обязательными полями | `is_available = true`, `is_hidden = false`, `sort_key = ''`, `synced_at` — aware-datetime; категория `is_hidden = false` |
| 3 | Вторая meta для той же позиции | `IntegrityError`, `pk_menu_item_meta` |

### Notes
Правило «пустой список аллергенов без `allergens_verified = true` означает "неизвестно"» — правило сервиса и ИИ (#11), ограничением БД не проверяется; здесь проверяется только безопасное значение по умолчанию.

---

## TC-50-007: Деньги NUMERIC(10,2) и порядок сортировки sort_key

**Priority:** High
**Type:** Functional
**AC:** AC-3 (цены); NFR-2 spec (деньги `NUMERIC(10,2)`, `Decimal`); ADR-7.13 (`COLLATE "C"`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_menu.py::test_prices_are_decimal_with_two_places`, `test_sort_key_uses_byte_order`; `tests/test_models_metadata.py::test_numeric_columns_are_money_or_listed_exceptions`, `test_sort_keys_use_c_collation`; `tests/db/test_schema_invariants.py::test_money_columns_exist_and_are_numeric_10_2`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Прочитать цены позиции | `[Decimal("12.50"), Decimal("15.00")]`, тип `Decimal`, не `float` |
| 2 | Цена `0` (тариф `staff`) | Принимается (CHECK `>= 0`) |
| 3 | Категории с `sort_key` `b`, `B`, `a`, `_`, сортировка по `sort_key` | Побайтный порядок, одинаковый на Windows и Linux |

---

## TC-50-008: Справочник 14 аллергенов ЕС

**Priority:** Medium
**Type:** Functional
**AC:** AC-3 (аллергены); ТЗ FR-16a
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_models_metadata.py::test_eu14_allergens_reference`, `test_default_allergen_rows_for_tenant`; `tests/db/test_menu.py::test_default_allergen_rows_insert_for_two_tenants`. Проверка азербайджанских названий носителем — TC-53-006 (ручной).
**Статус прогона:** PASS (авто)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить справочник `EU14_ALLERGENS` | Ровно 14 уникальных кодов ЕС по шаблону кода, `name_az` и `name_ru` длиной 1..100 |
| 2 | `default_allergen_rows(tenant_id)` | Коды в порядке справочника, нужный `tenant_id`, `sort_order` уникален и возрастает; функция чистая (изменение результата не портит справочник); строки вставляются в БД без ошибок |

---

## Related TCs
- TC-49-005 (составные FK — тот же приём)
- TC-51-002, TC-52-004 (цена на момент добавления в корзину и снимок цены в заказе берутся из `menu_item_prices`)
- TC-53-001 (сид загружает меню, цены `default`/`vip`, справочник аллергенов)
- TC-54-004 (инвариант `NUMERIC(10,2)`)
