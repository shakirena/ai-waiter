# Test Cases: Story #71 — Неготовность приложения в prod при демо-заведении в базе

**Feature:** «Защита от демо-данных в боевой базе» (story #71, AC-2; выделена из #60)
**Spec:** docs/specs/feature-60-demo-data-guard.md (AC-2, FR-3, FR-4, NFR-1…NFR-6, E-3, E-4, E-7…E-10)
**Arch:** docs/arch/feature-60-demo-data-guard.md (ADR-60.2, ADR-60.3, раздел «Реализация #71»)
**Created:** 2026-10-29

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-29: локально (Windows, PostgreSQL 16, тестовая база `*_test`) `uv run pytest -q tests/test_demo_data.py tests/test_health.py tests/test_lifespan.py tests/db/test_health_db.py` — 67 passed, без пропусков (db-тесты выполнены).

AC-2 (= AC issue #71): **Given** приложение запущено с `APP_ENV=prod`, а в его базе есть заведение `DEMO_TENANT_ID` / **When** запрашивается `/health/ready` / **Then** ответ — 503 `not_ready` без строки подключения и внутренних деталей в теле, а в лог пишется предупреждение о демо-заведении без строки подключения.

Объём: AC-2 и граничные случаи E-3, E-4 (часть приложения), E-7…E-10. AC-1 и E-1, E-2, E-5, E-6 (сид) — в `feature-60-demo-seed-guard.md`.

Решения, от которых зависят ожидаемые результаты:
- ADR-60.2: `DemoDataMonitor` (`app.state.demo_data_monitor`) вызывается один раз в lifespan после старта контейнера и на каждом `GET /health/ready` при `APP_ENV=prod`, без кэша. Состояния `FOUND` / `ABSENT` / `UNKNOWN`; не `ABSENT` → 503. Лог только при смене состояния: → `FOUND` — WARNING `DEMO_FOUND_WARNING`; → `UNKNOWN` — WARNING `DEMO_CHECK_FAILED` (текст ошибки через `Database.describe_error`); `FOUND` → `ABSENT` — INFO `DEMO_GONE_INFO`; `extra component="demo_data"`, без `exc_info`.
- ADR-60.3: тело и OpenAPI `/health/ready` прежние — `{"status": …, "checks": {"database": …, "redis": …}}`; ключа `demo_data` нет.

Общее предусловие: применены все миграции (`alembic upgrade head`); «демо-заведение» — строка `tenants` с `id = DEMO_TENANT_ID` (`app.seed.data`), «боевое заведение» — строка с другим `id`. Если не указано иное — режим `single` (`redis: "skipped"`).

---

## TC-71-001: prod и демо-заведение в базе — 503 not_ready и WARNING без строки подключения

**Priority:** Critical
**Type:** Security / Functional
**AC:** AC-2; FR-3; NFR-1, NFR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_health_db.py::test_prod_with_demo_tenant_is_503_and_warns` (полный сид зафиксирован, настоящий PostgreSQL); без БД — `tests/test_health.py::test_prod_demo_found_is_503_with_unchanged_body[single|scaled]`, `tests/test_demo_data.py::test_found_logs_one_warning_and_repeat_is_silent`.
**Статус прогона:** PASS

### Preconditions
- В базе загружен сид (`python -m app.seed` с `APP_ENV=dev`), транзакция зафиксирована.
- Приложение запускается с `APP_ENV=prod`, `DATABASE_URL` — на эту базу.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запустить приложение (lifespan) | Старт успешен; в логе одна запись WARNING `DEMO_FOUND_WARNING` (`component="demo_data"`) |
| 2 | `GET /health/ready` | 503; тело ровно `{"status": "not_ready", "checks": {"database": "ok", "redis": "skipped"}}` |
| 3 | Проверить тело | Нет строки подключения, хоста, текстов исключений, идентификатора заведения и слова `demo` |
| 4 | Проверить все записи лога | Ровно одна запись `app.api.demo_data` — WARNING `DEMO_FOUND_WARNING`; ни в одной записи нет `postgresql` и пароля |
| 5 | Повторить шаг 2 в режиме `scaled` | 503; тело `{"status": "not_ready", "checks": {"database": "ok", "redis": "ok"}}` |

---

## TC-71-002: Тело и OpenAPI /health/ready не раскрывают наличие демо (ADR-60.3)

**Priority:** Critical
**Type:** Security
**AC:** AC-2 («без внутренних деталей в теле»); ADR-60.3; FR-3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_prod_openapi_has_no_demo_key`, `::test_prod_demo_found_is_503_with_unchanged_body[single|scaled]` (`demo` нет в тексте ответа), `::test_prod_demo_check_failed_is_503[single|scaled]` (текст ошибки `tenants` в тело не попадает), `::test_ready_is_listed_in_openapi_with_503`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `APP_ENV=prod`, `DOCS_ENABLED=true`, `GET /openapi.json` | Схема `ReadinessResponse`: свойства только `status`, `checks`; ключи `checks` — только `database`, `redis`; слова `demo` в документе нет |
| 2 | prod, демо найдено — `GET /health/ready` | Тело совпадает с телом при обычной неготовности: `not_ready` и `checks` без дополнительных ключей |
| 3 | prod, проверка демо упала с ошибкой `relation tenants does not exist` | 503, тело без текста ошибки (`tenants` не встречается) |

### Notes
Security review #71 (INFO): 503 при всех `ok` косвенно сигнализирует «что-то не так» — это следствие AC-2; причину оператор видит только в логе.

---

## TC-71-003: Записи лога без строки подключения, пароля и traceback

**Priority:** High
**Type:** Security
**AC:** AC-2 («предупреждение … без строки подключения»); NFR-1, NFR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_demo_data.py::test_log_texts_have_no_connection_details`, `::test_exception_is_unknown_with_masked_password`, `::test_session_error_is_unknown`, `::test_found_logs_one_warning_and_repeat_is_silent` (`exc_info is None`); `tests/test_health.py::test_check_database_exception_logged_masked_without_traceback`, `::test_ready_returns_503_without_details_when_check_fails[event_bus|rate_limiter]` (Redis — только имена классов, `exc_info is None`), `::test_ready_with_real_database_object_masks_password_in_log`; с БД — `tests/db/test_health_db.py::test_prod_with_demo_tenant_is_503_and_warns`, `::test_prod_without_schema_is_503_with_database_ok`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить константы `DEMO_FOUND_WARNING`, `DEMO_CHECK_FAILED`, `DEMO_GONE_INFO` | Нет `postgresql` и `@`; в `DEMO_FOUND_WARNING` упомянуты `APP_ENV=prod` и `DATABASE_URL` (как имена переменных) |
| 2 | Проверка демо падает с исключением, в тексте которого DSN с паролем (настоящий `Database`) | Состояние `UNKNOWN`; одна запись WARNING `DEMO_CHECK_FAILED…`; в ней имя класса и `***`, пароля нет; `exc_info is None`; `component="demo_data"` |
| 3 | `ping` БД падает с DSN в тексте | Запись `app.api.health` c `component="database"`: текст через `describe_error`, пароль замаскирован, `exc_info is None` |
| 4 | `ping` шины или rate-limiter-а падает с секретом в тексте | В записи только имя класса (`ConnectionError`), без сообщения и адреса; `exc_info is None` |

### Notes
Известное ограничение NFR-1 (с #7, задача #73): `describe_error` маскирует только пароль; хост и порт из текста драйвера в WARNING `DEMO_CHECK_FAILED` возможны. Собственные тексты #71 деталей подключения не содержат.

---

## TC-71-004: APP_ENV=dev и test — проверка не выполняется, поведение прежнее (E-7)

**Priority:** High
**Type:** Functional / Negative (регрессия)
**AC:** E-7; FR-4
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_demo_check_not_called_outside_prod[single|scaled × dev|test]`, `tests/test_lifespan.py::test_lifespan_outside_prod_does_not_refresh[dev|test]`.
**Статус прогона:** PASS

### Preconditions
- Проверка демо подменена так, что вернула бы «демо найдено».

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запустить приложение с `APP_ENV=dev` (затем `test`) | Lifespan не вызывает `refresh`; состояние монитора `None`; записей о демо нет |
| 2 | `GET /health/ready` в `single` и `scaled` | 200 `ready`; проверка демо не вызывалась ни разу |

---

## TC-71-005: prod без демо-заведения — готовность по прежним проверкам (E-4, E-8)

**Priority:** High
**Type:** Functional (регрессия)
**AC:** E-4 (часть приложения), E-8; FR-3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_health_db.py::test_prod_without_demo_tenant_is_ready` (в базе только боевое заведение), `tests/test_health.py::test_prod_without_demo_is_ready[single|scaled]`, `tests/test_demo_data.py::test_first_absent_is_silent`.
**Статус прогона:** PASS

### Preconditions
- В `tenants` одно боевое заведение, демо-заведения нет; `APP_ENV=prod`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запустить приложение, `GET /health/ready` | 200, `{"status": "ready", "checks": {"database": "ok", "redis": "skipped"}}` |
| 2 | То же в `scaled` с доступным Redis | 200, `redis: "ok"` |
| 3 | Проверить лог | Записей `app.api.demo_data` нет (первое `ABSENT` после старта не пишется) |
| 4 | Число вызовов проверки | 2: одна в lifespan и одна на запрос |

---

## TC-71-006: prod, база недоступна — 503 из-за database, «демо нет» не делает готовым (E-9)

**Priority:** Critical
**Type:** Negative
**AC:** E-9; NFR-5
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_prod_database_down_is_503_regardless_of_demo`, `tests/test_lifespan.py::test_lifespan_in_prod_survives_failed_check`, `tests/db/test_health_db.py::test_prod_with_unreachable_database_is_503_and_demo_warning_is_masked` (настоящий драйвер: 503, `database: fail`, один WARNING `DEMO_CHECK_FAILED` без пароля и `exc_info`); регрессия #56 — `tests/db/test_health_db.py::test_ready_with_wrong_credentials_is_503_without_details`, `tests/test_health.py::test_ready_database_error_has_no_details_in_body`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `APP_ENV=prod`; `ping` БД возвращает неуспех, проверка демо — «демо нет» | 503, `{"status": "not_ready", "checks": {"database": "fail", "redis": "skipped"}}` |
| 2 | Проверить тело | Нет текста ошибки, хоста, пароля |

---

## TC-71-007: Ошибка или таймаут проверки демо — «неизвестно», 503 при database: ok (NFR-5)

**Priority:** Critical
**Type:** Negative / Security
**AC:** NFR-5; ADR-60.2 (`UNKNOWN` → 503); E-9
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_prod_demo_check_failed_is_503[single|scaled]`, `::test_prod_demo_check_timeout_is_503`; `tests/test_demo_data.py::test_exception_is_unknown_with_masked_password`, `::test_session_error_is_unknown`, `::test_timeout_is_unknown`, `::test_driver_timeout_error_uses_describe_error`, `::test_cancelled_error_propagates`, `::test_session_is_closed_after_check`; с БД — `tests/db/test_health_db.py::test_prod_without_schema_is_503_with_database_ok`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | prod; запрос проверки демо падает с исключением | 503, тело `{"status": "not_ready", "checks": {"database": "ok", "redis": …}}` |
| 2 | prod; проверка демо не укладывается в таймаут (`READINESS_CHECK_TIMEOUT`, 2 с) | 503 с тем же телом; в WARNING — «превышен таймаут проверки (N с)» |
| 3 | Ошибка при открытии сессии (не в запросе) | `UNKNOWN`, наружу не выходит, WARNING с `OSError: …` |
| 4 | `TimeoutError` от драйвера при неистёкшем собственном таймауте | `UNKNOWN`; текст — через `describe_error` (`TimeoutError: …`), не «превышен таймаут» |
| 5 | Запрос отменён (`CancelledError`) | Исключение пробрасывается, состояние не меняется |
| 6 | После любой проверки | Сессия закрыта |
| 7 | Настоящий PostgreSQL без таблицы `tenants` (миграции не применены), prod | `database: "ok"`, но 503; одна запись WARNING без `exc_info` и пароля |

---

## TC-71-008: Демо удалено между опросами — следующий опрос 200 и INFO

**Priority:** High
**Type:** Functional
**AC:** ADR-60.2 (проверка на каждом запросе, без кэша); FR-3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_health_db.py::test_prod_demo_removed_between_polls_becomes_ready`, `tests/test_demo_data.py::test_found_then_absent_logs_info`.
**Статус прогона:** PASS

### Preconditions
- В базе есть демо-заведение (зафиксировано); приложение запущено с `APP_ENV=prod`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET /health/ready` | 503 |
| 2 | Удалить демо-заведение и зафиксировать, без перезапуска приложения | — |
| 3 | `GET /health/ready` дважды | Оба 200 `ready`, `database: "ok"` |
| 4 | Проверить лог | Ровно две записи: WARNING `DEMO_FOUND_WARNING`, затем INFO `DEMO_GONE_INFO` |

---

## TC-71-009: Лог только при смене состояния — без спама при частых опросах

**Priority:** Medium
**Type:** Functional (NFR-6)
**AC:** ADR-60.2 п. 4; NFR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_prod_demo_warning_logged_once_for_repeated_polls`; `tests/test_demo_data.py::test_initial_state_is_none`, `::test_found_logs_one_warning_and_repeat_is_silent`, `::test_first_absent_is_silent`, `::test_unknown_then_absent_is_silent`, `::test_found_after_unknown_logs_warning`, `::test_found_then_absent_logs_info`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | prod, демо в базе; старт и 3 опроса `/health/ready` | Все 503; проверка вызвана 4 раза; в логе одна запись WARNING `DEMO_FOUND_WARNING` |
| 2 | Последовательность `ABSENT, ABSENT` с начального состояния | Записей нет |
| 3 | `UNKNOWN, UNKNOWN, ABSENT` | Одна запись WARNING (о сбое); о восстановлении — ничего |
| 4 | `UNKNOWN, FOUND` | Последняя запись — WARNING `DEMO_FOUND_WARNING` |
| 5 | `FOUND, ABSENT, ABSENT` | WARNING, затем одна INFO `DEMO_GONE_INFO` |

---

## TC-71-010: Проверка при старте в prod — один раз, сбой не прерывает старт

**Priority:** High
**Type:** Functional / Negative
**AC:** ADR-60.2 (проверка в lifespan для службы Windows); FR-3; E-9
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_lifespan.py::test_lifespan_in_prod_refreshes_once_with_container_database`, `::test_lifespan_in_prod_survives_failed_check`, `::test_create_app_creates_demo_data_monitor`, `::test_get_demo_data_monitor_returns_state_object`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `create_app` | `app.state.demo_data_monitor` — `DemoDataMonitor`, состояние `None`, таймаут = `READINESS_CHECK_TIMEOUT`; зависимость `get_demo_data_monitor` возвращает этот объект |
| 2 | Старт в prod, демо найдено | `refresh` вызван один раз с `container.database`; состояние `FOUND` до первого запроса (WARNING уже в логе) |
| 3 | Старт в prod, БД недоступна | Старт не прерывается; состояние `UNKNOWN`; одна запись WARNING; `GET /health` (liveness) — 200 |

---

## TC-71-011: Проверка демо идёт параллельно с ping-ами, в пределах таймаута 2 с

**Priority:** Medium
**Type:** Functional (NFR-4)
**AC:** NFR-4; ADR-60.2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_prod_demo_check_runs_concurrently_with_pings`, `::test_prod_demo_check_timeout_is_503`, `::test_ready_runs_checks_concurrently`; запрос `EXISTS` по PK — `tests/test_seed_guard.py::test_demo_tenant_exists_query` (#60).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | prod, `scaled`; проверка демо, `ping` БД, шины и rate-limiter-а — по 0,3 с | Ответ 200 быстрее 0,55 с: проверки в одном `gather`, а не последовательно |
| 2 | Проверка демо дольше таймаута | Ответ не дольше таймаута; 503 (TC-71-007) |
| 3 | SQL проверки | Один `SELECT EXISTS (… FROM tenants WHERE id = DEMO_TENANT_ID)` |

---

## TC-71-012: prod, в базе демо и боевое заведение — 503 и предупреждение (E-3)

**Priority:** High
**Type:** Security / Negative
**AC:** E-3 (часть приложения); AC-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_health_db.py::test_prod_with_demo_and_real_tenant_is_503_and_warns` (настоящая база с демо и боевым заведением → 503, одна запись WARNING); дополнительно `tests/db/test_seed.py::test_guard_on_demo_and_other_base`, `tests/test_health.py::test_prod_demo_found_is_503_with_unchanged_body[single|scaled]`.
**Статус прогона:** PASS

### Preconditions
- Сид загружен; добавлено и зафиксировано боевое заведение; `APP_ENV=prod`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET /health/ready` | 503 `not_ready`, `database: "ok"`, тело без деталей |
| 2 | Проверить лог | WARNING `DEMO_FOUND_WARNING` без строки подключения |

---

## TC-71-013: Одинаковое поведение в режимах single и scaled, на Windows и Linux (E-10)

**Priority:** Medium
**Type:** Functional (переносимость)
**AC:** E-10; NFR-2, NFR-3, NFR-6
**E2E Automated:** No
**Автоматизация:** Авто — параметризация `[single|scaled]`: `tests/test_health.py::test_prod_demo_found_is_503_with_unchanged_body`, `::test_prod_demo_check_failed_is_503`, `::test_prod_without_demo_is_ready`, `::test_demo_check_not_called_outside_prod`; `scaled` — `::test_prod_demo_check_runs_concurrently_with_pings`. Unit-тесты — в матрице CI на Windows и Linux; db-тесты (`tests/db/test_health_db.py`) — в Linux-джобе `backend-services`. `app/api/demo_data.py` использует только `Database` и `app.seed.guard`, без Redis, `EventBus`, `TaskScheduler`, `RateLimiter` (проверено чтением кода; общий тест границ импортов — TC-38-003). Новых переменных окружения и флага отключения нет.
**Статус прогона:** PASS (локально Windows: unit и db; Linux — по результату CI PR #72)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Прогнать тесты #71 с `APP_MODE=single` и `scaled` | Одинаковые статусы; отличается только `redis` (`skipped` / `ok`) |
| 2 | Прогнать unit-тесты на Windows и Linux | PASS на обеих ОС |
| 3 | Проверить импорты `app/api/demo_data.py` | Только стандартная библиотека, `app.db.session`, `app.seed.guard` |

---

## TC-71-014: Ручной — запуск в prod на Windows (single) с демо в базе: лог и /health/ready

**Priority:** High
**Type:** Security / Functional
**AC:** AC-2; ADR-60.2 (WARNING при старте службы без опросов); E-8, E-10
**E2E Automated:** No
**Автоматизация:** Ручной. Сценарий автоматически покрыт через ASGI-клиент (TC-71-001, TC-71-008); ручной прогон проверяет настоящий процесс `python -m app` и JSON-лог в консоли.
**Статус прогона:** НЕ ВЫПОЛНЕН

### Preconditions
- Тестовая база (`*_test`) или база разработки с применёнными миграциями; боевые базы не использовать.
- Сид загружен с `APP_ENV=dev`: `python -m app.seed --database-url <url>`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | В PowerShell из `backend/`: `$env:APP_ENV='prod'; $env:APP_MODE='single'; $env:DATABASE_URL='<url>'`; `uv run python -m app` | Процесс стартует; в логе (JSON) запись WARNING `component="demo_data"` с текстом `DEMO_FOUND_WARNING`; строки подключения и пароля нет |
| 2 | `curl.exe -s -i http://127.0.0.1:8000/health` | 200 |
| 3 | `curl.exe -s -i http://127.0.0.1:8000/health/ready` | 503; тело `{"status":"not_ready","checks":{"database":"ok","redis":"skipped"}}` |
| 4 | Повторить шаг 3 несколько раз | Новых записей о демо в логе нет |
| 5 | Удалить демо-данные (новая пустая база или сброс схемы и `alembic upgrade head`), не перезапуская процесс — либо перезапустить на базе без демо | `/health/ready` — 200 `ready`; при удалении без перезапуска — одна запись INFO `DEMO_GONE_INFO` |
| 6 | Остановить процесс (Ctrl+C), вернуть `APP_ENV` | — |

---

## Related TCs
- TC-60-008 (Notes: гонка сида не закрыта блокировкой, последствие обнаруживает #71 — TC-71-001, TC-71-012)
- TC-60-002 (E-3 для сида) ↔ TC-71-012 (E-3 для приложения)
- TC-60-001 (E-4 для сида) ↔ TC-71-005 (E-4 для приложения)
- TC-56-001…TC-56-003 (проверка `database` в `/health/ready`, таймаут 2 с, тело без деталей — регрессия в TC-71-006, TC-71-011)
- TC-37-005 (`/health/ready` и Redis; запись ошибки Redis теперь без traceback — TC-71-003)
- TC-38-003 (границы импортов Redis/arq/apscheduler — TC-71-013)
- TC-53-003 (сид отказывает в prod; демо в боевой базе возможно только при ошибке оператора — TC-71-001)
