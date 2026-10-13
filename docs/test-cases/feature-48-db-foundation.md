# Test Cases: Story #48 — БД: Alembic async, сессия SQLAlchemy, базовый класс моделей, фикстура db

**Feature:** #7 «Модель данных v1 и миграции Alembic» (story #48, AC-1)
**Spec:** docs/specs/feature-7-data-model.md (FR-1, FR-2, FR-3, NFR-4, NFR-5)
**Arch:** docs/arch/feature-7-data-model.md (ADR-7.1, 7.8, 7.9, 7.10, 7.11)
**Created:** 2026-10-12

Обозначения в поле «Автоматизация»: **Авто** — выполняется тестом (`backend/tests/...`; тесты с маркером `db` — в `backend/tests/db/`, требуют PostgreSQL); **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на 2026-10-12: локально (Windows, PostgreSQL 16 как служба, база `ai_waiter_test`) 1017 passed, 3 skipped (тесты настоящего Redis), все db-тесты PASS; CI по PR #57 — 5/5 зелёные.

---

## TC-48-001: Цикл Alembic upgrade / downgrade на пустой базе

**Priority:** Critical
**Type:** Functional
**AC:** AC-1 (Given `DATABASE_URL` на пустую базу PostgreSQL 16 / When `alembic upgrade head`, `alembic downgrade base` / Then команды завершаются без ошибок)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_alembic.py::test_upgrade_downgrade_upgrade`, `test_env_accepts_ready_connection`; `tests/test_alembic_setup.py::test_versions_chain_has_at_most_one_root_starting_at_0001`, `test_offline_upgrade_uses_explicit_url`, `test_offline_upgrade_falls_back_to_settings`; `tests/test_migrations_offline.py::test_chain_is_linear_and_ordered`. CLI-шаги — джоб `backend (postgres + redis)` в CI.
**Статус прогона:** PASS (локально и CI PR #57)

### Preconditions
- PostgreSQL 16 доступен, пустая база с именем, оканчивающимся на `_test`.
- `uv sync --extra scaled` выполнен в `backend/`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `uv run alembic upgrade head` | Код 0; в `alembic_version` текущая ревизия = head (`0004`) |
| 2 | `uv run alembic downgrade base` | Код 0; в схеме `public` нет таблиц, кроме служебной `alembic_version`; ревизия пуста |
| 3 | `uv run alembic upgrade head` | Код 0; схема создана заново |
| 4 | Проверить цепочку ревизий | Ровно один корень `0001`, одна head, цепочка линейна `0001 → 0002 → 0003 → 0004` |

### Expected Result
Миграции обратимы, цепочка линейна, Alembic работает в async-режиме через `postgresql+asyncpg`.

---

## TC-48-002: Фикстура db — пробный запрос и откат данных теста

**Priority:** Critical
**Type:** Functional
**AC:** AC-1 (`pytest -m db` с пробным тестом на фикстуре `db`: `SELECT 1` и вставка во временную таблицу; данные теста не остаются в базе)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_db_fixture.py::test_select_one`, `test_database_is_utf8`, `test_committed_data_is_rolled_back_after_test`, `test_rollback_inside_test_keeps_outer_transaction`, `test_database_ping_and_session_on_real_postgres`.
**Статус прогона:** PASS

### Preconditions
- `TEST_DATABASE_URL` указывает на базу `*_test`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `uv run pytest -q -m db tests/db/test_db_fixture.py` | Все тесты проходят |
| 2 | Тест выполняет `SELECT 1` через фикстуру | Результат `1` |
| 3 | Тест вставляет строку и делает `commit` (savepoint) | Внутри теста строка видна |
| 4 | После теста проверить базу отдельным подключением | Строки нет: внешняя транзакция откатана |
| 5 | Откат внутри теста | Внешняя транзакция остаётся рабочей |

### Expected Result
Каждый db-тест изолирован откатом; база после прогона не содержит тестовых данных; кодировка базы UTF8.

---

## TC-48-003: Отсутствие или ошибка DATABASE_URL — понятная ошибка без пароля

**Priority:** High
**Type:** Negative / Security
**AC:** AC-1 (отсутствие `DATABASE_URL` при старте даёт понятную ошибку, не показывающую пароль)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_config.py::test_database_url_is_required`, `test_database_url_must_be_asyncpg`, `test_database_url_is_secret_and_pool_defaults`, `test_config_error_does_not_leak_secret_values`, `test_pool_settings_are_validated`; `tests/test_db_session.py::test_ping_failure_returns_false_and_masks_password`, `test_describe_error_masks_url_encoded_password`, `test_describe_error_without_password_and_empty_message`; `tests/db/test_db_fixture.py::test_database_ping_fails_without_leaking_password`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запустить `python -m app` без `DATABASE_URL` | Код возврата 1, сообщение называет `DATABASE_URL`, трассировки нет |
| 2 | `DATABASE_URL=postgresql://...` (без `+asyncpg`) | Ошибка конфигурации с подсказкой о драйвере `postgresql+asyncpg` |
| 3 | `DATABASE_URL` с паролем `pw-s3cret`, неверный хост; вызвать `ping()` | `ping()` возвращает `false`, в логе причина без пароля (в т.ч. URL-кодированного) |
| 4 | Вывести `repr(Settings)` | `DATABASE_URL` скрыт (`SecretStr`) |
| 5 | `DB_POOL_SIZE=0` или отрицательный `DB_MAX_OVERFLOW` | Ошибка конфигурации |

### Expected Result
Приложение не стартует без корректного `DATABASE_URL`; ни в одном сообщении и логе нет пароля.

---

## TC-48-004: Guard тестовой базы — только TEST_DATABASE_URL и имя *_test

**Priority:** Critical
**Type:** Security / Negative
**AC:** AC-1 (Given `TEST_DATABASE_URL` на пустую тестовую базу, имя оканчивается на `_test`); FR-3; ADR-7.11
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_guards.py` (все 10 тестов, в т.ч. `test_database_url_is_never_used`, `test_missing_url_skips_locally`, `test_missing_url_fails_in_ci`, `test_non_test_database_exits`, `test_check_test_database_url`); `tests/test_config.py::test_test_database_url_is_not_a_setting`; `tests/test_repo_artifacts.py::test_ci_services_job_uses_dedicated_test_database`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Задан только `DATABASE_URL`, `TEST_DATABASE_URL` нет; `pytest -m db` локально | db-тесты пропускаются с сообщением «TEST_DATABASE_URL не задан»; `DATABASE_URL` не используется |
| 2 | То же при `CI=true` | Прогон падает («в CI тесты с PostgreSQL ...»), тесты не пропадают молча |
| 3 | `TEST_DATABASE_URL=.../ai_waiter` (без `_test`) | Сессия pytest прерывается, сообщение упоминает `_test`, пароль не выводится |
| 4 | `TEST_DATABASE_URL` без имени базы, с драйвером `postgresql://`, нечитаемая строка | Понятная ошибка для каждого случая |
| 5 | `TEST_DATABASE_URL` в корневом `.env` | Читается из `.env`, если не задан в окружении |
| 6 | Проверить `ci.yml`, джоб `backend-services` | БД сервис-контейнера `ai_waiter_test`, `TEST_DATABASE_URL` оканчивается на `/ai_waiter_test` |

### Expected Result
db-тесты (с откатом схемы до `base`) никогда не выполняются на рабочей или dev-базе.

---

## TC-48-005: Базовый класс моделей — соглашение об именах, Money, timestamptz, UUIDv7

**Priority:** High
**Type:** Functional
**AC:** AC-1 (основание модели); FR-2; NFR-2 spec (деньги `NUMERIC(10,2)`, время `timestamptz`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_base.py` (7 тестов: `test_base_metadata_uses_naming_convention`, `test_money_is_numeric_10_2_decimal`, `test_uuid_primary_key_defaults`, `test_tenant_mixin_constraints_and_names`, `test_timestamp_mixin_is_timestamptz_with_now_default` и др.); `tests/test_ids.py` (9 тестов UUIDv7); статика — правило `DTZ` в `ruff` (`backend/pyproject.toml`).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить `Base.metadata.naming_convention` | Шаблоны для `ix`, `uq`, `ck`, `fk`, `pk`; имена детерминированы |
| 2 | Проверить тип `Money` | `NUMERIC(10,2)`, в Python `Decimal` |
| 3 | `TenantMixin` | `tenant_id` NOT NULL, FK на `tenants.id`, индекс, `UNIQUE (tenant_id, id)` |
| 4 | `TimestampMixin` | `created_at`, `updated_at` — `timestamptz`, `server_default now()` |
| 5 | `new_id()` 1000 раз, в т.ч. в одной миллисекунде, при откате часов и из нескольких потоков | Версия 7, вариант RFC 4122, значения уникальны и строго возрастают |
| 6 | `uv run ruff check .` с `datetime.now()` без tz | Нарушение `DTZ` (naive-datetime запрещён) |

---

## TC-48-006: Async-сессия и движок — ленивое создание, пул, закрытие

**Priority:** Medium
**Type:** Functional
**AC:** AC-1; FR-2 (единая фабрика async-сессии)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py` (13 тестов: `test_engine_is_created_lazily_once_with_pool_settings`, `test_sessionmaker_does_not_expire_on_commit`, `test_stop_disposes_engine_and_allows_restart`, `test_session_yields_async_session_and_closes_it`, `test_ping_does_not_swallow_cancellation`, ...); `tests/test_container.py::test_build_container_creates_lazy_database_in_both_modes`, `test_database_stop_failure_is_logged`; `tests/test_lifespan.py::test_session_dep_opens_and_closes_session_without_commit`; `tests/test_qa_coverage_gaps.py::test_describe_error_falls_back_to_msg_when_template_context_is_missing`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Собрать `Container` в режимах `single` и `scaled` | `Container.database` создан, движок ещё не создан, подключения нет |
| 2 | Первое обращение к движку | Движок создаётся один раз с `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` |
| 3 | Запрос через `SessionDep` | Сессия открывается и закрывается без неявного `commit`; `expire_on_commit=False` |
| 4 | Остановка контейнера | `dispose()` движка; ошибка остановки логируется, остальные компоненты останавливаются |

---

## TC-48-007: Переносимость и отсутствие секретов в конфигурации Alembic

**Priority:** High
**Type:** Security
**AC:** AC-1; NFR-5 spec (только `DATABASE_URL`, без путей и IP); CLAUDE.md (публичный репозиторий)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_alembic_setup.py::test_ini_has_no_connection_string_and_no_timezone`, `test_alembic_ini_is_ascii`, `test_revision_template_renders_formatted_code`; `tests/test_config.py::test_env_example_lists_every_setting`; `tests/test_repo_artifacts.py::test_env_files_are_gitignored_except_example`, `test_no_ip_addresses_or_keys_in_infrastructure_files`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть `backend/alembic.ini` | Нет `sqlalchemy.url`, строки подключения, абсолютных путей; файл в ASCII (чтение на Windows без UTF-8 локали) |
| 2 | Сверить `.env.example` и `Settings` | `DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` перечислены, значений-секретов нет |
| 3 | Проверить `.gitignore` | `.env` игнорируется, `.env.example` — нет |

---

## TC-48-008: Локальный запуск на Windows с PostgreSQL как службой (без Docker)

**Priority:** Medium
**Type:** Functional (переносимость)
**AC:** AC-1; NFR-5 spec (тесты схемы на PostgreSQL 16 как службе Windows)
**E2E Automated:** No
**Автоматизация:** Ручной — по README, раздел «База данных».
**Статус прогона:** PASS (2026-10-12, Windows 11, PostgreSQL 16, база `ai_waiter_test`: `uv run pytest -q` — 1017 passed, 3 skipped)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Создать роль и базу `ai_waiter_test` по README | Команды выполняются в PowerShell |
| 2 | Задать `DATABASE_URL`, `TEST_DATABASE_URL` в корневом `.env` (значения не коммитятся) | — |
| 3 | `uv run pytest -q` в `backend/` | Все тесты проходят, пропущены только 3 теста настоящего Redis |

---

## Related TCs
- TC-37-004 (секреты в `Settings`), TC-38-001 (фабрика `Container`) — #48 добавил `DATABASE_URL` как обязательную настройку и `Container.database`
- TC-54-001, TC-54-002 (цикл миграций и `alembic check` в CI)
- TC-56-001 (`Database.ping()` используется в `/health/ready`)
