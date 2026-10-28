# Architecture: Feature #60 — Защита от демо-данных в боевой базе

**Issues:** #60 (проверка в `python -m app.seed`), #71 (неготовность приложения в prod) · **ТЗ:** 6 NFR-4, NFR-6, NFR-8; 9.1–9.3
**Spec:** `docs/specs/feature-60-demo-data-guard.md` (AC-1, AC-2, FR-1…FR-4, NFR-1…NFR-6, E-1…E-10)
**Опирается на:** `docs/arch/feature-6-project-scaffold.md` (контракт `/health/ready`, lifespan, «недоступная зависимость не роняет процесс»), `docs/arch/feature-7-data-model.md` (ADR-7.9 — ленивый `Database`, ADR-7.11 — db-тесты, ADR-7.12 — сид), DEC-002, DEC-007, DEC-008
**Источник замечания:** security review #53, `docs/test-cases/feature-53-seed.md`, TC-53-003 (Notes)

Демо-заведение `DEMO_TENANT_ID` с QR-токенами из публичного репозитория не должно оказаться в рабочей системе. Сейчас сид проверяет только `APP_ENV` машины, на которой его запускают. Фича добавляет две независимые проверки по содержимому самой базы:

1. **#60 — сид не пишет в базу, где есть чужие заведения** (код 2).
2. **#71 — приложение с `APP_ENV=prod` не готово, если в базе есть демо-заведение** (`/health/ready` 503 + WARNING в лог). Так ловятся все остальные пути: пустая боевая база, в которую сид всё-таки загрузили; восстановленный дамп базы разработки; старая версия сида; ручной `INSERT`.

Проверки закрывают разные пути появления демо-данных, их можно реализовывать в любом порядке.

**Схема БД и миграции не меняются.** Новых таблиц, колонок, индексов и ревизий нет. Оба запроса используют первичный ключ `tenants.id`. Новых переменных окружения нет.

---

## ADR-60.1. Сид: проверка целевой базы в транзакции сида, до первой записи

**Контекст.** `python -m app.seed` выполняет `apply_seed(session)` в одной транзакции (`database.session()` + `session.begin()`). В issue задан запрос `SELECT EXISTS (SELECT 1 FROM tenants WHERE id <> DEMO_TENANT_ID)`. Spec (открытый вопрос 3) предлагает не вводить блокировки.

**Решение.**
- Новый модуль `app/seed/guard.py`:
  - `foreign_tenants_exist(session) -> bool` — `select(exists().where(Tenant.id != DEMO_TENANT_ID))`;
  - `ensure_seed_target(session)` — если запрос вернул `true`, бросает `ForeignTenantsError`;
  - константа `FOREIGN_TENANTS_REFUSAL` — текст сообщения.
  `DEMO_TENANT_ID` берётся из `app.seed.data`.
- **Проверка вызывается из CLI, а не из `apply_seed`.** `_run` в `app/seed/__main__.py`:
  ```python
  async with database.session() as session, session.begin():
      await ensure_seed_target(session)   # первый запрос транзакции
      return await apply_seed(session)
  ```
  Контракт `apply_seed` («загрузить в текущей транзакции») не меняется. db-тесты загрузчика, в которых в базе есть другое заведение (`test_seed_does_not_touch_foreign_table_with_same_token`), продолжают проверять вторую линию защиты: чужой стол с демо-токеном не перезаписывается. Сид — единственный путь, где политика «только база разработки» нужна. db-фикстуры и будущие тесты могут звать `apply_seed` и рядом с другими заведениями.
- **Порядок проверок в `main`** (FR-2, E-5):
  1. разбор аргументов;
  2. `APP_ENV=prod` → отказ, код 2, `PROD_REFUSAL` (как сейчас: до чтения остальной конфигурации и до подключения);
  3. `Settings` → ошибка конфигурации, код 1;
  4. транзакция: `ensure_seed_target` → `apply_seed` → commit.
- **Коды выхода.** `ForeignTenantsError` перехватывается в `main` **раньше** общего `except Exception`: в stderr печатается `FOREIGN_TENANTS_REFUSAL`, возвращается **2**. Код 2 означает «запрещено политикой» (prod или чужая база), код 1 — «ошибка конфигурации или БД». Ошибки самого запроса проверки (нет соединения, нет таблицы `tenants`, E-6) — по-прежнему код 1 через `describe_error` с подсказкой `alembic upgrade head`. Константы: добавить `EXIT_FORBIDDEN = 2` и оставить `EXIT_PROD_FORBIDDEN = EXIT_FORBIDDEN` (на него ссылаются тесты #53). Docstring модуля и `app/seed/__init__.py` дополнить новым кодом.
- **«Ничего не записано».** Исключение выходит из `session.begin()`, транзакция откатывается. Проверка — первый запрос транзакции, поэтому откатывать нечего. Демо-строки в базе «демо + реальное» тоже не обновляются (E-3).
- **Изоляция и гонка.** Уровень изоляции — по умолчанию READ COMMITTED, блокировок нет. Остаётся окно гонки: заведение, зафиксированное другой транзакцией между проверкой и commit сида (меньше секунды), проверка не увидит. Повышение изоляции этого окна не закрывает:
  - REPEATABLE READ — это снимок, вставку новой строки он не запрещает;
  - SERIALIZABLE ловит конфликт, только если пишущая транзакция тоже SERIALIZABLE, а приложение работает в READ COMMITTED.

  Закрыть окно может только `LOCK TABLE tenants IN SHARE ROW EXCLUSIVE MODE` перед проверкой. Мы его **отвергаем**: окно возможно только при ручном запуске сида в момент создания первого заведения (а создавать заведения пока можно только вручную). Последствие гонки обнаружит #71. Блокировка же добавляет `lock_timeout`, ожидание за длинной транзакцией и привилегию `LOCK` (у владельца БД она есть, но это лишняя зависимость).
- **Текст сообщения** (stderr, без числа, id и названий найденных заведений — это данные боевой базы, вывод может попасть в лог CI; spec, вопрос 4):
  > В целевой базе уже есть заведения, кроме демо-заведения: демо-данные в такую базу не загружаются, ничего не записано. Сид предназначен только для базы разработки — проверьте --database-url и DATABASE_URL.

  Имя базы, хост и строка подключения не печатаются (NFR-1).

**Альтернативы (отвергнуты).**
- Проверка внутри `apply_seed` — меняет контракт загрузчика и ломает db-тесты защиты чужих строк, а пользы не добавляет.
- Отдельная транзакция для проверки перед транзакцией сида — окно гонки шире, и нарушается требование issue «в той же транзакции».
- Признак «боевая база» по таблице-метке или настройке в БД — нужна миграция и процедура установки метки. Признак «есть чужие заведения» работает и без неё.
- Флаг `--force` — вне scope (issue).

**Последствия.**
- Разработчик, у которого в базе разработки, кроме демо, есть свои заведения (например, для проб `python -m app.menu_sync`), не может перезапустить сид. Нужна отдельная база или удаление лишних заведений. Это осознанная цена: без флага `--force` ошибиться нельзя.
- Пустую боевую базу (миграции применены, заведений ещё нет) сид примет: отличить её от новой базы разработки по содержимому нельзя (E-1). Этот случай закрывает #71.

---

## ADR-60.2. Приложение в prod: проверка при старте (для лога) и на каждом `/health/ready` (для статуса)

**Контекст.**
- Приложение намеренно стартует при недоступной БД: `Database` ленивый, `start()` не ходит в сеть, о неготовности сообщает `/health/ready` (arch #6, ADR-7.9).
- Режим `single` — служба Windows без оркестратора. `/health/ready` там никто не опрашивает и трафик по нему не снимает.
- В `scaled` healthcheck контейнера `api` в compose — это `/health` (liveness), а не `/health/ready`. Caddy снимает трафик только по `depends_on` при старте. Значит, readiness 503 сам по себе доступ по демо-токенам ни в одном режиме не закрывает. Гостевого API пока нет, блокировка гостевых запросов — вне scope #71.
- Поэтому полезный результат #71 — **сигнал оператору**: 503 для внешнего мониторинга и WARNING в логе, в том числе там, где мониторинга нет.

**Решение — сочетание.** Один объект `DemoDataMonitor` (`app/api/demo_data.py`) на приложение. Его создаёт `create_app`, он хранится в `app.state.demo_data_monitor`, зависимость — `get_demo_data_monitor` в `app/api/deps.py`. Вне `APP_ENV=prod` он не вызывается вовсе (FR-4).

1. **Старт (lifespan, после `start_container`).** При `APP_ENV=prod` выполняется `await monitor.refresh(container.database)`. Проверка ограничена таймаутом 2 с, никогда не бросает исключений и старт не прерывает. Задача — чтобы WARNING попал в лог службы Windows сразу после запуска, даже если `/health/ready` никто не опрашивает. Если БД при старте недоступна, результат `UNKNOWN`, процесс продолжает работу. Принцип arch #6 «недоступная зависимость не роняет процесс» сохраняется. Цена — старт дольше максимум на 2 с, и только когда БД «висит» (при отказе в соединении — мгновенно).
2. **`GET /health/ready` при `APP_ENV=prod`.** `monitor.refresh(database)` выполняется параллельно с `database.ping()` (и Redis в `scaled`) в том же `asyncio.gather`, с тем же таймаутом 2 с. Итоговое правило:

   | `database` | `redis` | демо (`DemoDataState`) | Ответ |
   |---|---|---|---|
   | ok | ok/skipped | `ABSENT` | 200 `ready` |
   | ok | ok/skipped | `FOUND` | **503 `not_ready`** (AC-2) |
   | ok | ok/skipped | `UNKNOWN` (ошибка/таймаут запроса, нет таблицы `tenants`) | **503 `not_ready`** (NFR-5: неизвестно ≠ «демо нет») |
   | fail | любое | любое | 503, как сейчас (E-9) |

   При каждом запросе проверка выполняется заново, кэша нет. Удаление демо-заведения без перезапуска делает приложение готовым при следующем опросе. Появление демо (восстановили дамп «на живую») обнаруживается при следующем опросе.
3. **Запрос.** `app.seed.guard.demo_tenant_exists(session)` — `select(exists().where(Tenant.id == DEMO_TENANT_ID))`, поиск по PK, только чтение. Сессия — `database.session()` (транзакция не фиксируется, при закрытии откатывается).
4. **Состояния и лог — только при смене состояния** (дедупликация, нет спама при опросе раз в 10–30 с):

   | Переход | Уровень | Текст |
   |---|---|---|
   | любое → `FOUND` | WARNING | `DEMO_FOUND_WARNING`: в базе найдено демо-заведение при APP_ENV=prod, приложение не готово, удалите его или проверьте DATABASE_URL |
   | любое → `UNKNOWN` | WARNING | `DEMO_CHECK_FAILED` + `database.describe_error(exc)` (пароль `***`) или «таймаут» |
   | `FOUND` → `ABSENT` | INFO | `DEMO_GONE_INFO` |
   | старт → `ABSENT`, `UNKNOWN` → `ABSENT` | — | без записи (`UNKNOWN` → `ABSENT` после восстановления БД: о восстановлении и так говорит прекращение ошибок `database`) |

   `extra={"component": "demo_data"}`. Строк подключения, хостов и паролей в записи нет. В `scaled` с `API_WORKERS=2` каждый процесс ведёт своё состояние и пишет свою запись: это 2 строки, а не спам. Между `await` и сменой состояния нет точек переключения, поэтому параллельные запросы одного процесса не дублируют запись.
5. **Одинаково в `single` и `scaled`, Windows и Linux** (NFR-2): используется только `Database`, без Redis и без `EventBus`/`TaskScheduler`/`RateLimiter`. Отличие режимов — только в наличии ключа `redis`.

**Стоимость.** В prod каждый запрос `/health/ready` берёт два соединения из пула вместо одного (`SELECT 1` и `EXISTS` по PK), это микросекунды на стороне PostgreSQL. Пул `DB_POOL_SIZE + DB_MAX_OVERFLOW = 10`. Объединять с `SELECT 1` не стали: `database` должен значить «соединение есть» независимо от схемы. Иначе неприменённые миграции выглядели бы как «база недоступна», и смысл ключа `database` из #56 изменился бы.

**Альтернативы (отвергнуты).**
- **Отказ стартовать (выход процесса) при демо в prod.** Требует БД на старте и ломает принцип «стартуем при недоступной БД». При недоступной БД пришлось бы либо ждать, либо стартовать без проверки, то есть защита стала бы негарантированной. Служба Windows ушла бы в цикл перезапусков, а `/health` (liveness) перестал бы отвечать: оператор видел бы «служба падает» вместо понятного сообщения. В `scaled` контейнер `api` перезапускался бы бесконечно (`restart: unless-stopped`), Caddy не стартовал бы (`depends_on: service_healthy`). Гостевого API нет, поэтому выход процесса ничего дополнительно не закрывает.
- **Только проверка при старте, результат в памяти.** Без повторной попытки пропускает демо, если БД была недоступна при старте. Не видит удаления и появления демо без перезапуска. Readiness отражал бы устаревшее состояние.
- **Только `/health/ready`.** В `single` readiness никто не опрашивает: предупреждение не попало бы в лог никогда. AC-2 («пишет в лог») формально выполнялся бы только при наличии мониторинга.
- **Периодическая задача `TaskScheduler`.** Лишняя зависимость от планировщика (в `scaled` задачи выполняет worker, а не процесс `api`), и проверка не связана с ответом readiness. Опрос `/health/ready` и так даёт периодичность там, где есть мониторинг.
- **Кэш результата с TTL (например, 30 с).** Экономия незначительна (один PK-запрос), зато появляется состояние «устарело». Можно добавить позже, если `/health/ready` станут опрашивать часто (см. «Риски»).
- **WARNING на каждом запросе.** Спам в логе при опросе раз в 10 с. Отвергнуто в пользу записи при смене состояния.
- **Признак демо по токенам столов (`qr_token LIKE 'demo-table-%'`).** Формат токена — деталь сида. Документированный ключ — `DEMO_TENANT_ID` (issue, ADR-7.12).

**Последствия.**
- AC-2 выполняется в обоих режимах; WARNING гарантированно есть в логе после старта, если БД доступна.
- Блокировку гостевых запросов к демо-заведению в prod нужно заложить в story гостевого входа по QR-токену (см. «Риски», рекомендация 2).

---

## ADR-60.3. Контракт `/health/ready` не меняется: отдельного ключа для демо нет

**Контекст.** `ReadinessResponse.checks: dict[Literal["database", "redis"], CheckStatus]` (arch #6, #56). Тело публичное, без авторизации, и по контракту не содержит внутренних деталей.

**Решение (подтверждено пользователем 2026-10-26).** При срабатывании #71 тело выглядит так:

```json
503 {"status": "not_ready", "checks": {"database": "ok", "redis": "skipped"}}
```

Ключ `demo_data` (или аналогичный) **не добавляется**. Причина — в ключе `demo_data: "fail"` любой анонимный посетитель прочитал бы: «на этом сервере есть демо-заведение, токены `demo-table-0N-…` из публичного репозитория работают». Это прямая подсказка атакующему. `not_ready` при всех `ok` даёт лишь неспецифичный сигнал «что-то не так». Причину оператор видит в логе (WARNING из ADR-60.2). OpenAPI-схема не меняется.

**Альтернативы.**
- Ключ `demo_data` — удобнее для мониторинга, но раскрывает информацию (см. выше).
- Обобщённый ключ (`"policy": "fail"`) — меньше подсказки, но это всё равно изменение контракта ради одного случая; оператору хватает лога.
- Детали только для авторизованных — авторизации персонала ещё нет (#19).

**Последствия.** Тесты `/health/ready` проверяют тело целиком (`r.json() == {...}`). Новые тесты #71 фиксируют, что лишних ключей нет.

---

## Контракты

### CLI `python -m app.seed [--database-url URL]`

| Ситуация | Код | Поток | Сообщение |
|---|---|---|---|
| Успех (пустая база или только демо, E-1, E-2) | 0 | stdout | как сейчас: «Демо-данные загружены…» + ссылки `/t/{token}` |
| Ошибка конфигурации (`APP_ENV`, `DATABASE_URL`) | 1 | stderr | как сейчас (`format_validation_error`) |
| Ошибка БД, в том числе в запросе проверки (нет соединения, нет `tenants`, E-6) | 1 | stderr | как сейчас: «Не удалось загрузить демо-данные: {describe_error}» + подсказка `alembic upgrade head` |
| `APP_ENV=prod` (E-5) | 2 | stderr | `PROD_REFUSAL` (без изменений, до подключения) |
| **В базе есть заведение, кроме `DEMO_TENANT_ID` (AC-1, E-3, E-4)** | **2** | stderr | **`FOREIGN_TENANTS_REFUSAL`**; stdout пуст; база не изменена |

### `GET /health/ready` (без авторизации)

| Условие | Код | Тело |
|---|---|---|
| не prod (dev/test) | как сейчас | как сейчас (проверка демо не выполняется) |
| prod, демо нет, остальное ok | 200 | `{"status": "ready", "checks": {"database": "ok", "redis": "ok"\|"skipped"}}` |
| prod, демо есть | 503 | `{"status": "not_ready", "checks": {"database": "ok", "redis": "ok"\|"skipped"}}` |
| prod, проверка демо не выполнена (ошибка/таймаут), `database` ok | 503 | то же, что и при найденном демо |
| prod, БД недоступна | 503 | `{"status": "not_ready", "checks": {"database": "fail", …}}` (как сейчас) |

`GET /health` (liveness) не меняется и в БД не ходит.

---

## События и фоновые задачи

Нет. EventBus-событий и задач TaskScheduler фича не добавляет.

## ИИ

Не затронут.

---

## Security

- **Утечка секретов (NFR-1).** Ни сообщения CLI, ни лог, ни тело `/health/ready` не содержат строки подключения, хоста, порта и пароля. Ошибки БД выводятся только через `Database.describe_error`. Сообщение сида не раскрывает число, id и названия чужих заведений. В логе #71 допустимо упоминать демо-заведение: его id и токены и так публичны.
  - **Известное ограничение (security review #60, LOW, существует с #7).** `describe_error` маскирует только пароль. Хост, порт и имя пользователя из текста ошибки драйвера (например, `Connect call failed ('<host>', 5432)`) могут попасть в stderr сида (код 1) и в WARNING `DEMO_CHECK_FAILED` (#71). Тексты, которые формирует сама фича (`PROD_REFUSAL`, `FOREIGN_TENANTS_REFUSAL`, `DEMO_FOUND_WARNING`, тело `/health/ready`), деталей подключения не содержат. Устранение — доработка `describe_error` отдельной задачей, вне #60.
  - **`exc_info=True` в `app/api/health.py::_check` (INFO, существующий код #56).** Traceback исключения ping пишется в лог без маскирования и может содержать DSN. Проверить и решить при реализации #71 или отдельным bug; в `DemoDataMonitor` `exc_info` не используется (раздел «Логирование»).
- **Раскрытие информации.** Ключа `demo_data` в публичном теле нет (ADR-60.3).
- **Нагрузка.** `/health/ready` публичный и без rate-limit (как сейчас). В prod каждый запрос — два коротких запроса к БД с таймаутом 2 с. Флуд упирается в пул (10 соединений) и мешает остальным запросам так же, как и сейчас с `SELECT 1`. Порядок величины не меняется (см. «Риски»).
- **Мультиарендность.** Запросы читают `tenants` без фильтра по `tenant_id` — это осознанно: проверка платформенная, а не в контексте заведения. `tenants` — корневая таблица без `tenant_id` (DEC-010). Данные заведений наружу не выходят: результат — один бит, и он остаётся в процессе.
- **Обход.** Отключить проверку конфигурацией нельзя (нет флага, NFR-3). Обходы — `APP_ENV≠prod` в боевой системе (вне scope, чек-лист деплоя G6, TC-53-003) или прямой `INSERT` в пустую базу; второй случай ловит #71.
- **Prompt injection, роли** — не затронуты.

## Логирование

- Сид пишет только в stdout/stderr (как сейчас), логгер не настраивает.
- `app.api.demo_data`: WARNING/INFO только при смене состояния (ADR-60.2, п. 4), `extra={"component": "demo_data"}`, формат — общий JSON-лог (`configure_logging`, NFR-6). `exc_info` не передаётся: traceback asyncpg может содержать DSN. Текст ошибки — только через `describe_error`.

---

## Тестовая стратегия

**Unit (без БД, Windows и Linux, `-m "not db and not scaled"`).**
- `tests/test_seed_guard.py` (новый) — `foreign_tenants_exist`/`demo_tenant_exists` на `AsyncMock` сессии. Проверяется:
  - скомпилированный SQL (`EXISTS`, `tenants.id <>` / `=`, параметр — `DEMO_TENANT_ID`);
  - `ensure_seed_target`: `true` → `ForeignTenantsError`, `false` → ничего;
  - текст `FOREIGN_TENANTS_REFUSAL` на русском, без `postgresql`/`@`/цифр числа.
- `tests/test_seed.py` (дополнить, CLI):
  - `ensure_seed_target` бросает `ForeignTenantsError` → код 2, текст в stderr, `apply_seed` не вызван, stdout пуст;
  - порядок: при `APP_ENV=prod` `ensure_seed_target` не вызывается (отказ раньше);
  - ошибка БД в проверке → код 1 без пароля;
  - **существующие тесты, которые подменяют только `apply_seed`** (`test_success_prints_relative_guest_links`, `test_database_url_argument_overrides_environment`, `test_database_error_is_exit_1_without_password`), должны подменять и `seed_cli.ensure_seed_target` на async no-op (лучше в фикстуре `dev_env` или отдельной). Иначе проверка пойдёт в `db.invalid` и вернёт код 1.
- `tests/test_demo_data.py` (новый) — `DemoDataMonitor` с подменой `app.api.demo_data.demo_tenant_exists`:
  - `True` → `FOUND` + один WARNING; повтор → без новой записи;
  - `False` после `FOUND` → `ABSENT` + INFO;
  - исключение → `UNKNOWN` + WARNING с `***` вместо пароля (настоящий `Database` с фиктивным URL);
  - таймаут (`asyncio.sleep` дольше `check_timeout` — использовать маленький таймаут) → `UNKNOWN`;
  - `CancelledError` пробрасывается;
  - первое `ABSENT` — без записи.
- `tests/test_health.py` (дополнить) — `make_settings(app_env="prod", public_base_url=…)`:
  - `FOUND` → 503 и тело ровно `{"status": "not_ready", "checks": {"database": "ok", "redis": "skipped"}}`;
  - `UNKNOWN` при `database` ok → 503;
  - `ABSENT` → 200;
  - в dev/test проверка не вызывается (spy) и 200 при демо;
  - `scaled` — то же с ключом `redis`;
  - проверка выполняется параллельно с `database` (как `test_ready_runs_checks_concurrently`);
  - OpenAPI-схема без новых ключей.
- `tests/test_lifespan.py` или `tests/test_main.py` (дополнить):
  - в prod lifespan вызывает `refresh` один раз; исключение внутри не роняет старт;
  - в dev не вызывает;
  - `app.state.demo_data_monitor` создан в `create_app`.
  Существующий `test_docs_disabled_in_prod` не должен зависеть от проверки: если он запускает lifespan, `refresh` на `FakeDatabase` даст `UNKNOWN` и WARNING, но не исключение.

**db (маркер `db`, PostgreSQL, Linux-джоб `backend-services`; локально на Windows — через `TEST_DATABASE_URL`).**
- `tests/db/test_seed.py` (дополнить, фикстура `committed_seed`):
  - AC-1, E-4: другое заведение → `main` = 2, счётчики строк всех таблиц не изменились, демо-заведения нет;
  - E-3: демо + другое → 2, демо-строки не обновлены (`updated_at` прежний);
  - E-1/E-2 уже покрыты `test_cli_twice_commits_same_data`;
  - функции `guard` на `db_session`: пустая база / только демо / демо + другое.
- `tests/db/test_health_db.py` (дополнить):
  - AC-2: prod + демо-заведение (зафиксированное через отдельное соединение или `apply_seed` + commit с очисткой) → 503, тело без деталей, WARNING в `caplog` без пароля;
  - prod без демо → 200;
  - демо удалено между опросами → 200 и INFO.

**Матрица CI** не меняется: unit-тесты идут на Windows и Linux, db-тесты — в `backend-services`.

---

## Module Structure (code stubs)

```
backend/app/seed/guard.py          # #60 РЕАЛИЗОВАН: FOREIGN_TENANTS_REFUSAL, ForeignTenantsError,
                                   #   foreign_tenants_exist, ensure_seed_target, demo_tenant_exists (для #71)
backend/app/seed/__main__.py       # #60 РЕАЛИЗОВАН: _run вызывает ensure_seed_target; main ловит ForeignTenantsError → 2;
                                   #   EXIT_FORBIDDEN = 2 (EXIT_PROD_FORBIDDEN — алиас); docstring кодов
backend/app/seed/__init__.py       # #60 РЕАЛИЗОВАН: строка про проверку целевой базы
backend/app/api/demo_data.py       # СОЗДАН (stub): DemoDataState, DemoDataMonitor(check_timeout).refresh/_transition,
                                   #   DEMO_FOUND_WARNING, DEMO_CHECK_FAILED, DEMO_GONE_INFO
backend/app/api/deps.py            # #71: get_demo_data_monitor(request) -> DemoDataMonitor
backend/app/api/health.py          # #71: в prod — monitor.refresh в gather; FOUND/UNKNOWN → 503; контракт тела прежний
backend/app/main.py                # #71: create_app → app.state.demo_data_monitor = DemoDataMonitor(READINESS_CHECK_TIMEOUT);
                                   #   lifespan: в prod после start_container — await monitor.refresh(container.database)
```

Состояние на 2026-10-26: #60 реализован (коммит 4ff4749, G4 PASS, security:passed); заглушка `app/api/demo_data.py` (#71) к коду не подключена, `deps.py`, `health.py`, `main.py` не менялись. Frontend не затронут.

### Реализация #60 — файлы и тесты (doc-sync после G4, дополнено после G5)

| Файл | Что сделано |
|---|---|
| `app/seed/guard.py` | `foreign_tenants_exist` (`select(exists().where(Tenant.id != DEMO_TENANT_ID))`), `ensure_seed_target` → `ForeignTenantsError`, `FOREIGN_TENANTS_REFUSAL`; `demo_tenant_exists` (для #71) |
| `app/seed/__main__.py` | порядок `main`: аргументы → `APP_ENV=prod` (2) → `Settings` (1) → транзакция `ensure_seed_target` → `apply_seed`; `except ForeignTenantsError` (2) перед `except Exception` (1); `EXIT_FORBIDDEN = 2`, `EXIT_PROD_FORBIDDEN = EXIT_FORBIDDEN` |
| `app/seed/__init__.py`, `README.md` | описание проверки целевой базы и кода 2 |

| Тест (относительно `backend/`) | Что проверяет |
|---|---|
| `tests/test_seed_guard.py` | скомпилированный SQL `EXISTS` с `<>`/`=` и параметром `DEMO_TENANT_ID`; `None` → `False`; `ensure_seed_target` бросает/не бросает; ошибка БД не перехватывается; текст `FOREIGN_TENANTS_REFUSAL` на русском без деталей подключения |
| `tests/test_seed.py` | фикстура `seed_target_ok` (подмена `ensure_seed_target` для прежних CLI-тестов); `test_foreign_tenants_are_refused_with_exit_code_2`, `test_exit_prod_forbidden_is_alias_of_exit_forbidden`, `test_prod_refusal_happens_before_target_check`, `test_target_check_runs_before_apply_seed_in_same_session`, `test_database_error_in_target_check_is_exit_1_without_password`; G5: `test_foreign_tenants_refusal_is_same_in_both_modes[single|scaled]` (E-10, NFR-2: отказ одинаков при `APP_MODE=single`/`scaled`, Redis не нужен, в stderr ровно текст отказа без пароля и адреса Redis) |
| `tests/db/test_seed.py` | `test_guard_on_empty_base`, `test_guard_on_demo_only_base`, `test_guard_on_demo_and_other_base`, `test_guard_on_other_only_base`; CLI `test_cli_refuses_base_with_other_tenant` (AC-1, E-4), `test_cli_refuses_demo_plus_other_without_updating_demo` (E-3); E-1/E-2 — прежний `test_cli_twice_commits_same_data`. G5: общий хелпер `_assert_refused` усилен — stdout пуст, stderr ровно `FOREIGN_TENANTS_REFUSAL`, нет пароля, хоста, имени базы, пользователя, `postgresql`, UUID и названия найденного заведения (AC-1, NFR-1, ADR-60.1); `test_cli_without_schema_fails_with_hint` — нет таблицы `tenants`: код 1 с подсказкой `alembic upgrade head`, текста отказа нет (E-6) |

TC: `docs/test-cases/feature-60-demo-seed-guard.md` (TC-60-001…TC-60-010, G5 PASS 2026-10-28; ручной TC-60-010).

---

## Истории — файлы, тесты, порядок

| Story | Файлы | Тесты |
|---|---|---|
| #60 | `app/seed/guard.py` (`foreign_tenants_exist`, `ensure_seed_target`, `ForeignTenantsError`, `FOREIGN_TENANTS_REFUSAL`; `demo_tenant_exists` можно реализовать здесь же — функция в одну строку, а нужна она #71), `app/seed/__main__.py`, `app/seed/__init__.py`, README (раздел про сид — одна фраза: «только пустая база или база с демо») | unit: `tests/test_seed_guard.py`, дополнения `tests/test_seed.py` (включая правку существующих тестов CLI, см. «Тестовая стратегия»). db: дополнения `tests/db/test_seed.py` |
| #71 | `app/api/demo_data.py`, `app/api/deps.py`, `app/api/health.py`, `app/main.py`; `app/seed/guard.py:demo_tenant_exists`, если её не сделал #60 | unit: `tests/test_demo_data.py`, дополнения `tests/test_health.py`, `tests/test_lifespan.py`/`tests/test_main.py`. db: дополнения `tests/db/test_health_db.py` |

**Порядок.** Независимы. Общий файл — только `app/seed/guard.py`: обе заглушки уже в нём, поэтому конфликтов при параллельной работе нет, каждая story заполняет свои функции. Если story идут последовательно, удобнее #60 → #71: #71 переиспользует готовый модуль и db-фикстуры.

**Для TC (test-case-writer).** По ADR-60.2 добавить случаи:
- «демо удалили без перезапуска → следующий опрос 200 + INFO»;
- «повторные опросы при демо → один WARNING»;
- «БД недоступна при старте в prod → процесс работает, `/health` 200»;
- «проверка не выполнена при `database` ok → 503».

---

## Риски

| Риск | Митигация |
|---|---|
| Readiness 503 не закрывает доступ по демо-токенам: в `single` нет оркестратора, в `scaled` compose и Caddy смотрят на `/health` | Цель #71 — сигнал оператору (лог + мониторинг). Рекомендация 2: в story гостевого входа по QR-токену отклонять демо-заведение при `APP_ENV=prod` |
| Боевая система запущена с `APP_ENV≠prod` — обе проверки #71 молчат | Вне scope: пункт `APP_ENV=prod` в чек-листе деплоя (G6, TC-53-003) |
| Разработчик с несколькими заведениями в базе разработки не может перезапустить сид | Сообщение подсказывает причину; отдельная база разработки; `--force` — отдельная задача, если понадобится |
| Гонка в сиде (заведение создаётся во время сида) | ADR-60.1: окно меньше секунды, сценарий ручной; последствие ловит #71 |
| Старт в prod дольше до 2 с, если БД «висит» | Таймаут 2 с; при отказе в соединении — мгновенно; liveness не зависит |
| Частые опросы `/health/ready` в prod — два запроса к БД на опрос | PK-запрос дешёвый; при необходимости — кэш с TTL в `DemoDataMonitor` без смены контракта |
| `exc_info` в логе раскрыл бы DSN | В `DemoDataMonitor` — только `describe_error`, без `exc_info` (unit-тест на `***`) |

---

## Открытые вопросы для пользователя (с рекомендациями)

1. **Контракт `/health/ready` при демо в prod.** ✅ Закрыт 2026-10-26: пользователь подтвердил рекомендацию — тело без изменений: `503 {"status": "not_ready", "checks": {...все "ok"...}}`, ключа `demo_data` нет, причина — только в логе (ADR-60.3).
2. **(Для analysis-lead, не блокирует.)** Завести или дополнить story гостевого входа по QR (этап 1): при `APP_ENV=prod` запросы к столам `DEMO_TENANT_ID` отклоняются так же, как к неизвестному токену. Только это реально закрывает доступ по демо-токенам. В #71 не входит (spec «Вне scope»).
