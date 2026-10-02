# Test Cases: Story #37 — Backend: каркас FastAPI, настройки из окружения, /health, .env.example

**Feature:** #6 «Каркас проекта» (story #37, AC-1)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги ниже выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-37-001: Запуск backend и ответ /health в режиме single

**Priority:** Critical
**Type:** Functional
**AC:** AC-1 (Given чистая копия и переменные из `.env.example` / When `ruff check`, `pytest`, запуск `python -m app`, `GET /health` / Then ruff и pytest без ошибок, `/health` = 200 с `status: ok` и `mode`)
**E2E Automated:** No
**Автоматизация:** Авто — `backend/tests/test_health.py::test_health_liveness`, `test_main.py::test_health_reports_scaled_mode`, `test_health_has_no_auth_and_no_internal_details`. Ручной смоук — выполнен.
**Статус прогона:** PASS (ручной смоук `python -m app` на 127.0.0.1: `{"status":"ok","mode":"single","version":"0.1.0"}`)

### Preconditions
- Python 3.12, зависимости установлены (`uv sync --extra scaled`), `.env` создан из `.env.example`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | В `backend/` выполнить `uv run ruff check .` и `uv run ruff format --check .` | Ошибок нет |
| 2 | Выполнить `uv run pytest -q` | Все тесты проходят (тесты с настоящим Redis пропущены без `REDIS_URL`) |
| 3 | Выполнить `uv run python -m app` | Процесс слушает `127.0.0.1:8000`, лог — одна JSON-строка на запись |
| 4 | `GET http://127.0.0.1:8000/health` | 200, тело `{"status":"ok","mode":"single","version":"..."}`, без авторизации и без внутренних деталей |

### Expected Result
Приложение стартует, `/health` отвечает 200 и сообщает режим.

---

## TC-37-002: Некорректный APP_MODE прерывает запуск

**Priority:** Critical
**Type:** Negative
**AC:** AC-1 (приложение не стартует с понятной ошибкой при недопустимом `APP_MODE`)
**E2E Automated:** No
**Автоматизация:** Авто — `test_config.py::test_app_mode_rejects_unknown_value`, `test_get_settings_unknown_mode_is_clear_error`, `test_main.py::test_main_exits_with_clear_error`. Ручной — выполнен.
**Статус прогона:** PASS (код возврата 1, `APP_MODE: недопустимое значение; допустимо: single, scaled`, без трассировки)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Задать `APP_MODE=bogus`, запустить `python -m app` | Процесс завершается с кодом 1 |
| 2 | Прочитать stderr | Сообщение называет переменную `APP_MODE` и допустимые значения; введённое значение и трассировка не выводятся |

---

## TC-37-003: Отсутствие обязательной переменной в режиме scaled

**Priority:** High
**Type:** Negative
**AC:** AC-1 (обязательная переменная не задана)
**E2E Automated:** No
**Автоматизация:** Авто — `test_config.py::test_scaled_requires_redis_url`, `test_get_settings_scaled_without_redis_is_clear_error`. Ручной — выполнен.
**Статус прогона:** PASS (`REDIS_URL обязателен при APP_MODE=scaled`)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `APP_MODE=scaled`, `REDIS_URL` не задан, запустить `python -m app` | Код возврата 1 |
| 2 | Прочитать stderr | Сообщение «REDIS_URL обязателен при APP_MODE=scaled» |

---

## TC-37-004: Безопасные значения по умолчанию и секреты

**Priority:** High
**Type:** Security
**AC:** NFR-2 (секреты только в окружении; `single` слушает `127.0.0.1`; в репозитории нет IP, ключей)
**E2E Automated:** No
**Автоматизация:** Авто — `test_config.py::test_defaults_single_mode_on_loopback`, `test_single_rejects_non_loopback_host`, `test_secrets_not_in_repr`, `test_config_error_does_not_leak_secret_values`, `test_database_url_must_be_asyncpg`, `test_prod_requires_public_base_url`, `test_public_base_url_rejects_ip_address`, `test_env_example_lists_every_setting`, `test_repo_artifacts.py::test_env_files_are_gitignored_except_example`, `test_no_ip_addresses_or_keys_in_infrastructure_files`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Создать `Settings` без переменных | `host=127.0.0.1`, `app_mode=single`, документация API включена |
| 2 | `APP_MODE=single`, `HOST=0.0.0.0` | Ошибка конфигурации (single только на loopback) |
| 3 | `APP_ENV=prod` | `/docs`, `/redoc`, `/openapi.json` отвечают 404; требуется `PUBLIC_BASE_URL` с доменом, не IP |
| 4 | Вывести `repr(Settings)` и текст ошибки с секретами | Значения секретов маскируются, в ошибке их нет |
| 5 | Сверить `.env.example` с полями `Settings` | Каждая переменная перечислена, значений-секретов нет; `.env` в `.gitignore` |

---

## TC-37-005: Готовность /health/ready и устойчивость к недоступному Redis

**Priority:** Medium
**Type:** Functional / Negative
**AC:** AC-1 (расширение: проверка готовности без утечки деталей)
**E2E Automated:** No
**Автоматизация:** Авто — `test_health.py::test_ready_in_single_mode_skips_redis`, `test_ready_returns_503_without_details_when_check_fails`, `test_ready_check_times_out`, `test_redis_down_at_startup_keeps_liveness`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | single: `GET /health/ready` | 200, `checks.redis = skipped` |
| 2 | scaled, Redis отвечает: `GET /health/ready` | 200, `ready` |
| 3 | scaled, ping падает, возвращает false или превышает 2 с | 503 без текста исключения; `/health` остаётся 200 |

---

## TC-37-006: Структурированные логи и ленивое создание приложения

**Priority:** Medium
**Type:** Functional
**AC:** NFR-4 (JSON-логи), AC-1 (импорт `app.main` не читает окружение)
**E2E Automated:** No
**Автоматизация:** Авто — `test_log.py` (8 тестов), `test_main.py::test_import_does_not_read_environment`, `test_lazy_app_attribute_built_from_env`, `test_docs_disabled_in_prod`; `test_qa_coverage_gaps.py`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `LOG_FORMAT=json`, записать лог с `extra` и исключением | Одна строка JSON: `ts` (UTC), `level`, `logger`, `msg`, поля `extra`, `exc` |
| 2 | Логировать `SecretStr` | Выводится `**********` |
| 3 | Импортировать `app.main` при `APP_MODE=bogus` | Импорт проходит, объект `app` не создан до первого обращения |

---

## Related TCs
- TC-38-001 (фабрика зависимостей использует `Settings`)
- TC-42-001 (SPA использует `FRONTEND_DIST_DIR`)
