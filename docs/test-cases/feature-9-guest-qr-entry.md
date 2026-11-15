# Test Cases: Feature #9 — Вход гостя по QR-токену, визит, язык

**Feature:** #9 (stories #75–#86, AC-1…AC-12)
**Spec:** docs/specs/feature-9-guest-qr-entry.md (FR-1…FR-12, NFR-1…NFR-9, E-1…E-20, ADR-9.6, R-Q2, R-Q3, Q-1, Q-4)
**Arch:** docs/arch/feature-9-guest-qr-entry.md (ADR-9.1…9.7, «API Contracts», раздел «Реализация (после G4, 2026-11-15)»)
**Story memory:** .claude/memory/stories/story-9.md
**Created:** 2026-11-15

Обозначения: **Авто** — тест выполняется автоматически: backend — пути относительно `backend/` (`tests/db/` — маркер `db`, нужен PostgreSQL), frontend — относительно `frontend/` (Vitest), имя теста — `файл::функция` (pytest, `[…]` — параметры) или `файл::«describe › it»` (Vitest); **Ручной** — шаги вручную; **Статическая** — проверка чтением файла.

**Статус прогона** — на 2026-11-15 (qa-lead, локально Windows, PostgreSQL 16): backend `pytest -q --cov=app --cov-branch` — 2014 passed, 3 skipped (scaled без `REDIS_URL`), 100,4 с, покрытие `app` 100% строк и ветвей (набор CI `-m "not db and not scaled"` — 1696 passed за 23 с, `-m db` — 318 passed за 53 с); frontend `npm run test -- --run --coverage` — 141 passed, ~9 с, строки 100%, ветви 99,19% (`GuestScreen.tsx` 97,87%: недостижимая защитная ветвь в строке 71). Тест `src/App.test.tsx::«Маршруты приложения › /t/demo лениво загружает экран гостя и входит по токену»` был **нестабилен** (вызов `fetch` проверялся раньше passive effect lazy-компонента) — исправлен через `waitFor`, после исправления 9 прогонов подряд без падений. Ручные TC (TC-75-007, TC-84-004, TC-86-006) — **НЕ ВЫПОЛНЕН**, G5 не блокируют.

Решения, от которых зависят ожидаемые результаты:
- **ADR-9.6 (подтверждено пользователем 2026-11-11):** неизвестный, перевыпущенный, неверный по формату токен и демо-токен при `APP_ENV=prod` — единый **404 `{"detail": {"code": "qr_invalid"}}`** (одинаковые тело и заголовки, без cookie); найденный токен отключённого стола (`is_active = false`) — **403 `table_inactive`** без данных заведения и стола. Сессия демо-заведения при prod — **401 `guest_session_invalid`**.
- **R-Q3:** перевыпуск токена и отключение стола обрывают действующие сессии на следующем запросе (`tia` в cookie сверяется с `tables.token_issued_at`, плюс `is_active`).
- **R-Q2:** язык экрана ошибки входа — `navigator.language` (`az`/`ru`), иначе `az`.
- **Q-4 / E-20 (не решён, решение в #27):** после повторного включения стола без перевыпуска прежние cookie снова действуют — TC фиксирует текущее поведение, это **не дефект**.

Особенности реализации (arch «Реализация»), учтённые в ожиданиях:
1. Перевыпуск пишет `token_issued_at = clock_timestamp()`, а не `now()`: перевыпуск в той же транзакции (где стол создан или уже перевыпускался) всё равно меняет `tia`.
2. Get-or-open визита, шаг 1 — один `UPDATE visits SET last_activity_at … WHERE tenant_id, table_id, status='open' RETURNING`; затем `INSERT … ON CONFLICT DO NOTHING` (до 3 попыток, затем 503 `try_again`).
3. `GuestRoute` ставит `Cache-Control: no-store` на **все** ответы `/api/guest/v1/*` (в том числе 401, 422, 429, 503) и переводит ошибки соединения с БД (`OperationalError`, `InterfaceError`, пул `TimeoutError`, `DBAPIError.connection_invalidated`, **`OSError`**) в 503 `try_again`; прочие исключения — 500.
4. Rate-limit входа — зависимость маршрута, выполняется **до валидации тела**: 422 тоже считаются попытками; синтаксически битый JSON FastAPI отклоняет раньше, он в лимит не попадает.
5. Frontend: токен из адресной строки не удаляется; каждый заход на `/t/{token}` — `POST /entry` (не `GET /session`); 422 входа показывается как `qr_invalid`; в dev под StrictMode два почти одновременных `POST /entry` (первый отменяется AbortController-ом) — **не дефект**, в prod-сборке запрос один.

Общее предусловие для db-тестов: применены миграции; фикстуры `tenant` («Кафе А», языки `["az","ru"]`) и `table` («Стол 7», активный, токен из `generate_qr_token`). Демо-заведение — сид (`apply_seed`, `DEMO_TENANT_ID`, токены `dev_token(n)`).

---

## TC-75-001: Первый вход по QR открывает визит, 200 и cookie `aiw_guest` с HttpOnly (AC-1)

**Priority:** Critical
**Type:** Functional
**AC:** AC-1; FR-1, FR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_entry_success_body_and_cookie`; с БД — `tests/db/test_guest_entry.py::test_first_entry_opens_visit`, `::test_http_full_flow_entry_session_lang`.
**Статус прогона:** PASS

### Preconditions
- Активный стол с действительным токеном, у стола нет открытого визита.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `POST /api/guest/v1/entry` `{"token": "<токен>"}`, `Accept-Language: ru-RU,ru;q=0.9,en;q=0.8` | 200; тело `{tenant{name, languages, default_lang, currency}, table{name, type}, visit{id, opened_at, is_new: true}, lang: "ru"}` |
| 2 | Проверить `visits` | Один визит `status=open`, `lang=ru`, `tenant_id`/`table_id` стола, `opened_at` с зоной, `closed_at` пуст |
| 3 | Проверить `Set-Cookie` | `aiw_guest=v1.<payload>.<sig>`, `HttpOnly`; claims cookie: `tid`, `tbl`, `vid` визита, `lang=ru`, `tia` = `token_issued_at` стола |
| 4 | Проверить заголовки | `Cache-Control: no-store` |

---

## TC-75-002: Ответ входа без внутренних идентификаторов, `tenant_id` от клиента не принимается

**Priority:** Critical
**Type:** Security
**AC:** AC-1; FR-1, NFR-2, NFR-3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_entry_success_body_and_cookie` (в тексте ответа нет `tenant_id`, `table_id`, токена, `price_tier`, `external_id`; токена нет в значении cookie), `::test_session_ignores_client_supplied_ids`, `::test_openapi_has_guest_paths_without_internal_details`, `::test_router_and_codec_are_wired`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Успешный вход, просмотреть тело ответа | Нет `tenant_id`, `table_id`, `hall_id`, `price_tier`, `external_id`, `qr_token`; токен не встречается ни в теле, ни в значении cookie |
| 2 | `GET /session` с параметрами `tenant_id`, `visit_id` чужих сущностей | Используются только claims cookie (`tid` из cookie) |
| 3 | `GET /openapi.json` | Пути `/entry`, `/session`, `/session/lang` есть; в их описании нет `demo` и `reject` (ADR-60.3) |

---

## TC-75-003: Превью ссылки и prefetch `/t/{token}` не открывают визит (E-16)

**Priority:** High
**Type:** Functional / Security
**AC:** E-16; FR-1, ADR-9.1
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_http_spa_page_does_not_open_visit` (G5, tester), `tests/test_guest_api.py::test_entry_get_is_not_allowed`, `tests/test_spa.py::test_spa_routes_fall_back_to_index[/t/some-token]`, `[/t/demo]`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET` и `HEAD` `/t/{токен}` и `/t/{токен}/menu` с `User-Agent: TelegramBot`, `Purpose: prefetch` | 200 `text/html` (index.html SPA), без `Set-Cookie`; визитов у стола 0 |
| 2 | `GET /api/guest/v1/entry` | 405, сервис входа не вызывается |
| 3 | `POST /api/guest/v1/entry` с тем же токеном | 200; у стола ровно 1 визит |

---

## TC-75-004: БД недоступна — 503 `try_again` с no-store, без деталей подключения (E-15)

**Priority:** High
**Type:** Negative / Security
**AC:** E-15; arch «API Contracts», «Реализация» п. 3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_database_unavailable_is_try_again_without_details[operational|interface|invalidated|pool-timeout|refused|timeout]`, `::test_database_error_text_is_masked_in_log`, `::test_describe_db_error_without_container`, `::test_other_errors_are_500[runtime|integrity|dbapi-not-invalidated]`, `::test_entry_visit_conflict_is_try_again`. Frontend-часть — TC-85-004.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Сервис входа бросает `OperationalError` / `InterfaceError` / `DBAPIError(connection_invalidated=True)` / пул `TimeoutError` / `ConnectionRefusedError` (`OSError`, как asyncpg) / `TimeoutError`; `POST /entry` и `GET /session` | Оба ответа 503 `{"detail": {"code": "try_again"}}`, `Cache-Control: no-store`, без `Set-Cookie`, без адреса БД в теле |
| 2 | Проверить лог `app.api.guest` | По одной записи WARNING на запрос, с именем класса; текст — через `Database.describe_error` (адрес замаскирован `***`); без контейнера — только имя класса |
| 3 | `RuntimeError`, `IntegrityError`, `DBAPIError` без `connection_invalidated` | 500 (не 503) |
| 4 | `VisitOpenConflictError` (3 попытки get-or-open исчерпаны) | 503 `try_again`, WARNING |

### Notes
Security INFO: перехват `OSError` широкий — ошибка файловой системы в будущих #10–#12 станет 503, а не 500 (arch «Реализация» п. 3, предложено сузить).

---

## TC-75-005: Только JSON-тело (CSRF), стандартная 422 валидации тела (NFR-5)

**Priority:** High
**Type:** Security / Negative
**AC:** NFR-5; FR-3 (тело вне 1…128 — 422), E-4
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_entry_rejects_non_json_body`, `::test_entry_body_validation_is_standard_422[missing|empty|too-long|lang|type]`, `::test_change_lang_requires_json_body`; Service Worker — `frontend/pwa-config.test.ts::«сборка: PWA › service worker не перехватывает API, Integration API и /health, но отдаёт SPA для экранов»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `POST /entry` form-data и `text/plain` с JSON внутри | 422; сервис не вызывается |
| 2 | `POST /entry` тела `{}`, `{"token": ""}`, токен 129 символов, `lang: "en"`, `token: 123` | 422, `detail` — массив (стандарт FastAPI), `Cache-Control: no-store`; сервис не вызывается |
| 3 | `PUT /session/lang` `text/plain` и form | 422 |
| 4 | Конфигурация SW (`navigateFallbackDenylist`) | `/api/*` Service Worker не перехватывает |

---

## TC-75-006: Логи входа и отказов без токена, cookie и `Accept-Language` (NFR-3)

**Priority:** High
**Type:** Security
**AC:** NFR-3; arch «Security», «Реализация» п. 7
**E2E Automated:** No
**Автоматизация:** Авто (частично) — `tests/test_guest_api.py::test_session_invalid_and_closed[*]` (INFO `app.api.guest_auth` с `code`, без значения cookie), `::test_entry_rate_limiter_failure_is_fail_open` (WARNING только с именами классов), `::test_database_error_text_is_masked_in_log`. INFO-записи `app.guest.entry` («Отказ во входе гостя» с `code`/`reason`/`tenant_id`/`table_id`; «Вход гостя» с `tenant_id`, `table_id`, `visit_id`, `is_new`, `lang`) тестами не проверяются — **Статическая**: `backend/app/guest/entry.py::_refuse_entry`, `enter_table`.
**Статус прогона:** PASS (авто-часть); статическая проверка 2026-11-15 — PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | 401 `guest_session_invalid` / `visit_closed` на `GET /session` | Одна запись INFO `app.api.guest_auth`, атрибут `code`; значения cookie в логе нет |
| 2 | Сбой лимитера с паролем Redis в тексте | WARNING `ConnectionError <- OSError`, без текста исключений |
| 3 | Прочитать `entry.py`: отказ входа (формат, неизвестный, демо, отключён) и успешный вход | `extra` содержит только машинный код, причину и идентификаторы; токена, cookie и `Accept-Language` нет |

### Notes
Пробел автотестов (не дефект): содержимое INFO-записей `app.guest.entry` не закреплено тестом с `caplog` — рекомендация tester'у. Путь `/t/{token}` в access-логе uvicorn/Caddy — принятый риск R-2 (#32).

---

## TC-75-007: Ручной — замер NFR-6: p95 входа ≤ 200 мс на сервере без нагрузки

**Priority:** Medium
**Type:** Performance (Ручной)
**AC:** NFR-6
**E2E Automated:** No
**Автоматизация:** Ручной.
**Статус прогона:** НЕ ВЫПОЛНЕН

### Preconditions
- Режим `single`, `APP_ENV=dev`, PostgreSQL 16 на том же хосте; сид загружен (`python -m app.seed`), миграции применены.
- `GUEST_ENTRY_RATE_LIMIT=0` (иначе 31-й запрос в минуту получит 429), `LOG_LEVEL=INFO`.
- Машина без посторонней нагрузки; замер — с того же хоста (`127.0.0.1`), чтобы исключить сеть.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запустить `uv run python -m app`; прогреть: 20 запросов `POST http://127.0.0.1:8000/api/guest/v1/entry` с `{"token": "<dev_token(1)>"}` | 200 |
| 2 | Выполнить 500 последовательных запросов входа по токену стола с открытым визитом (присоединение), например `hey -n 500 -c 1 -m POST -T application/json -d '{"token":"…"}' …` или скрипт `httpx` с `time.perf_counter()` | Все 200 |
| 3 | Выполнить 200 запросов входа к 200 разным столам без визита (создание визита; столы создать заранее, токены — `generate_qr_token`) | Все 200, `is_new = true` |
| 4 | Посчитать p50/p95/p99 времени ответа по шагам 2 и 3 отдельно | **p95 ≤ 200 мс** в обоих случаях |
| 5 | Повторить шаг 2 в режиме `scaled` (Docker Compose, лимитер Redis) | p95 ≤ 200 мс |

### Notes
Зафиксировать в отчёте: ОС, CPU, версию PostgreSQL, режим, p50/p95/p99. Превышение порога — дефект NFR-6 (средний приоритет), G5 не блокирует.

---

## TC-76-001: Второе устройство присоединяется к открытому визиту (AC-2)

**Priority:** Critical
**Type:** Functional
**AC:** AC-2; FR-2, FR-12
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_second_entry_joins_open_visit`, `::test_http_full_flow_entry_session_lang` (повторный вход — `is_new = false`); `tests/test_guest_api.py::test_entry_rejoin_returns_is_new_false`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вход с устройства A (`lang=az`) | Визит создан, `is_new = true` |
| 2 | Сдвинуть `last_activity_at` визита на 3 ч назад; вход с устройства B (`lang=ru`) | Тот же `visit.id`, `is_new = false`, язык ответа `ru` (у устройства свой) |
| 3 | Проверить визит | `visits.lang` остался `az` (меняет только явная смена языка); `last_activity_at` обновлён (одним `UPDATE … RETURNING`); открытых визитов у стола ровно 1 |

---

## TC-76-002: Одновременные входы к столу без визита — ровно один визит, не 500 (E-1)

**Priority:** Critical
**Type:** Functional / Concurrency
**AC:** E-1; FR-2, ADR-9.3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_concurrent_entries_open_exactly_one_visit` (5 столов × 4 устройства, настоящий commit), `::test_insert_conflict_joins_visit_of_parallel_transaction` (детерминированная гонка двух транзакций); `tests/test_guest_services.py::test_get_or_open_visit_gives_up_after_attempts`; `tests/test_guest_api.py::test_entry_visit_conflict_is_try_again`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `asyncio.gather` 4 входов на каждый из 5 столов, отдельные сессии БД | На каждый стол один `visit.id`, ровно один `created = true`, один визит в БД |
| 2 | Транзакция A открыла визит и не зафиксирована; транзакция B — get-or-open того же стола | B ждёт на `uq_visits_open_table`; после commit A получает пустой `RETURNING`, присоединяется к визиту A (`created = false`, `lang` визита — A) |
| 3 | Визит «пропадает» между шагами на каждой из 3 попыток | `VisitOpenConflictError` → 503 `try_again` (не 500) |

---

## TC-76-003: Перезагрузка `/t/{token}` с действующей cookie — тот же визит и выбранный язык (E-2)

**Priority:** High
**Type:** Functional
**AC:** E-2; FR-7 шаги 1–2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_reentry_keeps_language_of_same_table_cookie`, `::test_http_full_flow_entry_session_lang` (после смены на `az` повторный вход с `Accept-Language: ru` — `az`, `is_new = false`); `tests/test_guest_api.py::test_entry_passes_claims_of_existing_cookie` (битая cookie — как отсутствующая); frontend — `src/guest/GuestScreen.test.tsx::«#86 переключатель языка › выбор остаётся после перезагрузки: следующий вход передаёт его серверу»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вход, смена языка на `az`, повторный `POST /entry` с новой cookie и `Accept-Language: ru` | 200, `is_new = false`, `lang = az` |
| 2 | Повторный вход с cookie `v1.bad.sig` | Сервису передаётся `session_claims = None` (язык по шагам 3–4) |
| 3 | Frontend: перезагрузка после выбора языка | Следующий `POST /entry` несёт `lang` из `localStorage` |

---

## TC-76-004: `last_activity_at` — вход, смена языка, `touch_visit` только открытого визита своего заведения (FR-12)

**Priority:** Medium
**Type:** Functional
**AC:** FR-12; NFR-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_second_entry_joins_open_visit`, `::test_change_lang_updates_visit`, `::test_touch_visit_updates_only_open_visit_of_tenant`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Повторный вход / смена языка | `last_activity_at` больше прежнего |
| 2 | `touch_visit` с чужим `tenant_id` | Без изменений |
| 3 | `touch_visit` закрытого визита | Без изменений |

### Notes
Что `GET /session` не обновляет `last_activity_at`, тестом не закреплено (по коду `load_guest_context` только читает) — не дефект.

---

## TC-77-001: Единый ответ 404 `qr_invalid` на неизвестный, неверный по формату и перевыпущенный токен (AC-3)

**Priority:** Critical
**Type:** Security / Negative
**AC:** AC-3; FR-3, ADR-9.6, NFR-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_entry_invalid_token_responses_are_identical`; с БД — `tests/db/test_guest_entry.py::test_unknown_token_does_not_create_visit`, `::test_http_reissue_and_disable_break_sessions` (старый токен — 404), `::test_http_demo_in_prod` (демо и неизвестный — одинаковые тело и заголовки).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `POST /entry` с токеном `short` (формат) и с неизвестным токеном верного формата | Оба: 404 `{"detail": {"code": "qr_invalid"}}`, `Cache-Control: no-store`, без `Set-Cookie`; тела и наборы заголовков побайтно равны |
| 2 | Токен после перевыпуска (TC-79-001) | Тот же ответ |
| 3 | Проверить ответы и БД | Нет названия заведения, стола, причины и токена; визитов не прибавилось |

---

## TC-77-002: Формат токена — пробелы, регистр, длина, символы; без запроса в БД (E-4)

**Priority:** High
**Type:** Negative
**AC:** E-4; FR-3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_tokens.py::test_invalid_formats[empty|short|long|newline|lead-space|inner-space|padding|std-b64|cyrillic|pct]`, `::test_valid_formats`, `::test_non_string_is_invalid`; `tests/test_guest_api.py::test_entry_format_check_does_not_touch_database`, `::test_entry_body_validation_is_standard_422[empty|too-long]`; `tests/test_guest_services.py::test_enter_table_rejects_format_without_query`; `tests/db/test_guest_entry.py::test_unknown_token_does_not_create_visit` (`swapcase` — регистрозависим). Frontend-показ 422 — TC-85-002.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Токены 21 и 65 символов, с ведущим пробелом, с `\n` в конце, с `=`, `+/`, кириллицей, `%` | 404 `qr_invalid`; запрос к БД не выполняется (FakeSession падает при любом запросе) |
| 2 | Токены 22 и 64 символа base64url, `dev_token(1)` | Формат верен |
| 3 | Действующий токен в другом регистре | 404 `qr_invalid` (не нормализуется) |
| 4 | Пустой токен или длиннее 128 символов | 422 валидации тела (массив `detail`) |

---

## TC-77-003: Отключённый стол — 403 `table_inactive` без данных, визит не создаётся (E-5, ADR-9.6)

**Priority:** Critical
**Type:** Security / Negative
**AC:** E-5; FR-3, ADR-9.6 (решение пользователя)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_entry_table_inactive`; с БД — `tests/db/test_guest_entry.py::test_inactive_table_is_refused`, `::test_http_reissue_and_disable_break_sessions` (без `Set-Cookie`, нет «Кафе» и «Стол» в ответе). Сессии отключённого стола — TC-80-006.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Стол `is_active = false`; `POST /entry` с его токеном | 403 `{"detail": {"code": "table_inactive"}}`, `no-store`, без `Set-Cookie` |
| 2 | Проверить тело | Нет названия заведения и стола |
| 3 | Проверить `visits` | Визит не создан |

### Notes
Демо-проверка выполняется раньше проверки `is_active`: отключённый стол демо-заведения в prod отвечает 404 `qr_invalid`, а не 403 (не раскрывает существование демо-токена) — по коду `entry.enter_table`.

---

## TC-77-004: Rate-limit входа по IP — 429 `rate_limited` с `Retry-After`, 422 тоже считаются (E-18)

**Priority:** High
**Type:** Security / Negative
**AC:** E-18; FR-3, NFR-4, ADR-9.7, «Реализация» п. 4
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_entry_rate_limited`, `::test_entry_retry_after_is_at_least_one`, `::test_entry_rate_limit_counts_invalid_bodies`, `::test_entry_rate_limit_disabled`, `::test_entry_rate_limit_with_real_single_limiter`, `::test_entry_without_client_address_uses_unknown_key`, `::test_client_ip_key[*]` (10 параметров); `tests/test_config.py::test_guest_defaults` (30 в минуту). Frontend — TC-85-003.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Лимитер отказал (`retry_after=12.2`) | 429 `rate_limited`, `Retry-After: 13`, `no-store`; сервис не вызван; ключ `guest_entry:ip:127.0.0.1`, лимит 30, окно 60 с |
| 2 | `retry_after = 0` | `Retry-After: 1` |
| 3 | Лимит 5: запрос с пустым токеном (422) и обычный | Лимитер вызван оба раза — 422 считается попыткой |
| 4 | `GUEST_ENTRY_RATE_LIMIT=0` | 200, лимитер не вызывается |
| 5 | Настоящий лимитер `single`, лимит 2, три входа с неверным токеном | `[404, 404, 429]` |
| 6 | `client_ip_key`: IPv4, IPv6 (→ /64, `:`→`-`), IPv4-mapped, зона `%eth0`, `None`, `testclient`, `1.2.3.4:80` | Нормализованный ключ; нераспознанный — `unknown`; двоеточий нет |

### Notes
Синтаксически битый JSON отклоняется FastAPI до зависимостей и в лимит не попадает (известное ограничение, story memory). Security LOW: лимит 30/мин общий для NAT заведения, а `/entry` вызывается на каждой загрузке — см. TC-84-003.

---

## TC-77-005: Сбой `RateLimiter` не блокирует вход (fail-open, E-19)

**Priority:** High
**Type:** Negative / Resilience
**AC:** E-19; NFR-4
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_entry_rate_limiter_failure_is_fail_open`, `::test_exception_chain_names_uses_context_and_stops_on_cycles`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Лимитер бросает `ConnectionError("redis://:password@…")` с причиной `OSError` | Вход 200 |
| 2 | Проверить лог | Одна WARNING `ConnectionError <- OSError`; ни пароля, ни текста причины |
| 3 | Цепочка через `__context__`, цикл, `__suppress_context__` | Имена без зацикливания, подавленный контекст не выводится |

---

## TC-78-001: Демо-токен при `APP_ENV=prod` — как неизвестный (AC-4)

**Priority:** Critical
**Type:** Security
**AC:** AC-4; FR-4, ADR-9.6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_http_demo_in_prod`, `::test_demo_tokens_rejected_only_with_reject_demo`; `tests/test_guest_api.py::test_entry_secure_cookie_and_reject_demo_flags[*]` (`reject_demo` только при prod), `::test_openapi_has_guest_paths_without_internal_details`.
**Статус прогона:** PASS

### Preconditions
- Сид загружен; приложение с `APP_ENV=prod`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `POST /entry` с `dev_token(3)` и с неизвестным токеном | Оба 404 `qr_invalid`; тела и заголовки равны |
| 2 | Проверить `visits` | Визитов не прибавилось |
| 3 | OpenAPI гостевых путей | Без упоминаний `demo`/`reject` |

---

## TC-78-002: `APP_ENV=dev`/`test` — демо-токены работают (E-9)

**Priority:** High
**Type:** Functional
**AC:** E-9; FR-4
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_demo_tokens_rejected_only_with_reject_demo`, `::test_http_demo_in_prod` (вход dev-приложения — 200); `tests/test_guest_api.py::test_entry_secure_cookie_and_reject_demo_flags` (`dev`, тестовое окружение — `reject_demo=False`).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `APP_ENV=dev`, вход по `dev_token(2)` | 200, заведение `DEMO_TENANT_ID` |

---

## TC-78-003: Сессия визита демо-заведения при prod — 401 `guest_session_invalid` (E-10)

**Priority:** Critical
**Type:** Security
**AC:** E-10; FR-4, FR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_http_demo_in_prod` (cookie dev-входа подписана тем же секретом и верна), `::test_demo_session_is_invalid_with_reject_demo`; `tests/test_guest_services.py::test_load_guest_context_rejects_demo_before_query` (без запроса в БД); `tests/test_guest_api.py::test_session_reject_demo_in_prod`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Cookie, выданная при dev на демо-визит; `GET /session` у prod-приложения с тем же секретом | 401 `{"detail": {"code": "guest_session_invalid"}}` |
| 2 | `load_guest_context(reject_demo=True)` с claims демо-заведения | `GuestSessionInvalidError("demo")`, запрос в БД не выполняется |

---

## TC-79-001: Перевыпуск токена — новый T2 (32 символа, 192 бита), T1 недействителен, T2 работает (AC-5)

**Priority:** Critical
**Type:** Functional / Security
**AC:** AC-5; FR-5, ADR-9.5
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_reissue_token`, `::test_http_reissue_and_disable_break_sessions`; `tests/test_guest_tokens.py::test_generated_token_is_32_base64url_chars_with_192_bits`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `reissue_table_token(tenant_id, table_id)`, commit | Новый токен ≠ старого, 32 символа, проходит `QR_TOKEN_PATTERN`; `token_issued_at` больше прежнего |
| 2 | Вход по T1 | 404 `qr_invalid` |
| 3 | Вход по T2 | 200 |

---

## TC-79-002: Перевыпуск при сидящих гостях — сессии 401, новый QR ведёт в тот же визит (E-6, R-Q3)

**Priority:** Critical
**Type:** Security
**AC:** E-6; FR-5, FR-6, R-Q3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_reissue_token`, `::test_http_reissue_and_disable_break_sessions`; `tests/test_guest_api.py::test_session_invalid_and_closed` (параметр `token_reissued`).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Гость вошёл; перевыпуск, commit; `GET /session` со старой cookie | 401 `guest_session_invalid` (`tia` не совпал) |
| 2 | Вход по новому токену | Тот же `visit.id`, `is_new = false` (визит принадлежит столу) |

---

## TC-79-003: Перевыпуск дважды в одной транзакции меняет `token_issued_at` (`clock_timestamp()`)

**Priority:** High
**Type:** Functional / Regression
**AC:** FR-5, R-Q3; arch «Реализация» п. 1
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_reissue_twice_in_one_transaction_changes_issued_at`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Два вызова `reissue_table_token` в одной транзакции | `token_issued_at` второго строго больше первого (с `now()` они были бы равны и сессии со старым `tia` остались бы действительны) |

---

## TC-79-004: Коллизия нового токена — повтор в SAVEPOINT, не 500 (E-17)

**Priority:** Medium
**Type:** Negative
**AC:** E-17; FR-5
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_reissue_retries_on_collision`, `::test_reissue_gives_up_after_attempts`; `tests/test_guest_services.py::test_reissue_collision_retries_up_to_limit`, `::test_reissue_reraises_other_integrity_error_immediately`, `::test_reissue_integrity_error_without_orig_is_not_collision`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Генератор дважды возвращает токен другого стола, затем свежий | Перевыпуск успешен со свежим токеном; токен другого стола не тронут |
| 2 | Генератор всегда даёт коллизию | `IntegrityError` после `REISSUE_ATTEMPTS` (3) попыток; токен стола прежний, сессия БД рабочая |
| 3 | `IntegrityError` другого ограничения / без `orig` | Пробрасывается сразу, без повторов |

---

## TC-79-005: Непредсказуемость токенов и tenant-фильтр перевыпуска (NFR-1, NFR-2)

**Priority:** High
**Type:** Security
**AC:** NFR-1, NFR-2; FR-5
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_tokens.py::test_generator_uses_secrets`, `::test_generated_tokens_are_unique`; `tests/db/test_guest_entry.py::test_reissue_filters_by_tenant`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Генерация | Через `secrets.token_urlsafe(24)`; 1000 токенов уникальны |
| 2 | Перевыпуск с чужим `tenant_id` или несуществующим `table_id` | `TableNotFoundError`; токен стола не изменился |

---

## TC-80-001: `GET /session` возвращает данные из сессии, без `tenant_id`/`visit_id` из запроса (AC-6)

**Priority:** Critical
**Type:** Functional / Security
**AC:** AC-6; FR-6, NFR-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_session_returns_view_without_set_cookie`, `::test_session_ignores_client_supplied_ids`, `::test_current_guest_builds_context`; `tests/db/test_guest_entry.py::test_load_guest_context_returns_view`, `::test_http_full_flow_entry_session_lang`; frontend-клиент — `src/api/client.test.ts::«getGuestSession › GET /api/guest/v1/session без тела»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET /session` с cookie входа | 200: `tenant`, `table`, `visit{id, opened_at}` (без `is_new`), `lang`; `no-store`; `Set-Cookie` нет |
| 2 | То же с query `tenant_id`, `visit_id` | Игнорируются, используется `tid` cookie |
| 3 | `current_guest` | `GuestContext(tenant_id, table_id, visit_id, lang, price_tier, languages, currency)` |

---

## TC-80-002: Нет cookie, повреждена, подделана, чужой секрет, неизвестная версия, истёк срок — 401 `guest_session_required` (E-14)

**Priority:** Critical
**Type:** Security / Negative
**AC:** AC-6; E-14, FR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_session_required[*]` (нет cookie, `""`, `garbage`, `v1.a.b`, `v2.a.b`), `::test_session_with_foreign_secret_or_expired`, `::test_change_lang_requires_session`; `tests/test_guest_session.py::test_decode_malformed_values[*]`, `::test_decode_rejects_unknown_version`, `::test_decode_rejects_tampered_payload`, `::test_decode_rejects_tampered_signature`, `::test_decode_rejects_other_secret`, `::test_decode_rejects_too_long_value`, `::test_decode_rejects_non_ascii`, `::test_decode_rejects_bad_base64_with_valid_signature`, `::test_decode_rejects_bad_json_with_valid_signature`, `::test_decode_rejects_invalid_utf8_with_valid_signature`, `::test_decode_rejects_wrong_fields[*]`, `::test_decode_rejects_non_object_payload[*]`, `::test_decode_expired_at_ttl_boundary`, `::test_decode_allows_small_clock_skew`, `::test_decode_rejects_iat_far_in_future`, `::test_decode_uses_current_time_by_default`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET /session` без cookie, с `""`, `garbage`, `v1.a.b`, `v2.a.b` | 401 `guest_session_required`, `no-store`; запроса в БД нет |
| 2 | Cookie, подписанная другим секретом; cookie с `iat` 13 ч назад (TTL 12 ч) | 401 `guest_session_required` |
| 3 | Кодек: изменённые payload/подпись, не-ASCII, слишком длинное значение, битые base64/JSON/UTF-8 при верной подписи, лишние/неверные поля | `decode` → `None` |
| 4 | Ровно на границе TTL; `iat` в будущем на ≤ 60 с; далеко в будущем | Истекла; допустима; отклонена |
| 5 | `PUT /session/lang` без cookie | 401 `guest_session_required` |

---

## TC-80-003: Cookie с чужими `vid`/`tid`/`tbl` при верной подписи — 401 `guest_session_invalid` (E-14a)

**Priority:** Critical
**Type:** Security / RBAC (tenant-изоляция)
**AC:** E-14a; NFR-2, FR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_session_of_other_tenant_or_table_is_invalid`; `tests/test_guest_api.py::test_session_invalid_and_closed` (параметр `not_found`, без `visit_id` в ответе); `tests/test_guest_session.py::test_forged_valid_data_is_accepted` (кодек проверяет только подпись — защита на уровне запроса в БД).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Подписанные claims: чужое заведение при своих `vid`/`tbl`; чужой визит; чужие визит и заведение при своём столе; другой стол того же заведения; случайный `vid` | Во всех случаях `GuestSessionInvalidError("not_found")` → 401 `guest_session_invalid`; данные чужого визита не возвращаются |

---

## TC-80-004: Атрибуты cookie `aiw_guest` и состав payload (FR-6, NFR-8)

**Priority:** High
**Type:** Security
**AC:** FR-6, NFR-5, NFR-8
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_entry_success_body_and_cookie`, `::test_entry_secure_cookie_and_reject_demo_flags[*]`, `::test_entry_ttl_from_settings`; `tests/test_guest_session.py::test_roundtrip`, `::test_payload_is_compact_json_without_extra_fields`, `::test_value_fits_max_length`, `::test_issue_claims_fills_tia_and_iat`, `::test_issue_claims_defaults_to_current_time`, `::test_epoch_micros_is_exact_and_zone_independent`, `::test_epoch_micros_rejects_naive_datetime`, `::test_remaining_seconds`, `::test_remaining_seconds_defaults_to_now`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вход в test-окружении | `HttpOnly`, `SameSite=Strict`, `Path=/api/guest/`, `Max-Age=43200`; без `Domain` и `Secure` |
| 2 | prod; prod с `GUEST_COOKIE_SECURE=false`; dev с `GUEST_COOKIE_SECURE=true` | `Secure` есть; нет; есть |
| 3 | `GUEST_SESSION_TTL_HOURS=2` | `Max-Age=7200` |
| 4 | Декодировать payload | Только идентификаторы визита, заведения, стола, `tia`, `lang`, `iat`; без токена, IP, User-Agent |

---

## TC-80-005: `GUEST_SESSION_SECRET` и настройки сессии (NFR-7)

**Priority:** High
**Type:** Security / Configuration
**AC:** NFR-7, FR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_config.py::test_guest_session_secret_required_in_prod_and_scaled[prod|scaled]`, `::test_guest_session_secret_optional_in_single_outside_prod[*]`, `::test_guest_session_secret_too_short_without_value_in_text[single|prod|scaled]`, `::test_guest_session_secret_of_min_length_is_accepted`, `::test_missing_guest_secret_reported_by_get_settings`, `::test_guest_secret_from_environment`, `::test_guest_cookie_secure_effective[*]`, `::test_guest_defaults`; `tests/test_guest_session.py::test_codec_rejects_short_secret`, `::test_codec_rejects_non_positive_ttl[*]`, `::test_build_codec_with_secret_does_not_warn`, `::test_build_codec_without_secret_uses_random_key_and_warns`; `tests/test_guest_api.py::test_router_and_codec_are_wired`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | prod или scaled без секрета | `ConfigError`/`ValidationError` «GUEST_SESSION_SECRET обязателен…» |
| 2 | single dev/test без секрета | Запуск; случайный ключ процесса, WARNING |
| 3 | Секрет короче 32 символов в любом режиме | Ошибка, значение секрета в тексте отсутствует |
| 4 | Значения по умолчанию | TTL 12 ч, лимит 30, `GUEST_COOKIE_SECURE` не задан (= prod) |

### Notes
Границы `GUEST_SESSION_TTL_HOURS` 1…72 заданы `Field(ge=1, le=72)` и отдельным тестом не закреплены (пробел, не дефект). `deploy/docker-compose.yml` не требует секрет через `${…:?}` — решение в #30.

---

## TC-80-006: Отключение стола обрывает сессии на следующем запросе, визит не закрывается (E-5, R-Q3)

**Priority:** Critical
**Type:** Security
**AC:** E-5; FR-6, R-Q3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_http_reissue_and_disable_break_sessions`, `::test_inactive_table_and_reactivation_e20` (часть «отключён»).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Гость с действующей cookie; `is_active = false`, commit; `GET /session` | 401 `guest_session_invalid` (причина `table_inactive` — только в INFO-логе) |
| 2 | Новый вход по токену стола | 403 `table_inactive` (TC-77-003) |
| 3 | Проверить визит | Остаётся `open` — закрывает официант или #23 |

---

## TC-80-007: Повторное включение стола без перевыпуска — прежние cookie снова действуют (E-20, Q-4: фиксация текущего поведения)

**Priority:** Medium
**Type:** Security (фиксация поведения)
**AC:** E-20; Q-4 (открыт, решение в #27)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_inactive_table_and_reactivation_e20`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Гость вошёл; стол отключён | Сессия — `GuestSessionInvalidError("table_inactive")` |
| 2 | Стол снова включён без перевыпуска токена | Та же cookie действует, визит прежний (`tia` совпадает, `is_active = true`) |

### Notes
**Не дефект.** Поведение соответствует spec E-20: сессия stateless, отключение — временная мера; чтобы окончательно отрезать прежних гостей, админ перевыпускает токен. Будет ли админка #27 перевыпускать токен при отключении — открытый вопрос Q-4. Security review: принятый риск (INFO).

---

## TC-80-008: QR другого стола или заведения заменяет сессию, данные первого не видны (E-3, D-2)

**Priority:** High
**Type:** Security / Functional
**AC:** E-3; D-2, NFR-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_http_scanning_other_tenant_replaces_session`, `::test_cookie_of_other_table_does_not_set_language`; frontend — `src/guest/GuestScreen.test.tsx::«GuestScreen: смена токена без перемонтирования › ошибка смены языка после неудачного входа по новому токену оставляет экран ошибки»` (G5, tester).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вход за стол «Кафе А», затем по QR «Кафе Б» с cookie первого входа; `GET /session` с новой cookie | Заведение «Кафе Б»; в ответе нет «Кафе А» и визита первого стола |
| 2 | Cookie стола 8 при входе за стол 7 того же заведения | Язык cookie не применяется (шаг 2 FR-7 только для того же стола) |
| 3 | Frontend: смена токена в `GuestScreen`, вход по новому — 404, затем поздний отказ смены языка прежнего стола | Остаётся экран ошибки нового входа; «прежний стол» не возвращается |

---

## TC-81-001: Сессия закрытого визита — 401 `visit_closed` без данных визита (AC-7)

**Priority:** Critical
**Type:** Functional / Security
**AC:** AC-7; FR-8, FR-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_http_closed_visit`, `::test_closed_visit_session_and_new_visit`; `tests/test_guest_api.py::test_session_invalid_and_closed` (параметр `VisitClosedError`).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `close_visit(closed_by=staff)`, commit; `GET /session` | 401 `{"detail": {"code": "visit_closed"}}`, без `visit.id` |
| 2 | `PUT /session/lang` с той же cookie | 401 `visit_closed` |

---

## TC-81-002: После закрытия визита повторное сканирование открывает новый визит (E-7)

**Priority:** High
**Type:** Functional
**AC:** E-7; FR-8, FR-1
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_closed_visit_session_and_new_visit`, `::test_http_closed_visit`. Кнопка «Начать заново» — TC-85-005.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Визит закрыт (`pos`); новый вход по тому же токену (с прежней cookie) | 200, `is_new = true`, новый `visit.id` |
| 2 | Проверить `visits` | Старый визит `closed`, `closed_by = pos` (история); всего 2, открытый 1 |

---

## TC-81-003: Повторное закрытие ничего не меняет; tenant-фильтр; `staff_id` только для `staff` (E-8)

**Priority:** High
**Type:** Functional / Negative
**AC:** E-8; FR-8
**E2E Automated:** No
**Автоматизация:** Авто — `tests/db/test_guest_entry.py::test_close_visit_is_idempotent_and_keeps_first_closer`, `::test_close_visit_filters_by_tenant`, `::test_close_visit_staff_id_only_for_staff`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Закрыть `staff` с `staff_id` | `True`; `closed`, `staff`, `closed_by_staff_id`, `closed_at` заполнены |
| 2 | Повторно закрыть `timeout` | `False`; `closed_by`, `closed_at`, `closed_by_staff_id` прежние; исключения нет |
| 3 | Закрыть с чужим `tenant_id` | `False`, визит открыт |
| 4 | `closed_by=pos` со `staff_id` | `ValueError` |

---

## TC-82-001: Язык по `Accept-Language`: `ru-RU,ru;q=0.9,en;q=0.8` → `ru` (AC-8)

**Priority:** Critical
**Type:** Functional
**AC:** AC-8; FR-7
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_lang.py::test_resolve_entry_lang[*]` (строки «AC-8»), `::test_parse_accept_language[*]`; `tests/db/test_guest_entry.py::test_first_entry_opens_visit`, `::test_http_full_flow_entry_session_lang`; `tests/test_guest_api.py::test_entry_success_body_and_cookie` (заголовок передан сервису).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Первый вход, заведение `["az","ru"]`, `Accept-Language: ru-RU,ru;q=0.9,en;q=0.8` | `lang = ru`, `visits.lang = ru` |
| 2 | `az-Latn-AZ`, заведение `["ru","az"]` | `az` |
| 3 | Без `az`/`ru` в заголовке | `tenants.languages[0]` |

---

## TC-82-002: Нет заголовка, `*`, `en-US`, `tr`, мусор, > 512 символов, язык не поддерживается заведением — язык по умолчанию (E-11)

**Priority:** High
**Type:** Negative
**AC:** E-11; FR-7
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_lang.py::test_parse_accept_language[*]` (26 параметров: q-value, `q=0`, `q>1`, мусорные теги, `\x00`), `::test_parse_truncates_long_header`, `::test_resolve_entry_lang[*]` (строки «E-11»); `tests/db/test_guest_entry.py::test_default_language_of_tenant`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Заголовок отсутствует / `*` / `\x00garbage` | `az` (первый язык `["az","ru"]`) |
| 2 | `en-US,tr;q=0.8`, заведение `["ru","az"]` | `ru` |
| 3 | `az`, заведение `["ru"]` | `ru` |
| 4 | Заголовок длиннее 512 символов с `ru` за границей | `ru` не учитывается; ошибки нет |

---

## TC-82-003: Порядок выбора языка: тело → cookie того же стола → браузер → по умолчанию (FR-7, ADR-9.4)

**Priority:** High
**Type:** Functional
**AC:** FR-7, FR-10; E-2
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_lang.py::test_resolve_entry_lang[*]` (строки «шаг 1», «шаг 2»); `tests/db/test_guest_entry.py::test_reentry_keeps_language_of_same_table_cookie`, `::test_cookie_of_other_table_does_not_set_language`, `::test_second_entry_joins_open_visit`; `tests/test_guest_api.py::test_entry_rejoin_returns_is_new_false`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `lang=ru` в теле, cookie `az`, браузер `az` | `ru` |
| 2 | `lang=az` в теле, заведение `["ru"]` | `ru` (выбор вне языков заведения пропускается) |
| 3 | Тела нет, cookie того же стола `ru`, браузер `az` | `ru` |
| 4 | Cookie другого стола | Не учитывается |
| 5 | Второе устройство с другим языком | Язык ответа — свой, `visits.lang` не меняется |

---

## TC-83-001: Смена языка `PUT /session/lang` — 200, переподписанная cookie, `GET /session` возвращает `az` (AC-9)

**Priority:** Critical
**Type:** Functional
**AC:** AC-9; FR-9, FR-10, FR-12
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_change_lang_resigns_cookie_without_extending`; `tests/db/test_guest_entry.py::test_http_full_flow_entry_session_lang`, `::test_change_lang_updates_visit`; клиент — `src/api/client.test.ts::«setGuestLang › PUT /api/guest/v1/session/lang с JSON-телом {lang}»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Сессия `ru`; `PUT /session/lang` `{"lang": "az"}` | 200 `GuestSessionResponse`, `lang = az`, без `visit.is_new`, `no-store` |
| 2 | Проверить `Set-Cookie` | Новая cookie, claims `lang = az`, `iat` прежний, `Max-Age` — остаток TTL (срок не продлевается), атрибуты как при входе |
| 3 | `GET /session` с новой cookie | `lang = az` |
| 4 | Проверить визит | `visits.lang = az`, `last_activity_at` обновлён |

---

## TC-83-002: Язык не из `Lang` или вне `tenants.languages` — 422, язык не меняется (E-12)

**Priority:** High
**Type:** Negative
**AC:** E-12; FR-9
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_change_lang_not_supported`, `::test_change_lang_invalid_value[*]` (`en`, `null`, `{}`); `tests/db/test_guest_entry.py::test_change_lang_not_supported_by_tenant`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Заведение `["ru"]`, `{"lang": "az"}` | 422 `{"detail": {"code": "lang_not_supported"}}`, без `Set-Cookie`; `visits.lang = ru` |
| 2 | `{"lang": "en"}`, `{"lang": null}`, `{}` | 422 стандартной валидации (массив), `no-store`; сервис не вызван |

---

## TC-83-003: Смена языка без действительной сессии или по закрытому визиту — 401

**Priority:** High
**Type:** Security / Negative
**AC:** FR-9, FR-6, NFR-5
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_guest_api.py::test_change_lang_requires_session`, `::test_change_lang_requires_json_body`; `tests/db/test_guest_entry.py::test_http_closed_visit`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Без cookie | 401 `guest_session_required` |
| 2 | Визит закрыт | 401 `visit_closed` |
| 3 | `text/plain` / form | 422 |

---

## TC-84-001: Экран стола — название заведения, стола и переключатель вместо заглушки (AC-10)

**Priority:** Critical
**Type:** Functional (UI)
**AC:** AC-10; FR-11
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#84 экран стола › входит по токену из адреса и показывает заведение, стол и переключатель»`, `::«#84 экран стола › кабина подписана как кабина; язык документа — язык гостя»`; `src/App.test.tsx::«Маршруты приложения › %s лениво загружает экран гостя и входит по токену»` (`/t/demo`, `/t/demo/menu`; был нестабилен при прогоне 2026-11-15, исправлен tester'ом через `waitFor`); `src/api/client.test.ts::«enterTable › POST /api/guest/v1/entry с JSON-телом {token, lang}»`.
**Статус прогона:** PASS (App.test.tsx — после исправления стабилен)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть `/t/{token}` | Lazy-загрузка экрана гостя, состояние загрузки, один `POST /api/guest/v1/entry` `{token, lang}` |
| 2 | Вход успешен | Видны название заведения, название стола, подпись «Ваш стол», переключатель языка |
| 3 | Стол типа `cabin`, язык `az` | Подпись «Kabinəniz»; `<html lang="az">` |

---

## TC-84-002: Экран стола не раскрывает токен, не исполняет разметку; Referrer-Policy same-origin

**Priority:** High
**Type:** Security (UI)
**AC:** FR-11, NFR-3; arch «Security», «Реализация» frontend п. 1
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#84 экран стола › токен не выводится на экран»`, `::«#84 экран стола › названия с разметкой выводятся как текст, не как HTML»`; `src/api/client.test.ts::«enterTable › сообщение ошибки не содержит токен и тело запроса»`. **Статическая** — `frontend/index.html`: `<meta name="referrer" content="same-origin" />` (строка 7).
**Статус прогона:** PASS; статическая проверка 2026-11-15 — PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Успешный вход, `innerHTML` экрана | Токена нет |
| 2 | Название заведения `<b>Кафе</b>` | Выводится текстом, элемента `<b>` нет |
| 3 | Ошибка `enterTable` | В `message` нет токена и тела запроса |
| 4 | Прочитать `frontend/index.html` | Есть `<meta name="referrer" content="same-origin">` |

### Notes
Токен из адресной строки **не удаляется** (`history.replaceState` не используется) — он нужен для тихого повторного входа и перезагрузки; это решение реализации, не дефект. Утечка в access-лог и историю браузера — риск R-2 (#32). Тега `referrer` автотест не проверяет — рекомендация tester'у.

---

## TC-84-003: Каждый заход — `POST /entry` с сохранённым языком; загрузка; отмена при размонтировании

**Priority:** Medium
**Type:** Functional (UI)
**AC:** FR-11; «Реализация» frontend п. 2, 4, 7
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#84 экран стола › передаёт при входе язык, сохранённый на устройстве»`, `::«#84 экран стола › пока вход идёт — состояние загрузки на языке устройства»`, `::«#84 экран стола › размонтирование до ответа отменяет запрос входа»`; `src/api/client.test.ts::«enterTable › передаёт lang: null, если выбора на устройстве нет»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `localStorage.aiw_guest_lang = az`, открыть экран | `enterTable(token, "az", signal)`; тексты на `az` |
| 2 | Без сохранённого языка | `lang: null` в теле |
| 3 | Вход ещё идёт | «Загрузка…» (язык устройства / браузера) |
| 4 | Размонтировать до ответа | `AbortSignal.aborted = true` |

### Notes
- Экран не пробует сначала `GET /session`: каждая загрузка — `POST /entry` (идемпотентно, ADR-9.1). Security LOW: общий лимит 30/мин на IP Wi-Fi заведения расходуется каждой перезагрузкой — в #13 сначала `GET /session`, лимит по столу — #26/#22.
- В dev под StrictMode два почти одновременных `POST /entry` (первый отменяется) — **не дефект**, в prod-сборке запрос один.

---

## TC-84-004: Ручной — вёрстка экрана стола, ошибки и переключателя на ширине 360 px

**Priority:** Medium
**Type:** UI (Ручной)
**AC:** AC-10, AC-11, AC-12; ТЗ NFR-2
**E2E Automated:** No
**Автоматизация:** Ручной.
**Статус прогона:** НЕ ВЫПОЛНЕН

### Preconditions
- `npm run build`, backend `uv run python -m app` (dev, сид); Chrome DevTools, режим устройства 360×640 (и 360×800), DPR 3; плюс реальный телефон, если есть.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть `/t/{dev_token(1)}` на RU и AZ | Название заведения и стола видны целиком или переносятся; нет горизонтальной прокрутки; переключатель AZ/RU помещается в строку, кнопки ≥ 44×44 px |
| 2 | Заведение/стол с длинным названием (≥ 40 символов) | Перенос без выхода за край |
| 3 | `/t/AAAAAAAAAAAAAAAAAAAAAA` (неизвестный токен) на RU и AZ (AZ-тексты длиннее) | Сообщение «QR-код недействителен…» читается целиком, без обрезки |
| 4 | Отключённый стол; ошибка сети (остановить backend) — кнопка «Повторить»; закрытый визит — «Начать заново» | Текст и кнопка видны без прокрутки, кнопка нажимается пальцем |
| 5 | Ошибка смены языка (остановить backend и нажать AZ) | Сообщение «Не удалось сменить язык…» не ломает раскладку |
| 6 | Повернуть экран (640×360) | Раскладка не ломается |

---

## TC-85-001: Экран ошибки `qr_invalid` на языке браузера (AZ/RU, иначе AZ), без кода и токена (AC-11)

**Priority:** Critical
**Type:** Functional / Security (UI)
**AC:** AC-11; FR-11, R-Q2
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#85 экран ошибки › 404 qr_invalid, браузер %s → «%s»»` (`ru-RU`, `az-AZ`, `en-US`); `src/guest/i18n.test.ts::«langFromTag — язык экрана по тегу браузера (R-Q2) › %j → %s»`, `::«browserLang › берёт navigator.language»`, `::«browserLang › браузер не az/ru → az»`, `::«browserLang › без navigator → az»`, `::«translate › тексты ошибок RU — по решению пользователя ADR-9.6»`; `src/guest/errors.test.ts::«entryErrorKind — ошибка входа → экран (FR-11 spec #9) › %o → %s»`; `src/api/client.test.ts::«enterTable › ответ %i {detail: {code: %s}} → ApiError с кодом»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Браузер `ru-RU`, вход → 404 `qr_invalid` | «QR-код недействителен, обратитесь к официанту»; кнопок нет |
| 2 | Браузер `az-AZ` | «QR-kod etibarsızdır, ofisianta müraciət edin» |
| 3 | Браузер `en-US` | Азербайджанский текст (R-Q2) |
| 4 | Проверить экран | Нет `qr_invalid`, `404`, `ApiError`, токена |

---

## TC-85-002: 422 входа (токен не прошёл валидацию тела) показывается как `qr_invalid` (E-4)

**Priority:** High
**Type:** Negative (UI)
**AC:** E-4, AC-11; «Реализация» frontend п. 3
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#85 экран ошибки › 422 валидации токена → как недействительный QR»`; `src/guest/errors.test.ts::«entryErrorKind — ошибка входа → экран (FR-11 spec #9) › %o → %s»` (422 без кода → `qr_invalid`, 422 `lang_not_supported` → `unavailable`); `src/api/client.test.ts::«enterTable › %s → ApiError без кода»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть `/t/` + 200 символов, вход → 422 без `code` | «QR-код недействителен…» |

---

## TC-85-003: `table_inactive` и `rate_limited` — тексты без кнопки и автоповтора (E-5, E-18)

**Priority:** High
**Type:** Functional (UI)
**AC:** E-5, E-18; FR-11, ADR-9.6
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#85 экран ошибки › 403 table_inactive»`, `::«#85 экран ошибки › 429 rate_limited без кнопки и без автоповтора»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вход → 403 `table_inactive` | «Стол временно не обслуживается, обратитесь к официанту»; кнопок нет |
| 2 | Вход → 429 `rate_limited` | «Слишком много попыток, повторите через минуту»; кнопок нет; вход вызван 1 раз |

---

## TC-85-004: Сеть, 5xx, 503 `try_again` — «Сервис временно недоступен» и «Повторить» (E-15)

**Priority:** High
**Type:** Negative (UI)
**AC:** E-15; FR-11
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#85 экран ошибки › %s → «Сервис временно недоступен», «Повторить» входит заново»` (503, 500, сеть), `::«#85 экран ошибки › кнопка «Повторить» на языке браузера (az)»`; `src/api/client.test.ts::«enterTable › тело ошибки не JSON → ApiError без кода»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Вход → 503 / 500 / `TypeError: Failed to fetch` | «Сервис временно недоступен», кнопка «Повторить»; автоповтора нет |
| 2 | Нажать «Повторить» (сервер ответил 200) | Экран стола; вход вызван второй раз |
| 3 | Браузер `az` | «Xidmət müvəqqəti olaraq əlçatan deyil», «Yenidən cəhd et» |

---

## TC-85-005: `visit_closed` — «Визит завершён» и вход только по «Начать заново»; `guest_session_*` — тихий повторный вход

**Priority:** High
**Type:** Functional (UI)
**AC:** E-7, FR-6, FR-11
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#86 переключатель языка › 401 visit_closed — «Визит завершён», новый вход только по кнопке «Начать заново»»`, `::«#86 переключатель языка › 401 %s — тихий повторный вход по токену с новым языком»` (`guest_session_required`, `guest_session_invalid`), `::«#86 переключатель языка › тихий повторный вход отклонён (стол отключён) — экран ошибки»`, `::«#86 переключатель языка › тихий повторный вход без сети — язык прежний, сообщение об ошибке»`; `src/guest/errors.test.ts::«needsSilentReentry › %o → %s»`, `::«isVisitClosed › %o → %s»`; `src/api/client.test.ts::«getGuestSession › 401 visit_closed → ApiError с кодом»`, `::«setGuestLang › ошибка %s → ApiError с кодом»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Смена языка → 401 `visit_closed` | «Визит завершён», кнопка «Начать заново»; повторного входа нет |
| 2 | Нажать «Начать заново» | `POST /entry`, экран стола (новый визит) |
| 3 | Смена языка → 401 `guest_session_required`/`guest_session_invalid` | Тихий `POST /entry` с выбранным языком; экран на `az`, выбор сохранён |
| 4 | Тихий вход → 403 `table_inactive` | Экран ошибки «Стол временно не обслуживается» |
| 5 | Тихий вход → сеть | Язык прежний, сообщение «Не удалось сменить язык…» |

---

## TC-85-006: Язык экрана ошибки входа — язык браузера даже при сохранённом выборе на устройстве (R-Q2) — Открытый вопрос

**Priority:** Medium
**Type:** Functional (UI, фиксация поведения)
**AC:** AC-11, R-Q2; «Реализация» frontend п. 5
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#85 экран ошибки › язык ошибки — браузера, даже если на устройстве выбран другой (R-Q2)»`, `::«#85 экран ошибки › браузер %s, на устройстве %s: ошибка %s на языке браузера»` (`en-US`/`ru` → `qr_invalid` AZ; `tr-TR`/`ru` → 503 AZ; `ru-RU`/`az` → `table_inactive` RU; G5, tester).
**Статус прогона:** PASS (текущее поведение — открытый вопрос)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Браузер `en-US`, `localStorage.aiw_guest_lang = ru`, вход → 404 | Текст на **азербайджанском** (язык браузера, иначе `az`); сохранённый `ru` не учитывается |
| 2 | Браузер `ru-RU`, сохранён `az`, вход → 403 | Текст на русском |
| 3 | Проверить `localStorage` и запрос | Значение не изменено; при входе передан сохранённый язык |

### Notes
**Открытый вопрос, не дефект.** Реализация буквально следует R-Q2 («язык браузера, иначе az»), хотя на этом же устройстве гость ранее явно выбрал язык, а экран загрузки показывается на сохранённом языке. Пользователь не решил, должен ли сохранённый выбор иметь приоритет на экране ошибки входа. При изменении решения TC и тесты меняются.

---

## TC-86-001: Переключатель меняет тексты сразу, вызывает API и сохраняет выбор (AC-12)

**Priority:** Critical
**Type:** Functional (UI)
**AC:** AC-12; FR-11, FR-9
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#86 переключатель языка › меняет тексты сразу, вызывает API и сохраняет выбор на устройстве»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Экран на `ru` (кнопка RU `aria-pressed=true`); нажать AZ | `setGuestLang("az")`; пока запрос идёт, кнопки неактивны, второго запроса нет |
| 2 | Ответ 200 | «Masanız», «Xoş gəlmisiniz!», AZ `aria-pressed=true`; `localStorage.aiw_guest_lang = az`; `<html lang="az">`; перезагрузки и повторного входа нет |

---

## TC-86-002: Выбор языка сохраняется после перезагрузки (AC-12)

**Priority:** High
**Type:** Functional (UI)
**AC:** AC-12; E-2
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#86 переключатель языка › выбор остаётся после перезагрузки: следующий вход передаёт его серверу»`; `src/guest/langStorage.test.ts::«язык устройства в localStorage › записанный язык читается обратно»`; сервер — TC-83-001, TC-76-003.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Выбрать AZ, размонтировать, открыть снова | Следующий `POST /entry` с `lang = az`, экран на AZ |

---

## TC-86-003: Один язык у заведения — переключателя нет; языки заведения в его порядке (E-13)

**Priority:** High
**Type:** Functional (UI)
**AC:** E-13; FR-11
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#86 переключатель языка › заведение с одним языком — переключатель не показывается (E-13)»`, `::«#86 переключатель языка › показывает только языки заведения в его порядке»`, `::«#86 переключатель языка › нажатие на текущий язык ничего не делает»`; сервер — `tests/db/test_guest_entry.py::test_change_lang_not_supported_by_tenant` (вход с `lang=az` в заведение `["ru"]` — `ru`).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Заведение `["ru"]` | Переключателя нет; язык `ru` |
| 2 | Заведение `["ru","az"]` | Кнопки в порядке RU, AZ |
| 3 | Нажать текущий язык | API не вызывается |

---

## TC-86-004: Ошибка смены языка — язык прежний, понятное сообщение, повторное нажатие работает

**Priority:** High
**Type:** Negative (UI)
**AC:** AC-12, E-12; FR-11
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/GuestScreen.test.tsx::«#86 переключатель языка › ошибка %s — язык прежний, понятное сообщение без подробностей»` (сеть, 503, 422 `lang_not_supported`, 422 без кода), `::«#86 переключатель языка › после ошибки повторное нажатие снимает сообщение и меняет язык»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Смена на AZ → сеть / 503 / 422 | «Не удалось сменить язык, попробуйте ещё раз.»; тексты на RU; RU нажата; AZ доступна; `localStorage` не изменён; нет `422`, `503`, кода; повторного входа нет |
| 2 | Нажать AZ снова (успех) | Сообщение исчезло, экран на AZ |

---

## TC-86-005: `localStorage` недоступен или содержит постороннее значение — без исключений

**Priority:** Medium
**Type:** Negative
**AC:** FR-11 («localStorage с try/catch»)
**E2E Automated:** No
**Автоматизация:** Авто — `src/guest/langStorage.test.ts::«язык устройства в localStorage › пусто → null»`, `::«… › постороннее значение → null»`, `::«… › чтение из недоступного хранилища → null без исключения»`, `::«… › запись в недоступное хранилище не бросает исключение»`; `src/guest/i18n.test.ts::«isGuestLang › %j → %s»`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Хранилище бросает при чтении/записи | `null` / без исключения; экран работает |
| 2 | `aiw_guest_lang = "en"` | `null` (в запрос входа не передаётся) |

---

## TC-86-006: Ручной — проверка азербайджанских текстов экрана гостя носителем языка (AI-6)

**Priority:** High
**Type:** Localization (Ручной)
**AC:** ТЗ AI-6; FR-11; AC-10…AC-12
**E2E Automated:** No
**Автоматизация:** Ручной. Наличие и различие ключей на обоих языках — Авто `src/guest/i18n.test.ts::«translate › ключ %s есть на обоих языках и тексты различаются»`.
**Статус прогона:** НЕ ВЫПОЛНЕН

### Preconditions
- Носитель азербайджанского языка; словарь `frontend/src/guest/i18n.ts` (объект `az`) и запущенный экран (dev, сид).

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить тексты экрана стола: «Yüklənir…», «Xoş gəlmisiniz!», «Masanız», «Kabinəniz», «Tezliklə burada menyu və ofisiantla çat olacaq.», «Dil», «Azərbaycan dili» | Грамотно, естественно, вежливая форма обращения |
| 2 | Тексты ошибок: «QR-kod etibarsızdır, ofisianta müraciət edin», «Masa müvəqqəti olaraq xidmət göstərmir, ofisianta müraciət edin», «Həddindən çox cəhd edildi, bir dəqiqədən sonra yenidən cəhd edin», «Ziyarət başa çatıb», «Xidmət müvəqqəti olaraq əlçatan deyil» | Смысл совпадает с RU; термины («ofisiant», «masa», «kabinə») привычны гостям заведения |
| 3 | Кнопки и сообщения: «Yenidən başla», «Yenidən cəhd et», «Dili dəyişmək alınmadı, yenidən cəhd edin.» | Понятны, умещаются на кнопке (см. TC-84-004) |
| 4 | Особо: «Ziyarət başa çatıb» как перевод «Визит завершён» | Носитель подтверждает или предлагает замену (возможно, точнее про посещение/обслуживание стола) |
| 5 | Зафиксировать правки | Список замен передаётся developer; после правки — повтор шага 1–3 |

---

## Related TCs
- TC-41-002 (маршрут `/t/:token`, #41) — заглушка `GuestPage` заменена экраном гостя; маршрут проверяется TC-84-001 (`App.test.tsx`).
- TC-41-004 (PWA, Service Worker) — исключение `/api` из `navigateFallback` используется гостевым API: TC-75-005.
- TC-42-001 (SPA fallback) — `/t/{token}` отдаёт `index.html`, визит не открывается: TC-75-003.
- TC-39-004 / TC-40-001 (RateLimiter single/scaled) — используется лимитом входа: TC-77-004, TC-77-005.
- TC-60-*, TC-71-* (демо-данные в prod) — дополнены отказом во входе по демо-токенам: TC-78-001…TC-78-003.
- TC-73-013 (`describe_error`) — новый вызывающий — `GuestRoute` (503 `try_again`): TC-75-004.

## Сводка

Всего 57 TC: авто 54 (из них частично статические — TC-75-006, TC-84-002), ручные 3 (TC-75-007, TC-84-004, TC-86-006 — НЕ ВЫПОЛНЕН, G5 не блокируют). Открытые вопросы: Q-4 / E-20 (TC-80-007, фиксация поведения), язык экрана ошибки при сохранённом выборе (TC-85-006), Q-1 (#19/#21, на TC не влияет).

### AC и граничные случаи → TC

| AC / E | Story | TC |
|--------|-------|----|
| AC-1 | #75 | TC-75-001, TC-75-002 |
| AC-2 | #76 | TC-76-001 |
| AC-3 | #77 | TC-77-001, TC-77-002 |
| AC-4 | #78 | TC-78-001 |
| AC-5 | #79 | TC-79-001, TC-79-003 |
| AC-6 | #80 | TC-80-001, TC-80-002 |
| AC-7 | #81 | TC-81-001 |
| AC-8 | #82 | TC-82-001 |
| AC-9 | #83 | TC-83-001 |
| AC-10 | #84 | TC-84-001, TC-84-004 (ручной) |
| AC-11 | #85 | TC-85-001, TC-85-006, TC-84-004 (ручной) |
| AC-12 | #86 | TC-86-001, TC-86-002, TC-84-004 (ручной), TC-86-006 (ручной) |
| E-1 | #76 | TC-76-002 |
| E-2 | #76, #82 | TC-76-003, TC-82-003, TC-86-002 |
| E-3 | #75, #80 | TC-80-008 |
| E-4 | #77 | TC-77-002, TC-85-002, TC-75-005 |
| E-5 | #77, #80 | TC-77-003, TC-80-006, TC-85-003 |
| E-6 | #79, #80 | TC-79-002 |
| E-7 | #75, #81 | TC-81-002, TC-85-005 |
| E-8 | #81 | TC-81-003 |
| E-9 | #78 | TC-78-002 |
| E-10 | #78, #80 | TC-78-003 |
| E-11 | #82 | TC-82-002 |
| E-12 | #83 | TC-83-002, TC-86-004 |
| E-13 | #86 | TC-86-003 |
| E-14 | #80 | TC-80-002 |
| E-14a | #80 | TC-80-003 |
| E-15 | #75, #85 | TC-75-004, TC-85-004 |
| E-16 | #75 | TC-75-003 |
| E-17 | #79 | TC-79-004 |
| E-18 | #77, #85 | TC-77-004, TC-85-003 |
| E-19 | #77 | TC-77-005 |
| E-20 | #80 | TC-80-007 (фиксация поведения, Q-4) |
| NFR-1 | #79 | TC-79-005 |
| NFR-2 | #75, #80 | TC-75-002, TC-80-001, TC-80-003, TC-79-005 |
| NFR-3 | #75 | TC-75-006, TC-84-002 |
| NFR-4 | #77 | TC-77-004, TC-77-005 |
| NFR-5 | #75, #83 | TC-75-005, TC-83-003, TC-80-004 |
| NFR-6 | #75 | TC-75-007 (ручной) |
| NFR-7 | #80 | TC-80-005 |
| NFR-8 | #80 | TC-80-004 |
| AI-6 | #86 | TC-86-006 (ручной) |
