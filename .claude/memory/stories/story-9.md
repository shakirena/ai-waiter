# Story #9: Вход гостя по QR-токену, визит, язык (stories #75–#86)

*Каждый агент дописывает свой раздел — не перезаписывает чужие.*

**Spec:** docs/specs/feature-9-guest-qr-entry.md · **Arch:** docs/arch/feature-9-guest-qr-entry.md · DEC-015, DEC-016

---

## 💻 Реализация backend (developer, #75–#83)

**Branch:** dev/9-backend (от a1ef76b, ветка feature/9-guest-qr-entry; вливает dev-lead)

**Что сделано**
- `app/guest/*` — сервисы без FastAPI: `tokens` (генерация `token_urlsafe(24)`, `fullmatch` формата, перевыпуск в SAVEPOINT с повтором при коллизии `uq_tables_qr_token`), `visits` (get-or-open: `UPDATE … SET last_activity_at RETURNING` → `INSERT … ON CONFLICT DO NOTHING RETURNING`, до 3 попыток; `close_visit`, `touch_visit`, `set_visit_lang` — все с `tenant_id` и `status='open'`), `lang` (RFC 4647/9110, q-value, обрезка 512), `session` (HMAC-SHA256 `v1.<payload>.<sig>`, строгий разбор полей, TTL и допуск часов 60 с), `entry` (`enter_table`, `load_guest_context` — один SELECT visits JOIN tables JOIN tenants по tid/vid/tbl, `change_lang`).
- `app/api/guest.py` — роутер `/api/guest/v1` с классом маршрута `GuestRoute`: `Cache-Control: no-store` на всех ответах (в том числе 401 зависимости и 422 валидации) и 503 `try_again` при ошибках соединения с БД (`OperationalError`, `InterfaceError`, пул `TimeoutError`, `DBAPIError.connection_invalidated`, `OSError` — asyncpg бросает `ConnectionRefusedError`/`gaierror` без обёртки), лог через `Database.describe_error`. Лимит входа по IP — зависимость маршрута (выполняется до валидации тела: считаются все попытки), только через `RateLimiter`, fail-open с WARNING (имена классов по цепочке).
- `app/api/guest_auth.py` — `current_guest_view`/`current_guest`, `set_guest_cookie`, `client_ip_key` (IPv6 → /64 по числовому значению, зона отбрасывается).
- `app/main.py` — `app.state.guest_session_codec`, `include_router(guest.router)`.
- `app/core/config.py` — `GUEST_SESSION_SECRET` обязателен при prod/scaled, короче 32 символов — ошибка в любом режиме (текст без значения).
- Тесты: `tests/conftest.py::make_settings` по умолчанию передаёт `TEST_GUEST_SESSION_SECRET`; тест «секрета нет» передаёт `guest_session_secret=None`. Env-тесты prod/scaled (`test_config`, `test_container`, `test_menu_sync_cli`, `test_seed`) задают `GUEST_SESSION_SECRET` явно.

**Отклонения от arch / решения по ходу**
- `reissue_table_token` пишет `token_issued_at = clock_timestamp()`, а не `now()`: `now()` — время начала транзакции, и перевыпуск в транзакции, где стол создан или уже перевыпускался, не изменил бы `tia` (сессии остались бы действительны).
- Шаг 1 get-or-open — один `UPDATE … RETURNING` вместо `SELECT` + `UPDATE`.
- `close_visit(..., staff_id=...)` при `closed_by != staff` — `ValueError`.
- `GuestSessionInvalidError` несёт причину (`not_found`/`table_inactive`/`token_reissued`/`demo`) — только для INFO-лога, в ответ не попадает. Отказы входа логирует `entry` (`code`, `reason`, `tenant_id`/`table_id` при наличии), 429 и 401 — HTTP-слой.
- У эндпоинтов явный `description` OpenAPI: docstring обработчиков (упоминают `reject_demo`) в схему не попадают (ADR-60.3 — не подсказывать про демо).
- `GuestRoute` обрабатывает `HTTPException`/`RequestValidationError` стандартными обработчиками FastAPI внутри маршрута, чтобы добавить `no-store`; глобальные обработчики исключений для `/api/guest` поэтому не вызываются.

**Новые файлы**
- backend/tests/test_guest_session.py, test_guest_tokens.py, test_guest_lang.py, test_guest_services.py, test_guest_api.py
- backend/tests/db/test_guest_entry.py

**Изменённые файлы**
- backend/app/api/errors.py, guest.py, guest_auth.py; backend/app/guest/entry.py, lang.py, session.py, tokens.py, visits.py
- backend/app/core/config.py, backend/app/main.py
- backend/tests/conftest.py, test_config.py, test_container.py, test_menu_sync_cli.py, test_seed.py
- README.md (scaled: `GUEST_SESSION_SECRET` и команда генерации)

**Build:** ruff check OK · ruff format OK · pytest 2013 passed, 3 skipped (scaled без REDIS_URL) · `-m "not db and not scaled"` 1696 passed

**Известные ограничения**
- Q-4 / E-20 не решался: повторное включение стола без перевыпуска оживляет прежние cookie (тест фиксирует поведение spec).
- Тело с битым JSON отклоняется FastAPI до зависимостей — такие попытки в лимит входа не попадают (все синтаксически корректные JSON-запросы считаются).
- `GUEST_SESSION_SECRET` в `deploy/docker-compose.yml` не помечен `${…:?}`: без него api/worker падают с `ConfigError` (README описывает).

## 🔒 Security Review

**Verdict:** PASS (2026-11-15), метка `security:passed` на #9 и #75–#86.
**Scope:** backend/app/guest/*, backend/app/api/{errors,guest_auth,guest}.py, backend/app/schemas/guest.py, main.py, core/config.py, .env.example, README.md; frontend/src/guest/*, src/api/{client,types}.ts, src/pages/GuestPage.tsx, index.html.
**Findings:** CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 2 · INFO 3.
- LOW: токен `/t/{token}` в access-логе и истории браузера (R-2, фильтр — #32).
- LOW: лимит 30 входов в минуту на IP общий для NAT заведения, а `/entry` вызывается при каждой загрузке страницы (#13: сначала `GET /session`; #26/#22: лимит по столу).
- INFO: широкий перехват `OSError` → 503 в `GuestRoute`; `GUEST_COOKIE_SECURE=false` допустим в prod; Q-4/E-20 — принятый риск (#27).
**Заметки:** HMAC и `compare_digest` до разбора JSON; `tid`+`vid`+`tbl` проверяются одним запросом; `tia` обрывает сессии после перевыпуска; демо-заведение в prod отвергается и при входе, и в `current_guest`; XFF принимается только от доверенных прокси.

## QA (G5)

**Verdict:** PASS (2026-11-15), коммит 60c0b3e. G5 Report: https://github.com/shakirena/ai-waiter/issues/9#issuecomment-7033891832.
**TC:** docs/test-cases/feature-9-guest-qr-entry.md — 57 TC (TC-75-001…TC-86-006): авто 54 PASS; ручные 3 не выполнены, переносятся в G6 — TC-75-007 (p95 входа, NFR-6), TC-84-004 (360 px), TC-86-006 (AZ-тексты, AI-6). Раздел #9 в docs/test-cases/traceability-tc.md.
**Тесты G5:** tests/db/test_guest_entry.py::test_http_spa_page_does_not_open_visit (E-16); GuestScreen.test.tsx — язык экрана ошибки при сохранённом выборе, describe «GuestScreen: смена токена без перемонтирования»; App.test.tsx — `waitFor` (был нестабилен).
**Прогон:** backend 2014 passed, 3 skipped, покрытие `app` 100% строк и ветвей (CI unit 1696 passed за 23 с, db 318 passed за 53 с); frontend 141 passed, строки 100%, ветви 99,19%.
**Открытые вопросы:** язык экрана ошибки входа при сохранённом выборе (сейчас язык браузера, R-Q2; TC-85-006); Q-4/E-20 → #27 (TC-80-007 фиксирует текущее поведение).
**Рекомендации по тестам:** логи NFR-3 через `caplog`; `<meta name="referrer">`; границы `GUEST_SESSION_TTL_HOURS`; FR-12 — `GET /session` не трогает `last_activity_at`; 503 на `PUT /session/lang`.
**Doc-sync после G5:** 2026-11-20 — docs/traceability.md, абзац G5 в arch «Реализация», active-sprint (Ready to Deploy (#9)).
