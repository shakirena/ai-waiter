# Test Cases: Story #40 — Режим scaled: заготовки Redis pub/sub, arq, Redis RateLimiter

**Feature:** #6 «Каркас проекта» (story #40, AC-4)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-40-001: Доставка события, задача в очереди arq, общий счётчик лимита

**Priority:** Critical
**Type:** Functional
**AC:** AC-4 (Given `APP_MODE=scaled` и `REDIS_URL`, тестовый Redis или его замена / When публикация, постановка задачи, запросы лимита / Then событие доходит до другого экземпляра, задача попадает в arq и обрабатывается worker-ом, счётчик общий)
**E2E Automated:** No
**Автоматизация:** Авто на fakeredis — `test_scaled_events.py::test_event_delivered_to_subscriber_of_another_instance`, `test_scaled_scheduler.py::test_enqueue_puts_job_into_arq_queue`, `test_scaled_worker.py::test_enqueued_task_is_processed_by_worker`, `test_scaled_ratelimit.py::test_counter_is_shared_between_instances`. На настоящем Redis — `test_scaled_redis.py` (3 теста, маркер `scaled`).
**Статус прогона:** PASS на fakeredis (локально и в CI). Тесты с настоящим Redis выполняются в CI-джобе `backend (postgres + redis)` (зелёный на PR #47); локально пропущены (Redis не установлен).

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Два экземпляра `RedisEventBus` на одном Redis; подписчик на втором, публикация с первого | Подписчик второго экземпляра получает событие |
| 2 | `ArqTaskScheduler.enqueue("demo", {...})` | Задание в очереди arq в формате JSON (не pickle); повторный `job_id` не дублируется |
| 3 | Запустить worker с `WorkerSettings` | Задача выполнена зарегистрированным обработчиком |
| 4 | Два `RedisRateLimiter` на одном Redis делают запросы | Счётчик общий; сверх лимита — отказ с временем до сброса |

---

## TC-40-002: scaled без REDIS_URL и защита значения адреса

**Priority:** Critical
**Type:** Negative / Security
**AC:** AC-4 (без `REDIS_URL` приложение не стартует с понятной ошибкой)
**E2E Automated:** No
**Автоматизация:** Авто — `test_scaled_worker.py::test_worker_requires_scaled_mode`, `test_worker_requires_redis_url`, `test_worker_invalid_redis_url_hides_value`; `test_container.py::test_scaled_without_redis_url_is_startup_error`; `test_scaled_events.py::test_not_started_raises`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запустить worker в режиме `single` | Понятная ошибка |
| 2 | Запустить worker без `REDIS_URL` | Ошибка с названием переменной |
| 3 | Передать некорректный `REDIS_URL` с паролем | Ошибка не содержит значения URL |

---

## TC-40-003: Отказоустойчивость Redis-реализаций

**Priority:** High
**Type:** Negative
**AC:** AC-4 (заготовки не должны подвешивать приложение)
**E2E Automated:** No
**Автоматизация:** Авто — `test_scaled_events.py` (потеря соединения завершает итерацию, невалидные сообщения пропускаются, медленный подписчик теряет старые события с предупреждением, ошибки закрытия логируются), `test_scaled_scheduler.py` (отмена задачи в работе и гонка с worker-ом возвращают `False`), `test_scaled_ratelimit.py` (ключ без TTL исправляется, окно фиксированное), `test_scaled_connection.py` (таймаут соединения, JSON-сериализатор отвергает NaN).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Оборвать соединение подписчика | Итерация завершается без исключения наружу |
| 2 | Прислать в канал не-JSON сообщение | Сообщение пропущено |
| 3 | Ключ rate-limit без TTL | Ключ исправляется, окно не «залипает» |

---

## Related TCs
- TC-43-001 (worker и Redis в docker compose)
- TC-39-001 (аналог для single)
