# Test Cases: Story #53 — Сид-данные для разработки: команда python -m app.seed

**Feature:** #7 «Модель данных v1 и миграции Alembic» (story #53, AC-6)
**Spec:** docs/specs/feature-7-data-model.md (FR-8, NFR-6)
**Arch:** docs/arch/feature-7-data-model.md (ADR-7.12)
**Created:** 2026-10-12

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-12: локально (Windows, PostgreSQL 16, `ai_waiter_test`) 1017 passed, 3 skipped, все db-тесты PASS; CI PR #57 — 5/5.

Общее предусловие: применены все миграции #7 (`upgrade head`) на пустой базе; `APP_ENV=dev` (если не указано иное).

---

## TC-53-001: Первый запуск загружает полный демонстрационный набор

**Priority:** Critical
**Type:** Functional
**AC:** AC-6 (после первого запуска есть одно демо-заведение с залом, несколькими столами (свой `qr_token`), категориями и позициями с ценами `default` и `vip` на AZ/RU, справочником 14 аллергенов ЕС, примерами `allergens_verified` true и false, одним открытым визитом и одним заказом)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_seed.py::test_seed_loads_full_dataset`; `tests/test_seed.py::test_tenant_is_fictional_demo_with_azn_and_baku`, `test_halls_and_tables_shape`, `test_qr_tokens_match_pattern_and_are_unique`, `test_categories_and_dishes_reference_each_other`, `test_every_dish_has_default_and_vip_prices_as_two_place_decimals`, `test_dish_texts_in_az_and_ru_within_limits`, `test_allergen_examples_cover_verified_and_unknown`, `test_exactly_one_hidden_and_one_unavailable_dish`, `test_visit_cart_and_order_use_orderable_dishes`, `test_order_total_uses_table_tier_prices`, `test_price_for_falls_back_to_default_tier`, `test_fixed_ids_are_deterministic_and_distinct`, `test_success_prints_relative_guest_links`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `uv run python -m app.seed` | Код 0; выводятся относительные ссылки гостя `/t/demo-table-0N-dev-only` (без `http`), неактивный стол помечен |
| 2 | Проверить заведение | Одно, `Demo Restoran`, `AZN`, `Asia/Baku`, языки `az`, `ru`, фиксированный `DEMO_TENANT_ID` |
| 3 | Залы и столы | 2 зала, 6 столов с уникальными `qr_token`; один кабинет `cabin` с тарифом `vip`; один стол неактивен |
| 4 | Меню | 4 категории, 12–20 позиций; у каждой цены `default` и `vip` с двумя знаками; названия и описания AZ/RU; одна позиция скрыта, одна в стоп-листе; валюта `AZN` |
| 5 | Аллергены | Справочник 14 кодов ЕС; есть meta с `allergens_verified = true` и с `false`; связи позиции совпадают с данными |
| 6 | Визит и заказ | Один открытый визит на столе 1, 2 сообщения, 2 строки корзины; один заказ `submitted`, итог = сумма строк по тарифу стола; событие `created` |

---

## TC-53-002: Повторный запуск не меняет число строк (идемпотентность)

**Priority:** Critical
**Type:** Functional
**AC:** AC-6 (после второго запуска число строк во всех таблицах не меняется)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_seed.py::test_seed_twice_gives_same_row_counts`, `test_cli_twice_commits_same_data`, `test_seed_restores_reference_values`, `test_seed_attaches_lines_to_existing_order_with_same_idempotency_key`; без БД — `tests/test_seed_loader.py` (контракт загрузчика: `test_reference_rows_are_upserted_by_natural_key`, `test_history_rows_are_insert_only`, `test_only_allergen_links_are_deleted`, `test_reference_upsert_restores_every_seed_column`, `test_parents_are_written_before_children`, `test_statement_count_matches_dataset`, `test_updated_at_is_refreshed_explicitly`, `test_visit_is_reopened_and_messages_unredacted` и др.).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Перед запуском посчитать строки всех таблиц | Все 0 |
| 2 | Запустить сид, посчитать строки | Совпадает с эталоном `EXPECTED_COUNTS` |
| 3 | Запустить сид второй раз (в т.ч. через CLI с фиксацией транзакции) | Количество строк в каждой таблице то же |
| 4 | Изменить демо-данные (цена 99.99, скрыть позицию, лишний аллерген, закрыть визит), запустить сид | Эталонные значения восстановлены (цена 6.50, позиция видима, лишней связи нет, визит открыт), число строк — эталонное |

---

## TC-53-003: Сид отказывается работать при APP_ENV=prod

**Priority:** Critical
**Type:** Security / Negative
**AC:** AC-6 (при `APP_ENV=prod` команда отказывается работать); NFR-6 spec
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_seed.py::test_prod_is_refused_with_exit_code_2`, `test_prod_refusal_does_not_need_other_settings`, `test_module_entry_point_refuses_prod_in_subprocess`, `test_module_guard_raises_system_exit_with_main_code`, `test_invalid_app_env_is_config_error`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `APP_ENV=prod`, `python -m app.seed` (настоящий подпроцесс) | Код 2, сообщение на русском с `APP_ENV=prod` в stderr |
| 2 | `APP_ENV=prod`, `--database-url <адрес>` | Код 2, к базе не подключается, данные не пишутся |
| 3 | `APP_ENV=prod` без `PUBLIC_BASE_URL` и других настроек prod | Код 2 (отказ раньше проверки остальной конфигурации) |
| 4 | `APP_ENV=production` (недопустимое значение) | Код 1, сообщение называет `APP_ENV` |

### Notes
Security review (LOW): защита проверяет `APP_ENV` локальной машины, а не целевую базу; запуск с `APP_ENV=dev` и `--database-url` на боевую базу создаст демо-заведение с предсказуемыми токенами. Рекомендация — отказ при наличии в базе заведений кроме `DEMO_TENANT_ID`; `APP_ENV=prod` в чек-листе деплоя. Тестом не покрыто (вне AC). **Обновление 2026-10-28:** проверка целевой базы реализована в #60 — TC-60-001, TC-60-002, TC-60-010 (`docs/test-cases/feature-60-demo-seed-guard.md`); пункт чек-листа деплоя — в задачах G6.

---

## TC-53-004: В сид-данных нет IP-адресов, секретов и реальных данных заведения

**Priority:** High
**Type:** Security
**AC:** AC-6 (в данных нет IP-адресов, секретов и реальных данных заведения); CLAUDE.md (публичный репозиторий)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_seed.py::test_no_ip_addresses_or_secrets_in_seed_data`, `test_secret_and_ip_patterns_detect_violations`, `test_tenant_is_fictional_demo_with_azn_and_baku`, `test_qr_tokens_match_pattern_and_are_unique`. Реальные данные заведения — по названию `Demo Restoran` и вымышленным блюдам (проверка состава — визуально при ревью).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Просканировать исходник `app/seed/data.py` и все строковые значения сида шаблонами IP и секретов | Совпадений нет |
| 2 | Проверить сами шаблоны на заведомых нарушениях (`10.1.2.3`, `postgresql://user:pw@host/db`, `sk-ant-…`) | Шаблоны срабатывают; `demo-table-01-dev-only` — не секрет |
| 3 | Проверить токены столов | Префикс `demo-table-`, суффикс `dev-only`, длина ≥ 22, формат CHECK `qr_token` |

---

## TC-53-005: Ошибки запуска — без схемы, неверный пароль, неверный адрес

**Priority:** High
**Type:** Negative / Security
**AC:** AC-6 (расширение: команда при ошибке не раскрывает пароль `DATABASE_URL`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_seed.py::test_cli_without_schema_fails_with_hint`, `test_cli_wrong_password_is_not_shown`, `test_seed_does_not_touch_foreign_table_with_same_token`; `tests/test_seed_loader.py::test_global_keys_are_guarded_by_tenant`, `test_foreign_row_raises_seed_error_and_stops`; `tests/test_seed.py::test_database_error_is_exit_1_without_password`, `test_invalid_database_url_is_config_error_without_value`, `test_database_url_argument_overrides_environment`, `test_lookup_helpers_raise_for_unknown_keys`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Сид на пустой схеме (без миграций) | Код 1, подсказка «alembic upgrade head» |
| 2 | Сид с неверным паролем в `--database-url` | Код 1, «Не удалось загрузить демо-данные», пароль не выводится ни в stdout, ни в stderr |
| 3 | `--database-url mysql://...` | Код 1, сообщение называет `DATABASE_URL`, пароль не выводится |
| 4 | Ошибка БД во время загрузки | Код 1, пароль заменён на `***` |
| 5 | В базе есть стол другого заведения с демо-токеном | `SeedError` по `tables`, загрузка останавливается, транзакция откатывается, чужой стол не изменён (`DO UPDATE … WHERE tenant_id`) |
| 6 | `--database-url` при заданном `DATABASE_URL` | Используется аргумент |

---

## TC-53-006: Азербайджанские названия аллергенов и блюд проверены носителем языка

**Priority:** Low
**Type:** Functional (локализация)
**AC:** AC-6 (данные на AZ/RU); технические заметки issue: «корректность азербайджанских названий проверить носителем» (ТЗ AI-6)
**E2E Automated:** No
**Автоматизация:** Ручной.
**Статус прогона:** НЕ ВЫПОЛНЕН (нужен носитель азербайджанского языка)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Выгрузить `name_az` из `EU14_ALLERGENS` (`app/models/reference.py`) и `name_az`/`description_az` демо-блюд из `app/seed/data.py` | Список из 14 аллергенов и 12–20 блюд |
| 2 | Носитель проверяет орфографию и терминологию | Ошибок нет или заведены правки |

---

## TC-53-007: Повторный сид при закрытом демо-визите и другом открытом визите на столе

**Priority:** Medium
**Type:** Negative (идемпотентность в реальном dev-сценарии)
**AC:** AC-6 (повторный запуск не меняет данные и не падает)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_seed.py::test_seed_rerun_when_demo_table_has_another_open_visit` (добавлен tester 2026-10-13; после исправления #58 маркер `xfail` снят).
**Статус прогона:** PASS (дефект #58 исправлен: сид закрывает чужой открытый визит на демо-столе с `closed_by = timeout`)

### Preconditions
- Сид уже загружен.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Закрыть демо-визит (`status = closed`, `closed_by = staff`) | Успех |
| 2 | Открыть на «Столе 1» новый визит (как после работы с приложением в dev) | Успех |
| 3 | Запустить сид повторно | **Ожидается:** сид завершается без ошибок (демо-визит не мешает открытому визиту или корректно разрешает конфликт). **Факт:** `IntegrityError` по `uq_visits_open_table`, сид прерывается (транзакция откатывается, данные не портятся) |

### Notes
Дефект не нарушает AC-6 в формулировке «два запуска подряд на пустой базе» (TC-53-002 PASS), но мешает типовому повторному запуску сида в dev. Задача на исправление — #58 (решение — за dev-lead: например, не переоткрывать демо-визит, если на столе есть другой открытый визит).

---

## Related TCs
- TC-49-001 (глобальная уникальность `qr_token` — основа TC-53-005, шаг 5)
- TC-50-008 (справочник 14 аллергенов ЕС)
- TC-52-005 (сид не изменяет и не удаляет `order_events`: только `ON CONFLICT DO NOTHING`)
- TC-48-004 (db-тесты сида выполняются только на базе `*_test`)
- TC-60-001…TC-60-010 (#60: сид отказывается работать с базой, где есть другие заведения; TC-60-005 — регрессия TC-53-003)
