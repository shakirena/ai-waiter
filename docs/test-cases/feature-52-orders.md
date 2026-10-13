# Test Cases: Story #52 — Модель данных: orders, order_items, order_events

**Feature:** #7 «Модель данных v1 и миграции Alembic» (story #52, AC-5)
**Spec:** docs/specs/feature-7-data-model.md (FR-7, NFR-1, NFR-2, NFR-3)
**Arch:** docs/arch/feature-7-data-model.md (ADR-7.2, ADR-7.3, ADR-7.4, ADR-7.6, ADR-7.7, ревизия `0004_orders`)
**Created:** 2026-10-12

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-12: локально (Windows, PostgreSQL 16, `ai_waiter_test`) 1017 passed, 3 skipped, все db-тесты PASS; CI PR #57 — 5/5.

Общее предусловие: применены миграции до `0004_orders` (или `upgrade head`); у открытого визита есть заказ с `idempotency_key = k1` в статусе `submitted` и две позиции («Toyuq plov» 12.50 и «Çay» 3.00); тест работает через `db_session` с откатом.

---

## TC-52-001: Повтор idempotency_key не создаёт второй заказ

**Priority:** Critical
**Type:** Functional / Negative
**AC:** AC-5 (повтор `idempotency_key` отклоняется уникальным ограничением); NFR-3 spec (надёжность заказа)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_orders.py::test_ac5_scenario`, `test_idempotency_key_unique_only_within_tenant`, `test_several_orders_per_visit`; `tests/test_models_metadata.py::test_order_uniques_and_types`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вставить второй заказ заведения A с ключом `k1` (тот же или другой визит) | `IntegrityError`, `uq_orders_tenant_id_idempotency_key` |
| 2 | Заказ заведения B с ключом `k1` | Принимается (уникальность в пределах заведения, нет межарендного «оракула») |
| 3 | Три заказа одного визита с разными ключами (дозаказ) | Принимаются |
| 4 | Проверить новый заказ | `status = 'submitted'`, `id` — UUIDv7, `created_at` — aware-datetime |

---

## TC-52-002: Ровно 8 статусов жизненного цикла

**Priority:** Critical
**Type:** Functional / Negative
**AC:** AC-5 (неизвестный статус отклоняется CHECK; допустимы ровно `submitted`, `edited`, `confirmed`, `rejected`, `escalated`, `sent_to_pos`, `in_pos`, `pos_failed`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_orders.py::test_ac5_scenario`, `test_all_eight_statuses_accepted` (8), `test_unknown_order_status_rejected` (4); `tests/test_order_status.py::test_exactly_eight_statuses_from_tz`, `test_unknown_status_is_an_error`, таблица переходов (9 тестов); `tests/db/test_migrations.py::test_check_constraint_values_match_enums[ck_orders_status]`; `tests/test_models_metadata.py::test_order_check_texts`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `UPDATE orders SET status = 'unknown_status'` | `ck_orders_status` |
| 2 | Вставка с `status` = `SUBMITTED`, `cancelled`, пустая строка | `ck_orders_status` |
| 3 | Вставка с каждым из 8 статусов (с `confirmed_at` / `reject_reason`, где требуется) | Все принимаются |
| 4 | Сверить CHECK с `OrderStatus` | Набор значений совпадает, ровно 8 |

### Notes
Переходы между статусами проверяет сервис (#12, #17); `tests/test_order_status.py` уже фиксирует таблицу переходов (в т.ч. `escalated → edited`, вопрос 33 spec).

---

## TC-52-003: Подтверждение и отклонение — обязательные поля

**Priority:** High
**Type:** Negative
**AC:** AC-5 (статус `confirmed` с `confirmed_at`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_orders.py::test_ac5_scenario`, `test_confirming_without_confirmed_at_rejected_on_update`, `test_order_checks` (13 случаев), `test_pos_fields_accepted`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `status = 'confirmed'`, `confirmed_at = now()`, `confirmed_by_staff_id` = uuid | Принимается; `confirmed_at` читается как то же aware-время |
| 2 | `confirmed`, `sent_to_pos`, `in_pos`, `pos_failed` без `confirmed_at` (вставка и `UPDATE`) | `ck_orders_confirmed_at` |
| 3 | `rejected` без `reject_reason`; с пустой причиной; причина > 500 | `ck_orders_reject_reason`, `ck_orders_reject_reason_length` |
| 4 | `total` или `pos_total` = -0.01 | `ck_orders_total`, `ck_orders_pos_total` |
| 5 | `currency = 'azn'`, `price_tier = 'VIP'`, `pos_ref` > 64, `pos_error` > 1000 | Соответствующие `ck_orders_*` |
| 6 | `in_pos` с `pos_ref = 'A-1042'`, `pos_total = 15.50`, без `confirmed_by_staff_id` | Принимается (прототип без входа персонала) |

---

## TC-52-004: Позиции заказа хранят снимок названия и цены

**Priority:** Critical
**Type:** Functional
**AC:** AC-5 (позиции хранят снимок названия (`pos_name`) и цены независимо от последующих изменений меню)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_orders.py::test_ac5_scenario`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Позиции заказа с `name_snapshot = menu_items.pos_name` и `price_at_order` | Сохранены |
| 2 | Переименовать позицию меню в «Plov (yeni)», цену `default` изменить на 14.00 | Успех |
| 3 | Прочитать строку заказа | `("Toyuq plov", Decimal("12.50"))` — снимок не изменился |

---

## TC-52-005: Журнал order_events только дописывается

**Priority:** Critical
**Type:** Security / Negative
**AC:** AC-5 (событие связано с заказом и не может быть изменено или удалено (триггер))
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_orders.py::test_ac5_scenario`, `test_append_only_blocks_bulk_update_and_delete`, `test_rollback_of_inserted_events_works`; `tests/db/test_migrations.py::test_append_only_trigger_created_and_dropped_with_revision`, `test_schema_reset_works_with_trigger`; `tests/test_migrations_offline.py::test_offline_sql_creates_and_drops_append_only_trigger`, `test_offline_upgrade_head_has_all_fifteen_tables_and_trigger`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Записать событие `status_changed` (`submitted → confirmed`, `actor_type = staff`, `actor_id`) | Сохранено; `created_at` — aware-datetime; `payload = {}` |
| 2 | `UPDATE order_events SET actor_type = 'system'` для события | `IntegrityError`, SQLSTATE `restrict_violation`, текст «order_events is append-only» |
| 3 | `DELETE` события | То же |
| 4 | Массовый `UPDATE` всей таблицы и `DELETE` по условию | Отклоняются; число событий не меняется |
| 5 | Прочитать событие | `order_id`, `type`, `actor_type`, `actor_id` — исходные |
| 6 | Откат транзакции со вставленными событиями | События исчезают (откат не блокируется триггером) |
| 7 | `alembic downgrade -1` с `0004_orders`, затем `upgrade` | Триггер и функция удаляются и создаются вместе с ревизией |

---

## TC-52-006: Позиции заказа — CHECK, уникальность, мягкое удаление

**Priority:** High
**Type:** Negative
**AC:** AC-5 (позиции заказа); FR-7 spec (`removed_by_staff`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_orders.py::test_order_item_qty_out_of_range_rejected[0|-1|100]`, `test_order_item_checks` (2), `test_order_item_unique_per_comment_and_soft_removal`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `qty` = 0, -1, 100 | `ck_order_items_qty` |
| 2 | `price_at_order = -0.01`; `comment` > 200 | `ck_order_items_price_at_order`, `ck_order_items_comment` |
| 3 | Позиция с `qty = 99` без комментария | `comment = ''`, `removed_by_staff = false` |
| 4 | Та же позиция с тем же комментарием | `uq_order_items_tenant_id_order_id_menu_item_id_comment` |
| 5 | Та же позиция с комментарием «без лука», затем `removed_by_staff = true` у первой строки | Обе строки остаются |

---

## TC-52-007: События заказа — CHECK типа, исполнителя и статусов

**Priority:** High
**Type:** Negative
**AC:** AC-5 (событие сохраняется с типом, исполнителем и временем)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_orders.py::test_order_event_checks` (6), `test_all_event_types_including_manual_pos_entry`; `tests/test_models_metadata.py::test_order_event_types_include_manual_pos_entry`; `tests/db/test_migrations.py::test_check_constraint_values_match_enums[ck_order_events_*]`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `type = 'deleted'` | `ck_order_events_type` |
| 2 | `actor_type = 'admin'` | `ck_order_events_actor_type` |
| 3 | `status_changed` без `to_status`; с `to_status = unknown_status`; `from_status = unknown_status` | `ck_order_events_status_change`, `ck_order_events_to_status`, `ck_order_events_from_status` |
| 4 | `payload` — массив | `ck_order_events_payload` |
| 5 | По одному событию 8 типов (`created`, `status_changed`, `item_removed`, `item_qty_changed`, `pos_ack`, `pos_error`, `pos_total_mismatch`, `manual_pos_entry`) | Все приняты; статус заказа `pos_failed` не меняется |

### Notes
Колонка типа события называется `type` (в issue — `event_type`); FK `order_events → orders` — RESTRICT (в issue — CASCADE), принято в ADR-7.6: заказ с журналом не удаляется.

---

## TC-52-008: Межарендные ссылки заказов отклоняются БД

**Priority:** Critical
**Type:** Security (tenant-изоляция)
**AC:** AC-5; NFR-1 spec; ADR-7.3 (позиция заказа со ссылкой на позицию меню другого заведения отклоняется БД)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_tenant_isolation.py::test_order_cannot_reference_visit_of_other_tenant`, `test_order_item_cannot_reference_menu_item_of_other_tenant`, `test_order_item_cannot_reference_order_of_other_tenant`, `test_order_event_cannot_reference_order_of_other_tenant`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Заказ заведения A на визит B | `IntegrityError` |
| 2 | Позиция заказа A с позицией меню B | `IntegrityError` |
| 3 | Позиция с `tenant_id = A` на заказ B | `IntegrityError` |
| 4 | Событие с `tenant_id = A` на заказ B | `IntegrityError` |

---

## TC-52-009: Правила удаления и индексы ленты заказов

**Priority:** Medium
**Type:** Functional
**AC:** AC-5 (расширение: FR-7 spec, индексы для ленты и эскалации)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_orders.py::test_on_delete_rules`, `test_pending_and_pos_queue_partial_indexes`; `tests/test_models_metadata.py::test_order_on_delete_rules`, `test_order_indexes`, `test_order_defaults`; `tests/db/test_migrations.py::test_downgrade_one_step_drops_only_revision_tables[0004_orders]`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | (Служебно) удалить заказ без событий | Позиции удаляются каскадом |
| 2 | Удалить заказ с событиями | `fk_order_events_tenant_id_order_id_orders` (RESTRICT) |
| 3 | Удалить визит с заказом; позицию меню из заказа | `fk_orders_tenant_id_visit_id_visits`, `fk_order_items_tenant_id_menu_item_id_menu_items` |
| 4 | Проверить индексы `orders` | `ix_orders_pending_confirm` (`submitted`, `edited`), `ix_orders_pos_queue` (`confirmed`, `sent_to_pos`) |

---

## Related TCs
- TC-51-001 (заказ принадлежит визиту)
- TC-50-003 (позиция меню из заказа не удаляется)
- TC-53-001 (сид создаёт заказ с событием `created`)
- TC-54-004 (`total`, `pos_total`, `price_at_order` — `NUMERIC(10,2)`)
