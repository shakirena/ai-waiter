# Test Cases: Story #60 — Защита от загрузки демо-данных в боевую базу

**Feature:** «Защита от демо-данных в боевой базе» (story #60, AC-1; story #71 — отдельно, вне этого документа)
**Spec:** docs/specs/feature-60-demo-data-guard.md (FR-1, FR-2, NFR-1…NFR-6, E-1…E-6, E-10)
**Arch:** docs/arch/feature-60-demo-data-guard.md (ADR-60.1, раздел «Реализация #60»)
**Created:** 2026-10-28

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-10-28: локально (Windows, PostgreSQL 16, тестовая база `*_test`) `pytest -q tests/test_seed_guard.py tests/test_seed.py tests/db/test_seed.py` — 56 passed, без пропусков (db-тесты выполнены).

Объём: AC-1 и граничные случаи E-1…E-6, E-10. AC-2 и E-7…E-9 относятся к #71 (неготовность приложения в prod) и здесь не покрываются.

Общее предусловие: применены все миграции (`alembic upgrade head`); `APP_ENV=dev` (если не указано иное). «Другое заведение» — строка в `tenants` с `id`, отличным от `DEMO_TENANT_ID` (`app.seed.data`).

---

## TC-60-001: В базе только другое заведение — отказ с кодом 2, демо не создаётся

**Priority:** Critical
**Type:** Security / Negative
**AC:** AC-1 (Given в базе есть заведение, кроме демо; When `python -m app.seed` с `APP_ENV` ≠ `prod`; Then код 2, сообщение на русском в stderr без строки подключения, ничего не записано); E-4; FR-1
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_seed.py::test_cli_refuses_base_with_other_tenant`, `tests/db/test_seed.py::test_guard_on_other_only_base`; без БД — `tests/test_seed.py::test_foreign_tenants_are_refused_with_exit_code_2`, `tests/test_seed_guard.py::test_ensure_seed_target_raises_when_foreign_tenants_exist`.
**Статус прогона:** PASS

### Preconditions
- Пустая база с применёнными миграциями; в `tenants` добавлено и зафиксировано одно заведение «Другое заведение».

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Посчитать строки всех таблиц | `tenants` = 1, остальные 0 |
| 2 | `python -m app.seed --database-url <url тестовой базы>` | Код 2 (`EXIT_FORBIDDEN`) |
| 3 | Проверить stdout и stderr | stdout пуст; в stderr — `FOREIGN_TENANTS_REFUSAL` на русском; пароля нет |
| 4 | Посчитать строки всех таблиц | Совпадает с шагом 1 |
| 5 | Проверить `tenants` на `DEMO_TENANT_ID` | Демо-заведения нет |

---

## TC-60-002: Демо и другое заведение — отказ с кодом 2, демо-строки не обновляются

**Priority:** Critical
**Type:** Security / Negative
**AC:** AC-1; E-3; FR-1 («ничего не записывает: транзакция откатывается»)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_seed.py::test_cli_refuses_demo_plus_other_without_updating_demo`, `tests/db/test_seed.py::test_guard_on_demo_and_other_base`.
**Статус прогона:** PASS

### Preconditions
- Сид загружен (код 0); затем добавлено и зафиксировано «Другое заведение».

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запомнить число строк всех таблиц и `updated_at` всех строк таблиц со столбцом `updated_at` | Есть демо-строки |
| 2 | Запустить сид повторно | Код 2, stdout пуст, в stderr `FOREIGN_TENANTS_REFUSAL` без пароля |
| 3 | Сравнить число строк и `updated_at` с шагом 1 | Без изменений: демо-строки не обновлены (upsert не выполнялся) |

---

## TC-60-003: Пустая база — сид загружает данные, код 0

**Priority:** High
**Type:** Functional (регрессия FR-2)
**AC:** E-1; FR-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_seed.py::test_guard_on_empty_base`, `tests/db/test_seed.py::test_cli_twice_commits_same_data` (первый запуск на пустой базе); без БД — `tests/test_seed_guard.py::test_ensure_seed_target_passes_for_empty_or_demo_only_base`, `tests/test_seed_guard.py::test_none_result_is_false`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | На пустой базе вызвать проверку `ensure_seed_target` | Исключения нет; `foreign_tenants_exist` = False, `demo_tenant_exists` = False |
| 2 | `python -m app.seed --database-url <url>` | Код 0; число строк = `EXPECTED_COUNTS`; напечатаны ссылки `/t/{token}` |

---

## TC-60-004: В базе только демо-заведение — повторный запуск идемпотентен

**Priority:** High
**Type:** Functional (регрессия FR-2)
**AC:** E-2; FR-2; связь с TC-53-002
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_seed.py::test_guard_on_demo_only_base`, `tests/db/test_seed.py::test_cli_twice_commits_same_data`, `tests/db/test_seed.py::test_seed_twice_gives_same_row_counts`, `tests/db/test_seed.py::test_seed_restores_reference_values`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Загрузить сид, вызвать `ensure_seed_target` | Исключения нет: демо-заведение — не «другое» |
| 2 | Запустить CLI второй раз | Код 0; число строк в каждой таблице то же; ссылки `/t/{token}` напечатаны |
| 3 | Изменить демо-данные и запустить сид | Эталонные значения восстановлены (как в TC-53-002) |

---

## TC-60-005: APP_ENV=prod — прежний отказ до подключения, проверка базы не выполняется

**Priority:** Critical
**Type:** Security / Negative (регрессия)
**AC:** E-5; FR-2; связь с TC-53-003
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_seed.py::test_prod_refusal_happens_before_target_check`, `tests/test_seed.py::test_exit_prod_forbidden_is_alias_of_exit_forbidden`; прежние тесты TC-53-003 (`test_prod_is_refused_with_exit_code_2`, `test_prod_refusal_does_not_need_other_settings`, `test_module_entry_point_refuses_prod_in_subprocess`).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `APP_ENV=prod`, `python -m app.seed --database-url <любой адрес>` | Код 2, в stderr текст про `APP_ENV=prod` |
| 2 | Проверить, вызывалась ли `ensure_seed_target` | Не вызывалась: к базе сид не подключается |
| 3 | Сравнить коды выхода | `EXIT_PROD_FORBIDDEN == EXIT_FORBIDDEN == 2` — оба отказа означают «запрещено политикой» |

---

## TC-60-006: Ошибка БД при проверке — код 1, пароль не выводится

**Priority:** High
**Type:** Negative / Security
**AC:** E-6; FR-1 (код 1 — ошибка конфигурации или БД); NFR-1
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_seed.py::test_database_error_in_target_check_is_exit_1_without_password`, `tests/test_seed_guard.py::test_database_error_is_not_caught`; с БД — `tests/db/test_seed.py::test_cli_without_schema_fails_with_hint` (нет таблицы `tenants`: код 1, а не отказ 2), `tests/db/test_seed.py::test_cli_wrong_password_is_not_shown`. Ручная проверка недоступной базы — TC-60-010, шаг 7.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запрос проверки падает с ошибкой, в тексте которой есть пароль | Код 1; в stderr «Не удалось загрузить демо-данные», пароль заменён на `***`; подсказка `alembic upgrade head`; текста `FOREIGN_TENANTS_REFUSAL` нет; загрузчик не вызван |
| 2 | Сид на схеме без миграций | Код 1, подсказка `alembic upgrade head` |
| 3 | Сид с неверным паролем в `--database-url` | Код 1, пароль не выводится ни в stdout, ни в stderr |
| 4 | `ensure_seed_target` при ошибке сессии | Ошибка не перехватывается внутри проверки (её обрабатывает CLI) |

### Notes
Известное ограничение NFR-1 (security review #60, LOW, существует с #7): `Database.describe_error` маскирует только пароль, поэтому хост и порт из текста ошибки драйвера в сообщении с кодом 1 возможны. Это не дефект #60: собственный текст отказа фичи деталей подключения не содержит (TC-60-007), а доработка `describe_error` — отдельная задача (arch, раздел Security).

---

## TC-60-007: Сообщение отказа — на русском, без строки подключения, идентификаторов и названий заведений

**Priority:** Critical
**Type:** Security
**AC:** AC-1 («сообщением на русском в stderr без строки подключения»); NFR-1; ADR-60.1 (ни числа, ни идентификаторов, ни названий найденных заведений)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_seed_guard.py::test_refusal_text_is_russian_without_connection_details`, `tests/test_seed.py::test_foreign_tenants_are_refused_with_exit_code_2` (в stderr нет пароля и хоста `db.invalid`, нет текста ошибки БД); `tests/db/test_seed.py::test_cli_refuses_base_with_other_tenant`, `::test_cli_refuses_demo_plus_other_without_updating_demo` (stdout пуст; stderr — ровно текст отказа; нет пароля, хоста, имени базы, пользователя, `postgresql`, UUID и названия найденного заведения).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить текст `FOREIGN_TENANTS_REFUSAL` | На русском; говорит, что в базе есть другие заведения, ничего не записано, сид только для базы разработки; упоминает `--database-url` и `DATABASE_URL` как имена параметров |
| 2 | Проверить отсутствие в тексте деталей | Нет строки подключения, хоста, порта, имени базы, пароля, UUID, числа и названий заведений |
| 3 | Отказ через CLI | Текст выводится только в stderr; stdout пуст |

---

## TC-60-008: Проверка — первый запрос транзакции сида; при отказе загрузчик не вызывается

**Priority:** High
**Type:** Functional / Security
**AC:** FR-1 («до первой записи, в той же транзакции»); ADR-60.1; NFR-4 (один запрос `EXISTS`)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_seed.py::test_target_check_runs_before_apply_seed_in_same_session`, `tests/test_seed.py::test_foreign_tenants_are_refused_with_exit_code_2` (`apply_seed` не вызван), `tests/test_seed_guard.py::test_foreign_tenants_exist_query`, `tests/test_seed_guard.py::test_demo_tenant_exists_query`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Подменить `ensure_seed_target` и `apply_seed` шпионами, запустить CLI | Порядок вызовов: проверка, затем загрузчик; оба получают одну и ту же сессию |
| 2 | Проверка возбуждает `ForeignTenantsError` | `apply_seed` не вызван, транзакция откатывается, код 2 |
| 3 | Проверить SQL проверки | Один запрос `SELECT EXISTS (… FROM tenants WHERE id <> DEMO_TENANT_ID)`; `None` от драйвера трактуется как False |

### Notes
Гонка (другое заведение создаётся параллельно с сидом) блокировкой не закрыта — решение ADR-60.1 (READ COMMITTED); последствие ловит #71. Тестом не покрывается намеренно.

---

## TC-60-009: Одинаковое поведение в режимах single и scaled, на Windows и Linux

**Priority:** Medium
**Type:** Functional (переносимость)
**AC:** E-10; NFR-2, NFR-3, NFR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_seed.py::test_foreign_tenants_refusal_is_same_in_both_modes[single|scaled]` (отказ AC-1 при `APP_MODE=single` и `scaled`, Redis не нужен); unit-тесты без БД (`tests/test_seed_guard.py`, тесты #60 в `tests/test_seed.py`) в матрице CI на Windows и Linux; db-тесты (`tests/db/test_seed.py`) — в Linux-джобе `backend-services`; ручной прогон на Windows в режиме single — TC-60-010. Код проверки (`app/seed/guard.py`) использует только `AsyncSession` и не импортирует Redis, `EventBus`, `TaskScheduler`, `RateLimiter` (проверено чтением кода; общий тест границ импортов — TC-38-003).
**Статус прогона:** PASS (локально Windows: unit и db; Linux — по результату CI PR)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Прогнать unit-тесты #60 на Windows и Linux | PASS на обеих ОС |
| 2 | Прогнать db-тесты #60 на PostgreSQL | PASS |
| 3 | Проверить импорты `app/seed/guard.py` | Только SQLAlchemy, модели и `app.seed.data`; новых переменных окружения и флага отключения проверки нет |

---

## TC-60-010: Ручной — сид с --database-url базы, где есть другое заведение (Windows, режим single)

**Priority:** Critical
**Type:** Security / Negative
**AC:** AC-1; E-4, E-6, E-10
**E2E Automated:** No
**Автоматизация:** Ручной.
**Статус прогона:** PASS (2026-10-28, Windows 11, PowerShell 5.1, локальный PostgreSQL 16, тестовая база `*_test`, `APP_ENV=dev`, `APP_MODE=single`)

### Preconditions
- База разработки или тестовая база с применёнными миграциями (`alembic upgrade head`); боевые базы не использовать.
- В `tenants` добавлено и зафиксировано одно заведение, кроме демо, например `INSERT INTO tenants (name) VALUES ('Другое заведение TC-60')`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить `tenants` | 1 строка, демо-заведения (`DEMO_TENANT_ID`) нет, `tables` пуста |
| 2 | В PowerShell из `backend/`: `$env:APP_ENV='dev'; $env:APP_MODE='single'` | — |
| 3 | `python -m app.seed --database-url 'postgresql+asyncpg://user:***@host/db'` | Процесс завершается |
| 4 | `$LASTEXITCODE` | `2` |
| 5 | Посмотреть вывод | stdout пуст; в stderr одна строка на русском: «В целевой базе уже есть заведения, кроме демо-заведения: демо-данные в такую базу не загружаются, ничего не записано…»; нет хоста, порта, имени базы, пароля и названия заведения |
| 6 | Снова проверить `tenants` и `tables` | Без изменений: 1 строка, демо-заведения нет, `tables` пуста |
| 7 | Тот же запуск с `--database-url` на недоступный порт (E-6) | Код 1; «Не удалось загрузить демо-данные: ConnectionRefusedError…» и подсказка `alembic upgrade head`; пароля нет |
| 8 | Удалить добавленное заведение | База в исходном состоянии |

### Фактический результат (2026-10-28)
Шаги 1–8 — как ожидалось: `$LASTEXITCODE = 2` (и `ExitCode = 2` у `Start-Process`), stdout пуст, stderr содержит только текст отказа, в нём нет хоста, порта, имени базы, пароля и названия заведения; `tenants` = 1 до и после, демо-заведение не появилось, `tables` = 0. На шаге 7 — код 1, пароля, хоста и порта в выводе нет (для отказа соединения драйвер их не включил; в общем случае см. ограничение NFR-1 в TC-60-006). Добавленное заведение удалено, тестовая база возвращена к пустому состоянию.

---

## Related TCs
- TC-53-003 (отказ при `APP_ENV=prod`; замечание security review #53 из его Notes закрыто этой историей — TC-60-001, TC-60-002, TC-60-010)
- TC-53-002 (идемпотентность сида — основа TC-60-004)
- TC-53-005 (ошибки запуска без раскрытия пароля — основа TC-60-006)
- TC-48-004 (db-тесты сида выполняются только на базе `*_test`)
- TC-38-003 (границы импортов Redis/arq/apscheduler — NFR-2, TC-60-009)
- #71 (AC-2, E-7…E-9: неготовность приложения в prod при демо-заведении) — `docs/test-cases/feature-71-demo-data-readiness.md` (TC-71-001…TC-71-014)
