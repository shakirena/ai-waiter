# Test Cases: Story #56 — Проверка доступности БД в /health/ready

**Feature:** #7 «Модель данных v1 и миграции Alembic» (story #56)
**Spec:** docs/specs/feature-7-data-model.md (открытый вопрос 19)
**Arch:** docs/arch/feature-7-data-model.md (ADR-7.9, API Contracts)
**Created:** 2026-10-13

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-12: локально (Windows, PostgreSQL 16, `ai_waiter_test`) 1017 passed, 3 skipped, все db-тесты PASS; CI PR #57 — 5/5.

AC story: **Given** приложение запущено и PostgreSQL доступен / **When** `GET /health/ready` / **Then** 200 с проверкой БД `ok`; если БД недоступна (таймаут не больше 2 с) — 503 с `fail`, без раскрытия строки подключения и текста ошибки драйвера.

Ключ проверки в ответе — `checks.database` (в тексте AC — `db`); формат утверждён в ADR-7.9 и описан в README.

---

## TC-56-001: БД доступна — 200 и database: ok

**Priority:** Critical
**Type:** Functional
**AC:** AC (PostgreSQL доступен → 200, проверка БД `ok`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_health_db.py::test_ready_with_available_database` (настоящий PostgreSQL); `tests/test_health.py::test_ready_runs_checks_concurrently`, `test_ready_in_single_mode_skips_redis`, `test_ready_is_listed_in_openapi_with_503`.
**Статус прогона:** PASS

### Preconditions
- `DATABASE_URL` указывает на доступную базу, режим `single`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET /health/ready` | 200, `{"status":"ready","checks":{"database":"ok","redis":"skipped"}}` |
| 2 | Режим `scaled`, Redis и БД доступны | 200, `database: ok`, `redis: ok`; проверки идут параллельно (общее время ≈ одной задержке) |
| 3 | Открыть `/openapi.json` (dev) | `/health/ready` описан с ответом 503 |

---

## TC-56-002: БД недоступна — 503 и database: fail без деталей

**Priority:** Critical
**Type:** Negative / Security
**AC:** AC (БД недоступна → 503 с `fail`, без строки подключения и текста ошибки драйвера)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_health_db.py::test_ready_with_wrong_credentials_is_503_without_details`; `tests/test_health.py::test_ready_checks_database_in_both_modes[single|scaled]`, `test_ready_database_error_has_no_details_in_body`, `test_ready_with_real_database_object_masks_password_in_log`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `DATABASE_URL` с неверным паролем и несуществующей базой; `GET /health/ready` | 503, `{"status":"not_ready","checks":{"database":"fail","redis":"skipped"}}` |
| 2 | Проверить тело ответа | Нет пароля, хоста, имени драйвера `asyncpg`, текста исключения |
| 3 | Проверить лог процесса | Есть запись с `component = database` и типом ошибки (`ConnectionRefusedError`), пароля нет, трассировки нет |
| 4 | То же в режиме `scaled` | 503, `database: fail`, `redis` по своей проверке |

---

## TC-56-003: Таймаут проверки БД не больше 2 с

**Priority:** High
**Type:** Negative
**AC:** AC (таймаут не больше 2 с)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_ready_database_timeout_is_fail`, `test_readiness_timeout_is_two_seconds`; `tests/test_db_session.py::test_ping_does_not_swallow_cancellation`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить константу таймаута готовности | 2 с |
| 2 | `ping()` БД зависает дольше таймаута | Ответ 503, `database: fail`, ожидание прерывается по таймауту |
| 3 | Отмена запроса во время `ping()` | Отмена не проглатывается |

---

## TC-56-004: /health (liveness) не обращается к БД

**Priority:** High
**Type:** Functional
**AC:** Technical Notes story (`/health` остаётся без обращения к БД)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_liveness_does_not_touch_database`, `test_health_liveness`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | БД недоступна (любой вызов `ping()` — ошибка); `GET /health` | 200, `status: ok`; к БД нет обращений |

---

## Related TCs
- TC-37-005 (`/health/ready` и Redis — расширено проверкой БД)
- TC-48-003, TC-48-006 (`Database.ping()`, маскировка пароля)
