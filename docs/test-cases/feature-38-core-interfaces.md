# Test Cases: Story #38 — Интерфейсы EventBus, TaskScheduler, RateLimiter с выбором реализации по режиму

**Feature:** #6 «Каркас проекта» (story #38, AC-2)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-38-001: Фабрика возвращает реализации по APP_MODE

**Priority:** Critical
**Type:** Functional
**AC:** AC-2 (Given каркас запущен и определён `APP_MODE` / When приложение запрашивает компоненты через фабрику / Then возвращается реализация режима)
**E2E Automated:** No
**Автоматизация:** Авто — `backend/tests/test_container.py::test_single_mode_uses_in_memory_implementations`, `test_scaled_mode_uses_redis_implementations`, `test_build_container_does_not_connect_anywhere`, `test_lifespan.py::test_lifespan_builds_starts_and_stops_container`, `test_deps_return_container_components`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Собрать `Container` при `APP_MODE=single` | `InMemoryEventBus`, `InProcessTaskScheduler`, `InMemoryRateLimiter`; модули `redis` и `arq` не импортируются |
| 2 | Собрать `Container` при `APP_MODE=scaled` и `REDIS_URL` | `RedisEventBus`, `ArqTaskScheduler`, `RedisRateLimiter`; сеть при сборке не используется |
| 3 | Запустить lifespan приложения | Компоненты стартуют при запуске и останавливаются при остановке |

---

## TC-38-002: Неизвестный режим и scaled без REDIS_URL — ошибка старта

**Priority:** Critical
**Type:** Negative
**AC:** AC-2 (неизвестное значение режима приводит к ошибке старта)
**E2E Automated:** No
**Автоматизация:** Авто — `test_container.py::test_unknown_mode_is_startup_error`, `test_scaled_without_redis_url_is_startup_error`, `test_lifespan.py::test_lifespan_unknown_mode_fails_startup`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Передать фабрике режим вне `single`/`scaled` | Исключение при старте, приложение не поднимается |
| 2 | `scaled` без `REDIS_URL` | Ошибка с названием переменной |

---

## TC-38-003: Границы импортов redis, arq, apscheduler

**Priority:** High
**Type:** Security / Architecture
**AC:** AC-2 (код за пределами пакета реализаций не импортирует `redis`, `arq`, `apscheduler`; NFR-7)
**E2E Automated:** No
**Автоматизация:** Авто — `test_import_boundaries.py` (3 теста: сканер видит код, распознаёт все формы импорта, запрещённые импорты только в `app/core/single` и `app/core/scaled`); правило ruff `TID251`; `test_container.py::test_lazy_import_in_clean_process`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Просканировать импорты в `backend/app` | `redis` и `arq` только в `app/core/scaled/`, `apscheduler` только в `app/core/single/` |
| 2 | Запустить `uv run ruff check .` | Нарушение границы даёт ошибку TID251 |
| 3 | В чистом процессе создать контейнер `single` | `redis` и `arq` не попадают в `sys.modules` |

---

## TC-38-004: Контракты интерфейсов и событий

**Priority:** High
**Type:** Functional / Negative
**AC:** AC-2 (интерфейсы одинаковы в обоих режимах)
**E2E Automated:** No
**Автоматизация:** Авто — `test_interfaces.py` (32 теста): `Event` — только JSON-сериализуемый payload, положительный `tenant_id`, aware-datetime, неизменяемость; `tenant_channel` включает `tenant_id` (мультиарендность); `rate_key` отвергает разделители и IPv6; реестр задач отвергает дубли и неверные интервалы.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Создать `Event` с `Decimal` или naive-датой в payload | Ошибка валидации |
| 2 | `tenant_channel` с нулевым tenant или неверным topic | Ошибка |
| 3 | Зарегистрировать две задачи с одним именем | `ValueError` |
| 4 | Создать экземпляр абстрактного класса | `TypeError` |

---

## Related TCs
- TC-39-001, TC-40-001 (реализации интерфейсов)
- TC-37-001 (Settings)
