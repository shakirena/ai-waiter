# Architecture: Feature #9 — Вход гостя по QR-токену, визит, язык

**Issue:** #9 · **ТЗ:** FR-1, FR-2, FR-14a; 6 NFR-4, NFR-5; 7 «Модель данных» (`tables`, `visits`); 13, вопрос 8
**Spec:** `docs/specs/feature-9-guest-qr-entry.md` (сверен с этим документом 2026-11-10; в технических деталях приоритет у arch, в поведении для гостя и scope — у spec)
**Опирается на:** `docs/arch/feature-7-data-model.md` (ADR-7.1, 7.3, 7.5 — `uq_visits_open_table`, ADR-7.9 — сессии БД), `docs/arch/feature-60-demo-data-guard.md` (риск 1 — демо-токены в prod), `docs/arch/feature-6-project-scaffold.md` (ADR-1 интерфейсы, ADR-3 SPA, доверие к прокси), DEC-006, DEC-007, DEC-013, DEC-014; вводит DEC-015 (формат ошибок), DEC-016 (гостевая сессия)

Гость сканирует QR и открывает `https://{домен}/t/{token}`. Это маршрут SPA: backend отдаёт `index.html`, страница гостя вызывает API входа. Сервер по токену находит заведение и стол, берёт открытый визит стола или открывает новый, определяет язык и выдаёт гостевую сессию — подписанную cookie, привязанную к визиту. Следующие гостевые API (#10 меню и корзина, #11 чат, #12 заказ) получают гостя через зависимость `current_guest`.

**Схема БД не меняется.** Новых таблиц, колонок, индексов и ревизий Alembic нет: хватает `tables.qr_token`/`token_issued_at`/`is_active` и `visits` с частичным уникальным индексом `uq_visits_open_table` (#7). Новые переменные окружения — четыре (раздел «Конфигурация»).

---

## Компоненты и слои

```
frontend/src/pages/GuestPage.tsx ──fetch──▶ /api/guest/v1/*        (app/api/guest.py, HTTP-слой)
                                              │  current_guest (app/api/guest_auth.py)
                                              │  RateLimiter (интерфейс, ADR-1)
                                              ▼
                                         app/guest/  (сервисы без FastAPI)
                                           entry.py    — сценарий входа (оркестрация)
                                           tokens.py   — генерация и перевыпуск QR-токена
                                           visits.py   — get-or-open / close визита
                                           session.py  — кодек подписанной cookie (HMAC)
                                           lang.py     — Accept-Language → az|ru
                                           errors.py   — доменные исключения
                                              ▼
                                         PostgreSQL: tenants, tables, visits
```

- `app/guest` не импортирует `fastapi`/`starlette`/`app.api` (как `app/menu_sync`, DEC-011). HTTP-коды, cookie и заголовки — только в `app/api`.
- Транзакцию фиксирует сервис (`entry.enter_table` — `await session.commit()`, DEC-007).
- Кодек сессии создаётся в `create_app` и лежит в `app.state.guest_session_codec`, как `demo_data_monitor`. `Container` не меняется: он хранит инфраструктуру режимов, а кодек от режима не зависит.

---

## ADR-9.1. Вход — `POST /api/guest/v1/entry` с токеном в теле; `/t/{token}` остаётся маршрутом SPA

**Контекст.** Issue формулирует критерий как «`GET /t/{token}` → заведение, стол, визит». `/t/{token}` — маршрут фронтенда: SPA fallback отдаёт `index.html` (ADR-3). Данные и сессию нужно выдавать отдельным API под зарезервированным префиксом `/api`.

**Решение.**
- `POST /api/guest/v1/entry`, тело `{"token": "...", "lang": "az" | "ru" | null}`.
- **POST, а не GET:** запрос меняет состояние (открывает визит, ставит cookie). Превью ссылок в мессенджерах, сканеры почты и prefetch браузера делают GET и не выполняют JS. Они не откроют фантомный визит, а GET-ответ можно закешировать — POST нет.
- **Токен в теле, а не в пути API.** Путь пишется в access-лог uvicorn/Caddy, тело — нет. Сам `/t/{token}` в access-логе остаётся (риск R-2).
- Версия `v1` в пути: PWA с `autoUpdate` может какое-то время работать со старой сборкой, а версия позволяет менять контракт без поломки открытых вкладок. Это повторяет `/integration/v1`.
- Повторный вход (перезагрузка страницы, второе устройство за столом) идемпотентен: возвращается тот же открытый визит.

**Альтернативы.** `GET /api/guest/v1/tables/{token}` + отдельный `POST /visits`: два запроса на слабом интернете (NFR-2), токен попадает в путь. Серверный рендер `/t/{token}` с `Set-Cookie`: ломает модель SPA и PWA и открывает визиты на превью ссылок.

**Последствия.** Фронтенд делает один запрос при загрузке `/t/{token}`. Префикс `/api` уже есть в `RESERVED_PREFIXES` и `BACKEND_PREFIXES`, их правка не нужна.

## ADR-9.2. Гостевая сессия — подписанная cookie без таблицы в БД

**Контекст.** Сессию нужно привязать к визиту и заведению. После закрытия визита она должна перестать действовать. Варианты: stateless-cookie с HMAC или таблица `guest_sessions`.

**Решение.** Stateless-cookie, подписанная HMAC-SHA256.
- **Формат значения:** `v1.<payload>.<sig>`, где `payload` — base64url (без `=`) компактного JSON, а `sig` — base64url от `HMAC-SHA256(secret, "v1." + payload)`. Подпись сверяется через `hmac.compare_digest`. Неизвестная версия, битый base64/JSON, неверная подпись, значение длиннее `MAX_SESSION_VALUE_LENGTH = 1024` или `iat` в будущем больше чем на 60 с (допуск расхождения часов) дают «сессии нет». `MIN_SECRET_LENGTH = 32` — байты ключа в кодеке и символы в `Settings` (секрет ASCII, `token_urlsafe`).
- **Поля payload (`GuestSessionClaims`):** `vid` (visit_id), `tid` (tenant_id), `tbl` (table_id), `tia` (`tables.token_issued_at`, целые микросекунды epoch), `lang`, `iat` (время выдачи, секунды epoch). Полей с личными данными нет (NFR-5).
- **Проверка на каждом запросе (`current_guest`):**
  1. подпись;
  2. `iat + GUEST_SESSION_TTL_HOURS > now`;
  3. **один** запрос в БД:
     ```sql
     SELECT … FROM visits v
       JOIN tables t ON t.tenant_id = v.tenant_id AND t.id = v.table_id
       JOIN tenants n ON n.id = v.tenant_id
      WHERE v.tenant_id = :tid AND v.id = :vid AND v.table_id = :tbl
     ```
     Строки нет (визит другого заведения или стола при верной подписи) — `guest_session_invalid`. Затем проверки по порядку: `v.status = 'open'` (иначе `visit_closed`), `t.is_active` и `t.token_issued_at = :tia` (иначе `guest_session_invalid`). При `APP_ENV=prod` `tid ≠ DEMO_TENANT_ID` (ADR-9.6), проверяется до запроса в БД.
     Это и реализует решение пользователя по Q-3 spec (R-Q3): перевыпуск токена и отключение стола обрывают действующие сессии на следующем же запросе, без кэша процесса.
- **Чем сессия становится недействительной:** закрытием визита (FR-14a: официант, касса, таймаут), перевыпуском токена стола (FR-1, `tia` не совпадёт), отключением стола, истечением TTL, сменой `GUEST_SESSION_SECRET`.
- **Cookie** (`GUEST_COOKIE_NAME = "aiw_guest"`):

  | Атрибут | Значение | Почему |
  |---|---|---|
  | `HttpOnly` | да | JS гостя её не читает (XSS не крадёт сессию) |
  | `Secure` | `GUEST_COOKIE_SECURE`; по умолчанию `true` при `APP_ENV=prod` | в dev — http://localhost |
  | `SameSite` | `Strict` | cookie нужна только `fetch` с нашей же страницы (same-site), переходы с чужих сайтов её не требуют; это сильнее защищает от CSRF, чем `Lax` |
  | `Path` | `/api/guest/` | не уходит в `/api/staff`, `/integration`, на статику |
  | `Max-Age` | `GUEST_SESSION_TTL_HOURS * 3600` | дублирует серверную проверку `iat` (браузеру не доверяем) |
  | `Domain` | не задаётся | host-only cookie |

  Префикс `__Host-` не используется: он требует `Path=/` и `Secure` даже в dev.
- **Одна cookie на устройство.** Сканирование другого стола перезаписывает её (последний вход выигрывает).
- **Секрет:** `GUEST_SESSION_SECRET` (≥ 32 символа). Обязателен при `APP_ENV=prod` и при `APP_MODE=scaled` (несколько процессов api должны иметь общий ключ). В `single` вне prod его можно не задавать: кодек берёт случайный ключ процесса (`secrets.token_bytes(32)`) и пишет WARNING. Сессии тогда не переживают перезапуск, но гость просто входит заново по токену из URL.

**Альтернативы.**
- Таблица `guest_sessions` (id, tenant_id, visit_id, lang, last_seen_at). Плюсы: точечный отзыв одного устройства и учёт устройств за столом. Минусы: миграция и правки тестов по DEC-009/DEC-010, запись в БД на каждый вход, очистка в #23, а запрос на каждый гостевой вызов нужен всё равно. Точечный отзыв устройства ТЗ не требует, а все нужные отзывы (визит, токен, стол) дают поля, проверяемые по БД. Отвергнуто для этапа 1; переход возможен без смены контракта API (cookie остаётся непрозрачной строкой).
- `itsdangerous`/JWT — лишняя зависимость ради 30 строк; JWT добавляет опасную гибкость (`alg`).
- Токен в `localStorage` + заголовок `Authorization` — доступен XSS.

**Последствия.** Новых таблиц нет. Каждый гостевой API-вызов делает один запрос по PK визита, и он нужен ему в любом случае (tenant_id, table_id, price_tier для #10). Смена секрета разлогинивает всех гостей; ротация двумя ключами — открытый вопрос 3.

## ADR-9.3. Открытие визита: get-or-open через `uq_visits_open_table` и `ON CONFLICT DO NOTHING`

**Контекст.** Два устройства за столом сканируют QR одновременно. Открытый визит у стола должен быть один (ADR-7.5); БД гарантирует это частичным уникальным индексом `uq_visits_open_table (table_id) WHERE status = 'open'`.

**Решение.** `visits.get_or_open_visit(session, *, tenant_id, table_id, lang) -> (Visit, created: bool)`:
1. `SELECT … FROM visits WHERE tenant_id = :t AND table_id = :tb AND status = 'open'` (частый путь: визит уже есть). Найден — `UPDATE visits SET last_activity_at = now()` и вернуть `created=False`.
2. Иначе `INSERT INTO visits (id, tenant_id, table_id, lang) VALUES (new_id(), …) ON CONFLICT (table_id) WHERE status = 'open' DO NOTHING RETURNING *` — `postgresql.insert(...).on_conflict_do_nothing(index_elements=["table_id"], index_where=text(OPEN_VISIT_PREDICATE))`. Строка вернулась — `created=True`.
3. Пусто (визит открыл параллельный запрос) — повторить шаг 1. Если визит успели закрыть между шагами, цикл повторяется, не больше `OPEN_VISIT_ATTEMPTS = 3` раз, затем `VisitOpenConflictError` (→ 503 `try_again`; практически недостижимо).

`ON CONFLICT DO NOTHING` не прерывает транзакцию, поэтому SAVEPOINT и перехват `IntegrityError` не нужны. В обоих режимах код один — это PostgreSQL, а не EventBus.

**Кто открывает визит (вопрос 8 ТЗ).** Допущение этапа 1: визит открывает первое сканирование. Открытие и закрытие визита официантом (FR-14a) — эндпоинты панели после #19 (авторизация персонала), вне scope. Новое сканирование после закрытия открывает новый визит: старый не находится по `status='open'`.

**Закрытие.** В #9 есть сервисная функция `visits.close_visit(session, *, tenant_id, visit_id, closed_by, staff_id=None) -> bool` — `UPDATE … SET status='closed', closed_at=now(), closed_by=…, closed_by_staff_id=… WHERE tenant_id, id, status='open'`. Она возвращает, закрыт ли визит этим вызовом; commit делает вызывающий. Эндпоинта нет. Функция нужна тестам #9 (закрытый визит → новая сессия и новый визит) и будущим потребителям: #21 (официант), #17 (`order_status` кассы), #23 (`visit_idle_close_hours`). Событие EventBus о закрытии визита появится вместе с первым подписчиком (панель #20), не в #9.

**Альтернативы.** `SELECT … FOR UPDATE` строки стола — сериализует входы за столом и держит блокировку дольше. Advisory lock — лишний механизм при уже существующем уникальном индексе. Перехват `IntegrityError` с SAVEPOINT — сложнее и шумит в логах PostgreSQL.

## ADR-9.4. Язык: у каждого устройства свой, хранится в сессии; `visits.lang` — последний выбранный за столом

**Контекст.** FR-2: язык определяется по браузеру, его можно выбрать и сменить в любой момент. Бот отвечает на языке гостя; AI-6 — на языке последнего сообщения. За одним столом могут сидеть гость с AZ и гость с RU, а диалог и корзина визита общие.

**Решение.**
- **Язык интерфейса устройства — `lang` в payload cookie.** Каждое устройство независимо. Смена — `PUT /api/guest/v1/session/lang`: cookie переподписывается с новым `lang`; `iat` не меняется (смена языка не продлевает сессию), `Max-Age` новой cookie — оставшийся срок (`codec.remaining_seconds(claims)`).
- **`visits.lang`** (NOT NULL, есть с #7) = язык устройства, открывшего визит; при каждой явной смене языка обновляется (последний выбор за столом). Его читает сервер, когда контекста устройства нет: тексты фоновых задач, сводка для официанта. Чат #11 берёт язык из `current_guest.lang` запроса (и AI-6 — по последнему сообщению), а не из `visits.lang`.
- **Порядок выбора при входе** (`lang.resolve_entry_lang`):
  1. `lang` из тела запроса (фронтенд передаёт явный выбор, сохранённый на устройстве в `localStorage`), если он входит в `tenants.languages`;
  2. `lang` из действующей cookie того же стола (`claims.tid` и `claims.tbl` совпадают с найденным столом; визит до `get_or_open_visit` ещё неизвестен, а язык нужен уже для INSERT);
  3. `Accept-Language`: по убыванию `q` первый тег, основной подтег которого (`az-Latn-AZ` → `az`, `ru-RU` → `ru`) входит в `tenants.languages`; `q=0` пропускается; разбор устойчив к мусору и ограничен длиной заголовка 512 символов;
  4. `tenants.languages[0]` — язык заведения по умолчанию.
- Ответ входа содержит `lang` и `languages`. Фронтенд показывает переключатель AZ/RU с выбранным определённым языком, если у заведения больше одного языка (при одном — не показывается, spec E-13). Отдельного блокирующего экрана выбора нет: «выбор при первом входе» — это видимый переключатель (решено в spec FR-7, FR-11).
- **`visits.last_activity_at`** обновляется при входе (создание и присоединение) и при смене языка; `GET /session` его не обновляет (чтение не продлевает визит). Гостевые действия #10–#12 вызывают `visits.touch_visit` (spec FR-12; нужно автозакрытию #23).
- `PUT /session/lang` с языком вне `tenants.languages` — 422 `lang_not_supported`.

**Альтернативы.** Только `visits.lang`, общий для стола: смена языка одним гостем переключила бы интерфейс соседу — противоречит FR-2 («язык гостя»). Таблица сессий для языка — см. ADR-9.2. Язык только в `localStorage` без сервера: сервер (#11) не знал бы язык устройства, клиенту пришлось бы передавать его в каждом запросе.

## ADR-9.5. QR-токен: `secrets.token_urlsafe(24)`, перевыпуск — UPDATE строки стола

**Решение.**
- `tokens.generate_qr_token() -> str` — `secrets.token_urlsafe(QR_TOKEN_BYTES)`, `QR_TOKEN_BYTES = 24`: 192 бита, 32 символа base64url. Соответствует `QR_TOKEN_PATTERN` (`^[A-Za-z0-9_-]{22,64}$`) и требованию ≥ 128 бит.
- `tokens.reissue_table_token(session, *, tenant_id, table_id) -> Table` — `UPDATE tables SET qr_token = :new, token_issued_at = now() WHERE tenant_id = :t AND id = :id RETURNING *`. Стола нет — `TableNotFoundError`. Коллизия по `uq_tables_qr_token` (практически невозможна) — повтор с новым токеном внутри SAVEPOINT, до 3 раз. Commit делает вызывающий (#27 — эндпоинт админки). Старый токен перестаёт находиться сразу; сессии, выданные по старому токену, отвергаются по `tia` (ADR-9.2).
- «Отзыв» в смысле FR-1 и есть перевыпуск: история токенов не хранится, старый токен после UPDATE неизвестен. Временное отключение стола — `is_active = false` (#27/коннектор `PUT /tables` #16).
- Новые столы (#16, #27) получают токен только из `generate_qr_token`. Детерминированные `dev_token()` сида — только для dev (ADR-9.6).
- Сравнение токена — поиск по уникальному индексу. Перед запросом в БД токен проверяется `QR_TOKEN_PATTERN`; несоответствие — тот же ответ `qr_invalid` без обращения к БД.

## ADR-9.6. Ошибки входа без утечки; демо-заведение в prod — как неизвестный токен

**Решение.**
- Неизвестный, отозванный (перевыпущенный), синтаксически неверный токен, а при `APP_ENV=prod` — токен стола заведения `DEMO_TENANT_ID` (замечание #71, DEC-014): **404 `qr_invalid`**. Ответы одинаковы по коду, телу и заголовкам. Название заведения, стола и факт существования токена не раскрываются.
- Токен существует, но `tables.is_active = false`: **403 `table_inactive`**, без данных заведения. Гость держит в руках настоящий QR этого заведения, поэтому раскрывать «стол временно не обслуживается» безопасно и понятнее, чем «неверный код». Название заведения не возвращается, чтобы ответ не служил оракулом по украденным токенам.
- Демо-проверка — сравнение `tenant_id` с константой `app.seed.data.DEMO_TENANT_ID` в `entry.enter_table` и в `current_guest`; запроса в БД она не добавляет. Флаг передаётся в сервис как `reject_demo: bool = settings.app_env is AppEnv.PROD`. `app/guest` не читает `Settings` сам.
- **Формат ошибки гостевого API (новый, общий для `/api/*`, DEC-015):** `{"detail": {"code": "<snake_case>"}}` — совместим с форматом FastAPI `{"detail": …}`. 422 валидации тела остаётся стандартным `{"detail": [...]}` (массив). Текст ошибки фронтенд локализует по `code`: язык сервер в ошибку не вкладывает, при неверном токене он неизвестен. Помощник — `app/api/errors.py: api_error(status, code, headers=None) -> HTTPException`.

## ADR-9.7. Rate-limit входа по IP — в scope, через `RateLimiter`

**Контекст.** NFR-4 требует rate-limit по IP и столу. #26 отвечает за лимиты сообщений ИИ (`msg_*`). Подобрать 192-битный токен перебором нельзя, но без лимита эндпоинт входа — дешёвый способ нагрузить БД и сканировать.

**Решение.** В #9 — лимит на `POST /api/guest/v1/entry` по IP клиента: `RateLimiter.hit(rate_key("guest_entry", "ip", <ip>), limit=GUEST_ENTRY_RATE_LIMIT, window=60 с)`. Считаются все попытки. Превышение — **429 `rate_limited`** с `Retry-After` (целые секунды, вверх). `GUEST_ENTRY_RATE_LIMIT=0` выключает лимит.
- Значение по умолчанию **30 в минуту**: гости одного заведения часто выходят через общий Wi-Fi/NAT (один IP), а вход — это одна загрузка страницы.
- IP — `request.client.host`. Он уже настоящий: `X-Forwarded-For` принимается только от доверенного прокси (single — loopback/cloudflared, scaled — подсеть `edge`, DEC-005). В `rate_key` двоеточие запрещено, поэтому адрес нормализуется функцией `client_ip_key(host)`: IPv4 — как есть; IPv6 — префикс /64 (`ipaddress.ip_network(f"{ip}/64", strict=False).network_address.exploded`) с заменой `:` на `-`; отсутствующий/нераспознанный адрес — `"unknown"`.
- Ошибка самого `RateLimiter` (Redis недоступен в scaled) **не блокирует вход** (fail-open): WARNING в лог с именами классов исключений и вход без лимита. Гость за столом важнее защиты от перебора невозможного токена.
- Лимит по столу и лимиты гостевых действий (#10–#12, сообщения) — в #26/#22.

## Последовательности

**Первый вход (визита нет)**
```
Гость → GET /t/{token}             → SPA index.html (Referrer-Policy: same-origin через <meta>)
SPA   → POST /api/guest/v1/entry {token, lang: localStorage|null}
API   : rate-limit по IP ─ превышен → 429 rate_limited
API   : codec.decode(cookie) → claims | None   (для шага 2 выбора языка)
entry : QR_TOKEN_PATTERN ─ нет → QrInvalidError
entry : SELECT tables JOIN tenants WHERE qr_token = :token
          нет | (reject_demo и tenant_id = DEMO_TENANT_ID) → QrInvalidError → 404 qr_invalid
          is_active = false → TableInactiveError → 403 table_inactive
entry : lang = resolve_entry_lang(body.lang, claims (если тот же стол), Accept-Language, tenant.languages)
visits: get_or_open_visit → INSERT … ON CONFLICT DO NOTHING → (visit, created=True)
entry : commit
API   : Set-Cookie aiw_guest=v1.<payload>.<sig>; Cache-Control: no-store
      → 200 GuestEntryResponse {tenant, table, visit{is_new: true}, lang}
```

**Повторный вход / второе устройство.** То же самое; на шаге visits найден открытый визит, `last_activity_at = now()`, `is_new = false`. Язык второго устройства определяется по его браузеру. Оба устройства в одном визите.

**Гонка двух сканирований.** Оба запроса не находят визит → оба делают INSERT; первый вставляет строку, второй ждёт на уникальном индексе, после commit первого получает DO NOTHING (пустой RETURNING) → повторный SELECT находит визит первого. Итог — один визит.

**Визит закрыт (официант/касса/таймаут).** Следующий вызов гостевого API: `current_guest` → `visit.status = 'closed'` → 401 `visit_closed`. Фронтенд показывает «Визит завершён» и кнопку «Начать заново» и **не** входит повторно сам: иначе забытая вкладка открывала бы фантомные визиты. Кнопка → `POST /entry` → новый визит.

**Смена языка.** `PUT /api/guest/v1/session/lang {lang}` → `current_guest` → `lang` в `tenant.languages`? → `UPDATE visits SET lang, last_activity_at` → commit → новая cookie → 200 `GuestSessionResponse`.

**Перевыпуск токена (#27).** `reissue_table_token` → commit. Старый QR → 404 `qr_invalid`; сессии устройств за столом → 401 `guest_session_invalid` (по `tia`). Гостям нужно отсканировать новый QR.

## ERD

Без изменений схемы. Используются:

```
tenants  id, name, currency, languages text[] (languages[0] — язык по умолчанию)
tables   id, tenant_id, hall_id, name, type, price_tier, qr_token UNIQUE, token_issued_at, is_active
visits   id, tenant_id, table_id, status, lang, opened_at, last_activity_at, closed_at, closed_by,
         closed_by_staff_id; uq_visits_open_table (table_id) WHERE status = 'open'
```

Миграция: нет.

## API Contracts

Все ответы — `application/json`, `Cache-Control: no-store`. Время — ISO 8601 с зоной. Тело ошибки — `{"detail": {"code": "…"}}` (ADR-9.6).

- **`no-store` на всех ответах префикса**, включая стандартную 422 FastAPI и 401 из зависимости: developer ставит заголовок одним middleware (или `APIRoute`-подклассом роутера) для `/api/guest/`, а не только в обработчиках.
- **БД недоступна** (ошибки соединения SQLAlchemy/драйвера: `OperationalError`, `InterfaceError`, `DBAPIError` с `connection_invalidated`, `TimeoutError` пула) на любом гостевом запросе → **503 `try_again`** без деталей; в лог — WARNING с `describe_error` (#73). Обработчик — в `app/api/guest.py` (exception handler роутера/обёртка), не глобальный для всего приложения. Прочие исключения — 500 по умолчанию.

| Method | Path | Кто | Request | Response | Ошибки |
|---|---|---|---|---|---|
| POST | `/api/guest/v1/entry` | гость (QR-токен) | `GuestEntryRequest` + `Accept-Language` | 200 `GuestEntryResponse` + `Set-Cookie` | 404 `qr_invalid`, 403 `table_inactive`, 429 `rate_limited` (+`Retry-After`), 422 (тело), 503 `try_again` |
| GET | `/api/guest/v1/session` | гость (cookie) | — | 200 `GuestSessionResponse` | 401 `guest_session_required`, 401 `guest_session_invalid`, 401 `visit_closed`, 503 `try_again` |
| PUT | `/api/guest/v1/session/lang` | гость (cookie) | `GuestLangRequest` | 200 `GuestSessionResponse` + `Set-Cookie` | 401 (как выше), 422 `lang_not_supported`, 422 (тело), 503 `try_again` |

```jsonc
// GuestEntryRequest
{ "token": "string, 1..128",         // формат проверяет сервис → qr_invalid, не 422
  "lang": "az" | "ru" | null }       // явный выбор устройства; необязательно

// GuestEntryResponse  (GuestSessionResponse — то же без visit.is_new)
{
  "tenant": { "name": "Демо-ресторан", "languages": ["az", "ru"], "default_lang": "az", "currency": "AZN" },
  "table":  { "name": "Стол 1", "type": "table" },                 // type: table | cabin
  "visit":  { "id": "0192…-uuid", "opened_at": "2026-11-04T18:05:00+04:00", "is_new": true },
  "lang":   "ru"
}

// GuestLangRequest
{ "lang": "az" | "ru" }
```

Гостю не отдаются `tenant_id`, `table_id`, `hall_id`, `price_tier`, `external_id`, `qr_token`. `visit.id` (UUIDv7) нужен для будущих подписок (SSE #11/#12) и сам доступа не даёт: доступ даёт только подписанная cookie.

Коды 401:
- `guest_session_required` — cookie нет, она повреждена, подпись неверна или истёк TTL;
- `guest_session_invalid` — токен перевыпущен, стол отключён, демо в prod, визит не найден по `tid`/`vid`/`tbl`;
- `visit_closed` — визит закрыт.

Фронтенд при первых двух входит повторно по токену из URL автоматически, при `visit_closed` — только по кнопке.

### Зависимость `current_guest` (для #10–#12)

```python
CurrentGuest = Annotated[GuestContext, Depends(current_guest)]

@dataclass(frozen=True, slots=True)
class GuestContext:
    tenant_id: uuid.UUID
    table_id: uuid.UUID
    visit_id: uuid.UUID
    lang: Lang
    price_tier: str          # тариф стола — цены меню #10
    languages: tuple[Lang, ...]
    currency: str
```

Все гостевые запросы #10–#12 фильтруют по `guest.tenant_id` и `guest.visit_id`; `tenant_id` из клиента не принимается.

## Конфигурация

Новые поля `Settings` и строки `.env.example`:

| Переменная | Тип / по умолчанию | Назначение |
|---|---|---|
| `GUEST_SESSION_SECRET` | `SecretStr \| None`, нет | ключ HMAC cookie; ≥ 32 символов; обязателен при `APP_ENV=prod` или `APP_MODE=scaled` |
| `GUEST_SESSION_TTL_HOURS` | `int`, 12 (1…72) | срок жизни cookie и `iat` |
| `GUEST_COOKIE_SECURE` | `bool \| None`, None → `true` при prod | атрибут `Secure` |
| `GUEST_ENTRY_RATE_LIMIT` | `int`, 30 (≥ 0; 0 — выкл.) | входов в минуту с одного IP |

В stubs поля добавлены **без** валидатора обязательности секрета: иначе упали бы существующие тесты, создающие prod-`Settings`. Developer добавляет в `_check_mode_consistency` проверку (`prod` или `scaled` без секрета или короче 32 символов — `ValueError` без значения секрета в тексте) и обновляет тесты, которые строят prod/scaled `Settings` (`tests/test_config.py`, `tests/test_main.py`, `tests/test_lifespan.py`, scaled-фикстуры). Значение секрета — только заглушка в `.env.example`; README (раздел scaled/deploy, `deploy/.env`) дополняется командой генерации: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## События и фоновые задачи

Нет. EventBus-событий о входе гостя и открытии визита в #9 нет: подписчиков пока нет (панель официанта — #20). Когда появятся, событие публикуется после commit в `entry.enter_table` (`visit.opened`). Автозакрытие визитов — #23 через `visits.close_visit`.

## ИИ

Не затронут. `current_guest.lang` станет входом для языка ответа в #11. Функции отправки заказа нет; меню в промпт не кладётся.

## Security

- **Мультиарендность.** `tenant_id` определяется только сервером: при входе — по `qr_token`, далее — из подписанной cookie, и сверяется с БД (`visits.tenant_id = :tid AND id = :vid AND table_id = :tbl`). Все запросы сервисов содержат `tenant_id`. Межарендные ссылки невозможны и на уровне БД (составные FK, DEC-006).
- **Токены.** 192 бита (`secrets`), проверка формата до БД, одинаковый 404 для всех неуспешных вариантов (ADR-9.6), демо-заведение в prod отвергается. В логи приложения токен не пишется — только `table_id`/`tenant_id` (риск R-2 про access-лог).
- **Cookie.** HMAC-SHA256, `compare_digest`, версия формата; `HttpOnly`, `SameSite=Strict`, `Secure` в prod, `Path=/api/guest/`. Payload не зашифрован — в нём только UUID и язык, секретов нет. Срок проверяется по `iat` на сервере.
- **CSRF.** `SameSite=Strict`; изменяющие запросы принимают только JSON-тело (Pydantic-модель). Developer добавляет тест: `PUT /session/lang` с `Content-Type: text/plain` / form → 422, а не 200.
- **Rate-limit.** ADR-9.7; ключ без `:`; fail-open с логом.
- **Утечка токена через Referer.** В `frontend/index.html` — `<meta name="referrer" content="same-origin">`: путь `/t/{token}` не уходит внешним ресурсам (карты, шрифты, ссылки в описаниях блюд в будущем).
- **Кэширование.** `Cache-Control: no-store` на всех ответах `/api/guest/v1/*`; Service Worker их не перехватывает (`navigateFallbackDenylist` по `/api`).
- **Ошибки и логи.** Тело ошибки — только `code`. В лог — `code`, `tenant_id`/`table_id`, если известны, без cookie, токена и `Accept-Language` целиком. Отказы входа (`qr_invalid`, `table_inactive`, `rate_limited`) и 401 гостевой сессии — уровень INFO, по одной записи на запрос; объём ограничен rate-limit входа (ADR-9.7). Успешный вход — INFO с `tenant_id`, `table_id`, `visit_id`, `is_new`, `lang`. Сбой `RateLimiter` — WARNING.
- **Prompt injection.** Не затронут. Название заведения и стола в ответе — данные кассы/админа; фронтенд выводит их как текст, а не HTML.

## Риски

| # | Риск | Мера |
|---|---|---|
| R-1 | Утечка `GUEST_SESSION_SECRET` позволяет подделать сессию любого визита (зная UUID визита) | секрет только в env; ротация разлогинивает всех; открытый вопрос 3 — ротация двумя ключами |
| R-2 | `/t/{token}` попадает в access-лог uvicorn/Caddy и в историю браузера | логи на сервере, доступ ограничен; перевыпуск токена (#27) при подозрении; фильтр access-лога — #32 |
| R-3 | Общий NAT заведения: 30 входов/мин на IP может не хватить при наплыве | значение в env; по метрикам 429 (#32) — повысить |
| R-4 | Фото QR, унесённое из заведения, даёт удалённый вход и заказ | ТЗ это допускает (визит без подтверждения официанта, вопрос 8); заказ подтверждает официант (FR-11); перевыпуск токена |
| R-5 | Фантомные визиты от повторных сканирований после закрытия | новый визит только явным POST; автозакрытие #23 по `last_activity_at` |
| R-6 | В single без `GUEST_SESSION_SECRET` ключ случайный на процесс | WARNING при старте; в prod секрет обязателен (валидатор) |

## Открытые вопросы

1. Вопрос 8 ТЗ: подтверждает ли официант открытие визита? Для этапа 1 пользователь подтвердил «первое сканирование открывает визит» (2026-11-10); режим для пилота решается в #19/#21 (spec Q-1, отложен).
2. ~~Блокирующий экран выбора языка~~ — решено в spec FR-7/FR-11: только видимый переключатель с предвыбранным языком.
3. Ротация `GUEST_SESSION_SECRET` без разлогинивания (`GUEST_SESSION_SECRET_PREVIOUS`) — нужна ли на этапе 1?
4. Сохранять ли историю отозванных токенов, чтобы отвечать «QR-код устарел, спросите новый у официанта» вместо общего `qr_invalid`? Сейчас нет: это потребовало бы таблицы и различимого ответа.

## Module Structure (code stubs)

```
backend/app/guest/__init__.py      пакет сервисов гостя (без FastAPI)
backend/app/guest/errors.py        GuestError; QrInvalidError, TableInactiveError, VisitOpenConflictError, TableNotFoundError, LangNotSupportedError, GuestSessionInvalidError, VisitClosedError
backend/app/guest/tokens.py        QR_TOKEN_BYTES, REISSUE_ATTEMPTS, generate_qr_token, is_valid_token_format, reissue_table_token
backend/app/guest/visits.py        OPEN_VISIT_ATTEMPTS, get_or_open_visit, close_visit, touch_visit, set_visit_lang
backend/app/guest/lang.py          ACCEPT_LANGUAGE_MAX_LENGTH, parse_accept_language, resolve_entry_lang
backend/app/guest/session.py       GuestSessionClaims, GuestSessionCodec (encode/decode/remaining_seconds), issue_claims, build_guest_session_codec
backend/app/guest/entry.py         EntryResult, GuestVisitView, find_table_by_token, enter_table, load_guest_context, change_lang
backend/app/schemas/guest.py       GuestEntryRequest, GuestLangRequest, GuestEntryResponse, GuestSessionResponse, …
backend/app/api/errors.py          ErrorCode, ApiErrorDetail, ApiErrorBody, api_error
backend/app/api/guest_auth.py      GuestContext, GUEST_COOKIE_NAME, get_guest_session_codec, current_guest_view/CurrentGuestView, current_guest/CurrentGuest, set_guest_cookie, client_ip_key
                                   (load_guest_context → доменный GuestVisitView с названиями для GET /session;
                                    current_guest строит из него GuestContext; зависимость кэшируется в запросе — один SELECT)
backend/app/api/guest.py           router /api/guest/v1: POST /entry, GET /session, PUT /session/lang
backend/app/core/config.py         + guest_session_secret, guest_session_ttl_hours, guest_cookie_secure, guest_entry_rate_limit, guest_cookie_secure_effective
backend/app/main.py                + include_router(guest.router); app.state.guest_session_codec — developer
.env.example                       + GUEST_* (раздел «Гость»)
frontend/src/api/types.ts          + GuestEntryResponse, GuestSessionResponse, GuestLang, ApiErrorBody
frontend/src/api/client.ts         + ApiError.code; enterTable, getGuestSession, setGuestLang (stubs)
```

Developer дополнительно:
- `frontend/src/pages/GuestPage.tsx` — вызов `enterTable` при монтировании; состояния «загрузка», «стол» (название заведения и стола), ошибки `qr_invalid`/`table_inactive`/`rate_limited`/`visit_closed` на выбранном языке; переключатель AZ/RU (`setGuestLang` + `localStorage` с try/catch). Полный интерфейс гостя — #13.
- `frontend/index.html` — `<meta name="referrer" content="same-origin">`.
- Тесты: unit `tests/test_guest_tokens.py`, `test_guest_lang.py`, `test_guest_session.py` (подпись, подмена, TTL, версия), `test_guest_api.py` (роутер с подменёнными сервисами, cookie-атрибуты, коды ошибок, 429, fail-open); db `tests/db/test_guest_entry.py` (get-or-open, гонка через две сессии/`asyncio.gather`, закрытие → новый визит, перевыпуск → 404 и 401, `is_active=false` → 403, демо в prod → 404, изоляция арендаторов).
