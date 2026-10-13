# Test Cases: Story #51 — Модель данных: visits, messages, cart_items

**Feature:** #7 «Модель данных v1 и миграции Alembic» (story #51, AC-4)
**Spec:** docs/specs/feature-7-data-model.md (FR-6, NFR-1, NFR-2, NFR-8)
**Arch:** docs/arch/feature-7-data-model.md (ADR-7.3, ADR-7.4, ADR-7.5, ADR-7.7, ревизия `0003_visits`)
**Created:** 2026-10-12

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-12: локально (Windows, PostgreSQL 16, `ai_waiter_test`) 1017 passed, 3 skipped, все db-тесты PASS; CI PR #57 — 5/5.

Общее предусловие: применены миграции до `0003_visits` (или `upgrade head`); в заведении есть стол и позиция меню с ценой `default` 12.50; тест работает через `db_session` с откатом.

---

## TC-51-001: На столе не более одного открытого визита

**Priority:** Critical
**Type:** Functional / Negative
**AC:** AC-4 (второй открытый визит на том же столе отклоняется частичным уникальным индексом; после закрытия визита новый открывается)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_visits.py::test_ac4_scenario`, `test_only_open_visits_are_unique_per_table`, `test_reopening_closed_visit_while_another_is_open_rejected`, `test_partial_unique_index_in_database`, `test_concurrent_open_race_resolved_by_index`; `tests/test_migrations_offline.py::test_offline_sql_contains_partial_open_visit_index`; `tests/test_models_metadata.py::test_visit_indexes`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть визит на столе | `status = 'open'`, `id` — UUIDv7, `opened_at` и `last_activity_at` — aware-datetime, `closed_*` — NULL |
| 2 | Вставить второй открытый визит на тот же стол | `IntegrityError`, `uq_visits_open_table` (`(table_id) WHERE status = 'open'`) |
| 3 | `INSERT … ON CONFLICT (table_id) WHERE status = 'open' DO NOTHING` (гонка двух сканирований) | Строка не вставлена, открытый визит один |
| 4 | Закрыть визит (`closed_by` = `staff`/`pos`/`timeout`), открыть новый | Новый визит принимается, `id` отличается |
| 5 | Повторно открыть старый закрытый визит при наличии открытого | Отклоняется `uq_visits_open_table` |
| 6 | Открытый визит на другом столе | Принимается |

---

## TC-51-002: Корзина — строки с разными комментариями и цена на момент добавления

**Priority:** Critical
**Type:** Functional / Negative
**AC:** AC-4 (повторная строка корзины с тем же комментарием отклоняется, строка с другим комментарием принимается, цена на момент добавления хранится в строке корзины)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_visits.py::test_ac4_scenario`, `test_cart_item_vip_tier_snapshot`; `tests/test_models_metadata.py::test_cart_item_uniques_and_defaults`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Добавить позицию в корзину без комментария, `price_at_add = 12.50` | `comment = ''` |
| 2 | Добавить ту же позицию ещё раз с пустым комментарием | `IntegrityError`, `uq_cart_items_tenant_id_visit_id_menu_item_id_comment` |
| 3 | Добавить ту же позицию с комментарием «без лука» | Принимается |
| 4 | Прочитать `price_at_add` строк | `[Decimal("12.50"), Decimal("12.50")]`, тип `Decimal` |
| 5 | Стол с тарифом `vip`: строка с `price_tier = 'vip'`, `price_at_add = 15.00` | Тариф и цена сохранены |

---

## TC-51-003: Количество в корзине 1..99

**Priority:** High
**Type:** Negative
**AC:** AC-4 (количество вне диапазона 1..99 отклоняется CHECK)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_visits.py::test_cart_qty_out_of_range_rejected[0|-1|100]`, `test_cart_qty_bounds_accepted[1|99]`, `test_cart_item_checks` (3 случая).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `qty` = 0, -1, 100 | `ck_cart_items_qty` |
| 2 | `qty` = 1 и 99 | Принимается |
| 3 | `comment` длиной 201 | `ck_cart_items_comment` |
| 4 | `price_tier = 'VIP'` | `ck_cart_items_price_tier` |
| 5 | `price_at_add = -0.01` | `ck_cart_items_price_at_add` |

---

## TC-51-004: CHECK визита — status, lang, closed_by и согласованность закрытия

**Priority:** High
**Type:** Negative
**AC:** AC-4 (недопустимые `status`, `lang`, `closed_by` отклоняются CHECK; допустимы `staff`/`pos`/`timeout`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_visits.py::test_visit_checks` (8 случаев), `test_unknown_visit_status_rejected_by_status_check`, `test_closed_visit_accepted[staff|pos|timeout]`; `tests/test_models_metadata.py::test_visit_check_texts`, `test_visit_defaults_and_soft_staff_reference`; `tests/db/test_migrations.py::test_check_constraint_values_match_enums[ck_visits_status|ck_visits_lang|ck_visits_closed_by]`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `lang = 'en'` | `ck_visits_lang` |
| 2 | `status = 'archived'` | Отклоняется (`ck_visits_closed_state`; при снятом `ck_visits_closed_state` — `ck_visits_status`) |
| 3 | `status = 'closed'` без `closed_at` и/или `closed_by` | `ck_visits_closed_state` |
| 4 | Открытый визит с `closed_at` или `closed_by` | `ck_visits_closed_state` |
| 5 | Закрытый визит с `closed_by = 'waiter'` | `ck_visits_closed_by` |
| 6 | Закрытый визит с `closed_by` = `staff` (+ `closed_by_staff_id`), `pos`, `timeout` | Принимается; `closed_by_staff_id` — uuid без FK (до #19) |

---

## TC-51-005: Сообщения диалога — роль, токены, стоимость, обезличивание

**Priority:** High
**Type:** Functional / Negative
**AC:** AC-4 (недопустимая роль сообщения отклоняется CHECK); FR-6 spec (токены `input`/`output`/`cache_*`, `cost_usd`, `latency_ms`, `redacted_at`); NFR-8 spec (индекс `(tenant_id, created_at)`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_visits.py::test_message_checks` (12 случаев), `test_message_defaults_and_cost_precision`, `test_message_redaction_keeps_tokens_and_cost`, `test_partial_unique_index_in_database`; `tests/test_models_metadata.py::test_message_roles_are_claude_api_roles`, `test_message_indexes_and_columns`; `tests/db/test_schema_invariants.py::test_numeric_exceptions_exist_with_exact_type`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Сообщение гостя с минимальными полями | Токены 0, `cost_usd = 0`, `created_at` — aware-datetime |
| 2 | Ответ `assistant` с блоком `tool_use` в `content`, токенами, `cost_usd = 0.001234`, `latency_ms = 850` | Сохраняется; `cost_usd` читается как `Decimal("0.001234")` (`NUMERIC(12,6)`) |
| 3 | `role` = `system` и `tool` | `ck_messages_role` (допустимы только `user`, `assistant` — роли Claude API) |
| 4 | `content` — объект вместо массива; `content = NULL` без обезличивания; `text` > 8000 | `ck_messages_content`, `ck_messages_content_or_redacted`, `ck_messages_text` |
| 5 | Отрицательные `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `cost_usd`, `latency_ms` | Соответствующие `ck_messages_*` |
| 6 | Выставить `redacted_at`, оставив `text` или `content` | `ck_messages_redacted_empty` |
| 7 | Обезличить: `text = NULL`, `content = NULL`, `redacted_at = now()` | Принимается; токены и `cost_usd` сохраняются |
| 8 | Проверить индексы | `ix_messages_tenant_id_created_at`, `ix_messages_retention` (`created_at WHERE redacted_at IS NULL`) |

### Notes
В технических заметках issue роли — `user`/`assistant`/`tool`/`system`; по ADR-7.4 приняты только `user`/`assistant` (результаты функций передаются блоками `tool_result` в `user`). AC «роль сообщения отклоняется CHECK» выполняется.

---

## TC-51-006: Межарендные ссылки визитов, корзины и сообщений отклоняются БД

**Priority:** Critical
**Type:** Security (tenant-изоляция)
**AC:** AC-4 (строка корзины со ссылкой на позицию меню другого заведения отклоняется составным внешним ключом); NFR-1 spec; ADR-7.3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenant_isolation.py::test_visit_cannot_reference_table_of_other_tenant`, `test_cart_item_cannot_reference_menu_item_of_other_tenant`, `test_cart_item_cannot_reference_visit_of_other_tenant`, `test_message_cannot_reference_visit_of_other_tenant`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Визит заведения A на стол B | `IntegrityError` |
| 2 | Строка корзины визита A с позицией меню B | `IntegrityError` (составной FK `(tenant_id, menu_item_id)`) |
| 3 | Строка корзины с `tenant_id = A` на визит B | `IntegrityError` |
| 4 | Сообщение с `tenant_id = A` на визит B | `IntegrityError` |

---

## TC-51-007: Правила удаления — CASCADE для визита, RESTRICT для стола и меню

**Priority:** Medium
**Type:** Functional
**AC:** AC-4 (расширение: `messages`, `cart_items` принадлежат визиту; NFR-7 spec)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_visits.py::test_deleting_visit_cascades_messages_and_cart`, `test_restrict_on_table_and_menu_item`; `tests/test_models_metadata.py::test_visit_on_delete_rules`; `tests/db/test_migrations.py::test_downgrade_one_step_drops_only_revision_tables[0003_visits]`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | (Служебно) удалить визит с сообщениями и корзиной | Сообщения и строки корзины удалены каскадом, позиция меню на месте |
| 2 | Удалить стол с визитом | `fk_visits_tenant_id_table_id_tables` (RESTRICT) |
| 3 | Удалить позицию меню, которая есть в корзине | `fk_cart_items_tenant_id_menu_item_id_menu_items` (RESTRICT) |
| 4 | `alembic downgrade -1` с `0003_visits` | Удалены ровно `visits`, `messages`, `cart_items` |

---

## Related TCs
- TC-49-001 (визит открывается на стол, найденный по `qr_token`)
- TC-50-007 (цена позиции — источник `price_at_add`)
- TC-52-001 (заказ ссылается на визит)
- TC-54-004 (исключение `messages.cost_usd` из правила `NUMERIC(10,2)`)
