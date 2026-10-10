# Test Cases: Story #39 — Режим single: EventBus в памяти, APScheduler, RateLimiter в памяти

**Feature:** #6 «Каркас проекта» (story #39, AC-3)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-39-001: Сквозной сценарий single без Redis

**Priority:** Critical
**Type:** Functional
**AC:** AC-3 (Given `APP_MODE=single` без Redis / When подписка, публикация, задача через 1 с, превышение лимита / Then событие получено, задача выполнена один раз через ~1 с, сверх лимита — отказ с временем до сброса, остановка без зависших задач)
**E2E Automated:** No
**Автоматизация:** Авто — `backend/tests/test_single_mode.py::test_single_mode_end_to_end_without_redis`, `test_events.py::test_subscriber_receives_published_event`, `test_scheduler.py::test_delayed_task_runs_once_after_about_one_second`, `test_ratelimit.py::test_limit_exceeded_within_window`, `test_remaining_and_retry_after_follow_window`, `test_events.py::test_stop_closes_active_subscriptions_without_hanging`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Подписаться на канал `tenant_channel(1, ...)` | Подписка активна |
| 2 | Опубликовать событие | Подписчик получает копию события |
| 3 | `enqueue("demo", delay=1 с)` | Обработчик вызван один раз через ~1 с |
| 4 | Сделать `limit + 1` запросов `RateLimiter.hit` | Последний — отказ, `retry_after` больше нуля |
| 5 | Остановить приложение | Планировщик и подписки закрыты, завершение быстрее таймаута |

---

## TC-39-002: Изоляция тенантов и медленный подписчик

**Priority:** High
**Type:** Security / Negative
**AC:** AC-3 (+ мультиарендность)
**E2E Automated:** No
**Автоматизация:** Авто — `test_events.py::test_other_tenant_channel_is_isolated`, `test_slow_subscriber_does_not_block_publisher`, `test_drop_warning_repeats_every_n_drops`, `test_events_published_before_subscribe_are_not_delivered`, `test_qa_coverage_gaps.py::test_push_to_closed_subscription_is_ignored`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Подписаться на канал тенанта 1, опубликовать событие тенанта 2 | События не приходят |
| 2 | Не читать из подписки, опубликовать больше `queue_size` событий | Публикация не блокируется, самые старые отбрасываются, в лог пишется предупреждение |

---

## TC-39-003: Планировщик — идемпотентность, отмена, остановка

**Priority:** High
**Type:** Functional / Negative
**AC:** AC-3 (задача выполняется один раз; при остановке нет зависших задач)
**E2E Automated:** No
**Автоматизация:** Авто — `test_scheduler.py` (21 тест), `test_qa_coverage_gaps.py::test_cancel_pending_job_without_running_apscheduler`: повторный `job_id` не создаёт дубль, `cancel`, периодические задачи не запускаются параллельно, `stop` дожидается или отменяет по таймауту, неизвестная задача и не-JSON payload отвергаются.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Дважды `enqueue` с одним `job_id` | Задача выполняется один раз |
| 2 | `cancel` ожидающей задачи | `True`, задача не запускается; повторный `cancel` — `False` |
| 3 | `enqueue` неизвестной задачи / payload с `Decimal` / отрицательная задержка | `KeyError` / `TypeError` / `ValueError` |
| 4 | `stop` при долгой задаче | Завершение не позже `shutdown_timeout` |

---

## TC-39-004: RateLimiter в памяти — окно и ограничение памяти

**Priority:** High
**Type:** Functional / Negative
**AC:** AC-3 (запрос сверх лимита получает отказ с временем до сброса окна)
**E2E Automated:** No
**Автоматизация:** Авто — `test_ratelimit.py` (18 тестов): фиксированное окно, отказы не продлевают окно, `reset`, лимит числа ключей (вытеснение), независимость ключей, проверка аргументов как в scaled.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Исчерпать лимит ключа | Отказ, `retry_after` убывает со временем |
| 2 | Дождаться конца окна (инъекция часов) | Новое окно, счётчик с нуля |
| 3 | Создать больше ключей, чем `max_keys` | Память ограничена, сначала удаляются истёкшие |

---

## Related TCs
- TC-38-001 (фабрика создаёт эти реализации)
- TC-40-001 (аналог для scaled)
