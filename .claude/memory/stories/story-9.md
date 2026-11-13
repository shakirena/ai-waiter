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
