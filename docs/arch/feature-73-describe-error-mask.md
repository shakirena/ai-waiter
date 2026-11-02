# Architecture: Feature #73 — Маскирование DATABASE_URL в describe_error

**Issue:** #73 (type:bug, priority:medium, backend, security) · **ТЗ:** 6 NFR-4, NFR-6, NFR-8
**Spec:** `docs/specs/feature-73-describe-error-mask.md` (AC-1, FR-1…FR-5, NFR-1…NFR-4, E-1…E-13)
**Опирается на:** `docs/arch/feature-7-data-model.md` (ADR-7.9 — `Database`), `docs/arch/feature-60-demo-data-guard.md` (раздел Security, известное ограничение LOW)

`Database.describe_error` (`backend/app/db/session.py`) сейчас заменяет на `***` только пароль из `DATABASE_URL`. Хост, порт, пользователь и имя базы из текста ошибки драйвера попадают в лог `/health/ready`, WARNING `DEMO_CHECK_FAILED`, stderr сида и отчёт `menu_sync`. Исправление — только внутри `session.py`: сигнатура `describe_error(exc) -> str` и места вызова не меняются (FR-5).

**ERD:** не меняется (таблиц, колонок, миграций нет).
**API Contracts:** не меняются (HTTP, CLI-коды выхода, тело `/health/ready`, OpenAPI — прежние; меняется только текст в логе и stderr).
**События и фоновые задачи:** нет. **ИИ:** не затронут. **Конфигурация:** новых переменных окружения нет. **Frontend:** не затронут.

---

## Что возвращает make_url (проверено, SQLAlchemy 2.0.x в `backend/.venv`)

| `DATABASE_URL` | `username` / `password` | `host` | `port` | `database` | `query` |
|---|---|---|---|---|---|
| `…://waiter:secret@192.0.2.10:5432/waiter` | `waiter` / `secret` | `192.0.2.10` | `5432` | `waiter` | `{}` |
| `…://waiter:secret@db.example.com/waiter` | `waiter` / `secret` | `db.example.com` | `None` | `waiter` | `{}` |
| `…://waiter:secret@[2001:db8::1]:5433/waiter` | `waiter` / `secret` | `2001:db8::1` (без скобок) | `5433` | `waiter` | `{}` |
| `…://us%40er:p%40ss@db.example.com/my%2Fdb` | `us@er` / `p@ss` (декодированы) | `db.example.com` | `None` | `my/db` | `{}` |
| `…://waiter:secret@192.0.2.10,192.0.2.11:5433/waiter` | — | `192.0.2.10,192.0.2.11` (строка с запятой) | `5433` | `waiter` | `{}` |
| `…://w:s@192.0.2.10:5432,192.0.2.11:5433/x` | `ValueError` (порт `5432,192.0.2.11:5433`) → `UNPARSABLE_URL_TEXT` | | | | |
| `…://waiter:secret@/waiter?host=/var/run/postgresql` | — | `None` | `None` | `waiter` | `{'host': '/var/run/postgresql'}` |
| `…://waiter:secret@/waiter?host=192.0.2.10:5432&host=192.0.2.11:5433` | — | `None` | `None` | `waiter` | `{'host': ('192.0.2.10:5432', '192.0.2.11:5433')}` (кортеж) |
| `…://waiter:secret@/waiter?host=192.0.2.10&port=6543` | — | `None` | `None` | `waiter` | `{'host': '192.0.2.10', 'port': '6543'}` |
| `…://w@[2001:db8::1]/x?host=[2001:db8::2]:5434` | — | `2001:db8::1` | `None` | `x` | `{'host': '[2001:db8::2]:5434'}` |
| `…://waiter@db.example.com/waiter?user=other&password=pw2` | `waiter` / `None` | `db.example.com` | `None` | `waiter` | `{'user': 'other', 'password': 'pw2'}` |

Диалект asyncpg (`PGDialect_asyncpg.create_connect_args`) делает `opts.update(url.query)` и разбирает `host=h:p` на списки `host`/`port`. Значит, **`?user=` и `?password=` из query переопределяют значения из userinfo и уходят в драйвер**. Сейчас `?password=` не маскируется вовсе — это ещё одна утечка того же бага, она закрывается здесь же.

---

## Решение

Отдельный ADR не нужен: формат лога, контракты и правила CLAUDE.md не меняются, решение локально в одном модуле. Обоснования — по пунктам.

### 1. Какие значения маскируются

Источник — `make_url(DATABASE_URL)`; новый хелпер `_url_secrets(url) -> _UrlSecrets` собирает две группы значений.

| Группа | Значения | Как заменяется |
|---|---|---|
| `substrings` (секрет) | `url.password`; `query["password"]` | простая подстрока (`str.replace`), без границ |
| `tokens` (адрес и учётка) | `url.username`; `url.host` — целиком и каждая часть после разбиения по `,`; `url.port` (только явный); `url.database`; из query: `host` (каждое значение и каждая часть через `,`; форма `h:p` и `[v6]:p` разбивается на хост и порт, всё значение целиком тоже добавляется), `port`, `user`, `database`, `passfile` | целый токен (п. 3), без учёта регистра |

- Значение query может быть строкой или кортежем (повтор ключа) — обрабатываются оба.
- Ключи query — те, что asyncpg принимает как параметры подключения (`host`, `port`, `user`, `password`, `database`, `passfile`). Остальные (`ssl`, `prepared_statement_cache_size`, …) не маскируются: это не адрес и не учётные данные, а короткие значения вроде `0` или `require` испортили бы текст.
- Схема и драйвер (`postgresql+asyncpg`) не маскируются (FR-2).
- Пустые строки и `None` пропускаются.
- Почему пароль — подстрока, а остальное — токен: пароль — секрет с высокой энтропией. Его вхождение внутри другого слова (`xpw-s3cret`) всё равно утечка, а случайных совпадений почти не бывает. Пользователь, база, порт и хост — короткие и «словарные» (`waiter`, `x`, `5432`): подстрока портила бы обычный текст. Короткий пароль (`a`) по-прежнему режет текст сообщения. Это осознанная цена (безопасность важнее читаемости), имена типов при этом не страдают (п. 3).

### 2. Кодирование и порядок замен

- Варианты каждого значения: `raw`, `quote(v, safe="")`, `quote_plus(v)` — как сейчас для пароля. `make_url` отдаёт декодированные значения, а драйвер и SQLAlchemy печатают их в любом виде. Для IPv6 скобки отдельно не добавляются: `2001:db8::1` внутри `[2001:db8::1]` находится как токен (`[` и `]` — не `\w`), скобки остаются вокруг `***` (E-6 допускает).
- Порядок: (1) все `substrings`, длинные первыми; (2) все `tokens` **одним** регулярным выражением `(?<!\w)(?:t1|t2|…)(?!\w)`, где альтернативы отсортированы по убыванию длины и экранированы `re.escape`. Один проход: в каждой позиции побеждает самое длинное совпадение (Python `re` берёт первую подходящую альтернативу), а уже вставленные `***` повторно не сканируются. Так `waiter_db` не превращается в `***_db`, а `db.example.com` — в `***.example.com` при базе `db` (E-2, E-3). (3) Общий шаблон IP-литералов (п. 4).
- Последовательные `str.replace` для токенов отвергнуты: результат зависит от порядка, а короткое значение может разрезать длинное.

### 3. Границы токена и имена типов исключений

- **Граница — `\w` (Unicode: буквы, цифры, `_`).** Токен маскируется, если непосредственно перед ним и после него нет `\w`. Точка, дефис, кавычки, `@`, `:`, `/`, скобки, пробел считаются границами. Следствия:
  - пользователь `u` и база `x` не задевают `RuntimeError` и обычные слова (E-4); существующие ожидания `test_describe_error_masks_url_encoded_password` (`"RuntimeError: raw ***, quoted ***"`) и `test_describe_error_follows_implicit_context_once` остаются верными;
  - порт `5432` не маскируется внутри `15432`, маскируется в `('***', 5432)`, `:5432/`, `port 5432`;
  - база `waiter` в `ai-waiter` (`application_name` из `SERVER_SETTINGS`) даёт `ai-***` — допустимо (E-4);
  - URL целиком: `postgresql+asyncpg://***:***@***:***/***` (E-10).
- **Регистр.** Токены сравниваются с `re.IGNORECASE`: DNS не различает регистр, драйвер и пользователь могут напечатать хост иначе, а лишнее маскирование безопасно. Пароль (подстрока) — с учётом регистра: другой регистр — уже не тот пароль.
- **Имена типов не маскируются.** Сейчас `_mask` применяется к уже склеенной строке `Type: message <- Type: message`. По новой схеме `describe_error` один раз получает `_UrlSecrets` (или `UNPARSABLE_URL_TEXT`), и `_mask_message` применяется **к каждому `str(exception)` отдельно**. `type(...).__name__` и разделитель ` <- ` подставляются как есть. Имя класса задаётся кодом, а не конфигурацией, и о секрете ничего не говорит. Поэтому при пользователе `OSError` или `Error` тип остаётся виден: `OSError: auth failed for user "***"`. Внутри текста сообщения такое значение маскируется как обычный токен.
- **Простая подстрока для токенов отвергнута**: `u` → `R***ntimeError`, `waiter` → `ai-***` в любом слове, `5432` → `1***`. **Граница по `[A-Za-z0-9_-]` (дефис внутри слова) отвергнута**: `ai-waiter` не маскировался бы, но тогда не маскировался бы и `waiter-` в выводе драйвера. Остаточный риск правила `\w`: пользователь `waiter` в слитном тексте `waiterdb` не маскируется. Драйверы печатают значения в кавычках или через разделители, так что риск низкий; его снижает и маскирование IP (п. 4).

### 4. IPv6, домен и разрешённый IP

- IPv6 из `[2001:db8::1]:5433` → `make_url` даёт `2001:db8::1`, маскируется как токен. Домен маскируется целиком (точки внутри значения — часть токена, а не граница, потому что сравнивается всё значение).
- **Разрешённый IP — в scope (spec, E-13 и «Решённые вопросы», п. 1).** В URL указан домен, а asyncpg печатает адрес после DNS: `Connect call failed ('192.0.2.10', 5432)`. Для VPS с доменом (CLAUDE.md: «внешний адрес — всегда домен») это самый частый путь утечки, по значениям из URL его не закрыть. Поэтому последний шаг `_mask_message` — `_mask_ip_literals`: любой литерал IPv4/IPv6 в тексте сообщения заменяется на `***`.
  - Кандидаты ищутся шаблонами: IPv4 — `(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d)`, IPv6 — последовательность hex-групп с минимум двумя `:`, с необязательным встроенным IPv4. Затем кандидат подтверждается `ipaddress.ip_address`. `12:30:45`, `1.2.300.4`, `v1.2` не трогаются. У IPv6-кандидата перед проверкой отбрасывается хвостовое одиночное `:` (`2001:db8::7:` в `…::7: x` → проверяется `2001:db8::7`). Зона `%eth0` остаётся в тексте.
  - Цена: в тексте ошибки БД замаскируется и посторонний IP-литерал (например, четырёхчастная версия `1.2.3.4`). Для диагностики ошибки подключения адрес сервера оператору не нужен: он знает свой `DATABASE_URL`. Безопасность важнее.
  - Шаблон применяется только внутри `describe_error`, глобального фильтра логов нет.
- Хост в виде пути Unix-сокета (`?host=/var/run/postgresql`) маскируется как токен; путь `…/.s.PGSQL.5432` в тексте драйвера даёт `***/.s.PGSQL.5432`.

### 5. Порт по умолчанию

Не маскируется (E-1). Его нет в `DATABASE_URL`, а `5432` общеизвестен и о сервере ничего не говорит. Маскирование `5432` во всём тексте задело бы посторонние числа. Явно указанный порт (в URL или в `?port=`, `?host=h:p`) маскируется, даже если это `5432`. Переменные `PGHOST`/`PGPORT`/`PGUSER` окружения процесса, которые asyncpg читает при отсутствии значений в URL, проект не использует (конфигурация только через `DATABASE_URL`). IP из `PGHOST` закрывает п. 4, остальное — вне scope.

### 6. Неразбираемый URL

Не меняется (FR-4, E-11). Если `make_url` бросает исключение (`ArgumentError`, `ValueError` нечислового порта, в том числе мультихост с портами в netloc `h1:5432,h2:5433`), `describe_error` возвращает `UNPARSABLE_URL_TEXT`, текст ошибки не показывается. Константа и её текст прежние. Fail-closed распространяется и на `_url_secrets`: исключение внутри него обрабатывается так же, как ошибка `make_url`, и даёт `UNPARSABLE_URL_TEXT`. На разобранном `URL` оно не ожидается.

### 7. Производительность

Разбор URL и сборка регулярного выражения выполняются при каждом вызове `describe_error`, только на пути ошибки (NFR-4). Кэш в `__init__` допустим, но не нужен: ошибки БД редки, а URL неизменен на всё время жизни `Database`.

---

## Security

- **Что закрывается.** Известное ограничение LOW (security review #60/#71, с #7): в тексте `describe_error` больше нет хоста (в том числе разрешённого IP), явного порта, пользователя, базы и пароля. Это относится к паролю и пользователю и из query, и из userinfo. Значит, их нет и в WARNING `Database.ping`, `_check` (`/health/ready`), `DEMO_CHECK_FAILED`, stderr сида (код 1) и отчёте `menu_sync`.
- **Остаточные риски (принимаются).**
  - Значение, слитое с буквами или цифрами (`waiterdb` при пользователе `waiter`), не маскируется (п. 3).
  - Домен из DNS-ошибки, отличный от указанного (CNAME, который драйвер напечатал), не маскируется. asyncpg печатает исходное имя, риск теоретический.
  - Порт по умолчанию виден (п. 5).
- **Вне scope** (без изменений, отдельные задачи при необходимости):
  - `app/menu_sync/__main__.py::mask_url_passwords` — маскирует только пароль в строках `схема://user:пароль@хост` в сообщениях argparse. Там это URL, который пользователь сам ввёл в `--database-url` в своей консоли (открытый вопрос 1);
  - `REDIS_URL` — для Redis в `_check` уже выводятся только имена классов (`_exception_names`, #71);
  - ключи коннекторов и модели.
- **Traceback.** `exc_info` по-прежнему не передаётся (#71), маскирование касается только текста `describe_error`.
- Tenant-изоляция, роли, rate-limit, prompt injection — не затронуты.

---

## Module Structure (code stubs)

```
backend/app/db/session.py
  _UrlSecrets(substrings: tuple[str, ...], tokens: tuple[str, ...])   # dataclass(frozen, slots) — СТАБ
  _url_secrets(url: URL) -> _UrlSecrets                              # п. 1–2, 5 — СТАБ (NotImplementedError)
  _mask_message(message: str, secrets: _UrlSecrets) -> str           # п. 2–4 — СТАБ
  _mask_ip_literals(text: str) -> str                                # п. 4 — СТАБ
  Database.describe_error                                            # developer: make_url + _url_secrets один раз
                                                                     #   (ошибка → UNPARSABLE_URL_TEXT), затем
                                                                     #   f"{name}: {_mask_message(msg, secrets)}" по цепочке
  Database._mask                                                     # developer: удалить или оставить тонкой обёрткой;
                                                                     #   импорты quote/quote_plus переходят в _url_secrets
```

Стабы к `describe_error` и `_mask` **не подключены**: текущее поведение и все тесты зелёные. Developer реализует функции и переключает `describe_error` на них. Регулярные выражения IP — константы модуля (`re.compile`).

Docstring/комментарии «пароль → `***`» → «детали подключения → `***`» (без изменения кода):
- `session.py`: модульный docstring при необходимости, `Database.ping`, `Database.describe_error`;
- `app/api/health.py`: модульный docstring, `_check`;
- `app/api/demo_data.py`: тексты про `describe_error`;
- `app/seed/__main__.py` и `app/menu_sync/__main__.py`: если упоминают «пароль замаскирован».

## Тесты

**Unit (без маркеров, Windows и Linux), `backend/tests/test_db_session.py`.** Заготовки уже добавлены с `pytest.mark.skip(reason="#73: реализация в фазе разработки")`, developer снимает skip:
- `test_describe_error_masks_all_url_parts` (AC-1);
- `test_describe_error_masks_whole_url_leaving_scheme` (E-10);
- `test_describe_error_keeps_exception_type_names` (п. 3: пользователь `OSError`);
- `test_describe_error_masks_query_hosts_ports_and_password` (E-7, `?password=`);
- `test_describe_error_masks_resolved_ip_literals` (E-13, `12:30:45` не тронут).

Developer/tester дописывают:
- E-1 — порт по умолчанию не маскируется;
- E-2, E-3 — `waiter`/`waiter`, `waiter`/`waiter_db`, хост `db.example.com` + база `db`;
- E-4 — `ai-waiter` → `ai-***`, `15432` при порте `5432` не тронут;
- E-5 — регистр хоста;
- E-6 — `[2001:db8::1]`;
- E-8 — URL без пароля;
- E-9 — закодированные пользователь/база (`svc%2Bwaiter`);
- netloc `192.0.2.10,192.0.2.11`, `?host=/var/run/postgresql`;
- unit-тесты `_mask_ip_literals` (IPv4, IPv6, `::1`, хвостовое `:`, невалидные кандидаты);
- оракул: для набора URL каждое значение `host`/`port`/`user`/`password`/`database` из `PGDialect_asyncpg().create_connect_args(make_url(u))[1]` попадает в `_url_secrets` (`str(port)` — в `tokens`).

Существующие тесты без изменения ожиданий:
- `test_describe_error_masks_url_encoded_password`, `test_describe_error_without_password_and_empty_message`, `test_describe_error_follows_implicit_context_once`, `test_describe_error_with_unparsable_url_hides_text` (E-11, E-12);
- `test_ping_failure_returns_false_and_masks_password` — дополнить проверкой, что `db.invalid` и `ai_waiter` не попали в WARNING.

Дополнить проверками отсутствия хоста и пользователя:
- `tests/test_health.py`: `test_ready_with_real_database_object_masks_password_in_log`, `test_check_database_exception_logged_masked_without_traceback`;
- `tests/test_demo_data.py::test_exception_is_unknown_with_masked_password`;
- `tests/test_seed.py::test_database_error_in_target_check_is_exit_1_without_password`.

**db (маркер `db`).** По желанию: `tests/db/test_seed.py::test_cli_wrong_password_is_not_shown` и `tests/db/test_health_db.py` с неверным паролем — дополнительно проверить, что хост и пользователь из `TEST_DATABASE_URL` не попали в stderr и лог. Учесть, что в CI хост — `localhost`/`127.0.0.1`: `127.0.0.1` маскируется шаблоном IP, `localhost` — как токен.

`tests/doubles.py::FakeDatabase.describe_error` не меняется: у двойника нет URL.

## Документы, которые обновить после исправления (doc-sync/developer после G4)

- `docs/specs/feature-60-demo-data-guard.md`, NFR-1 — абзац «Известное ограничение…» пометить закрытым в #73; E-6 — «без пароля» → «без деталей подключения».
- `docs/arch/feature-60-demo-data-guard.md`, Security — пункт «Известное ограничение (security review #60, LOW, существует с #7)» закрыт в #73; в пункте про `_check` убрать «ограничение по хосту/порту — см. пункт выше, bug #73».
- `docs/test-cases/feature-60-demo-seed-guard.md`, TC-60-006 — в ожидаемом результате: в stderr нет хоста, порта, пользователя и базы; Notes — ограничение закрыто #73; TC-60-010 (шаг 7, ссылка на ограничение NFR-1).
- `docs/test-cases/traceability-tc.md` (строка TC-60-006), `docs/traceability.md` (строки #73 и TC-60-006).
- Docstring `Database.describe_error`, `Database.ping`, `app/api/health.py` (см. Module Structure).
- Этот arch doc — раздел «Реализация» после G4.

## Открытые вопросы

1. **(Не блокирует.)** Нужна ли отдельная задача на `menu_sync.mask_url_passwords`: в сообщении argparse хост из введённого `--database-url` остаётся. Рекомендация — не делать: значение пользователь сам ввёл в свою консоль, в лог службы оно не попадает.
2. **(Не блокирует.)** Маскирование любого IP-литерала (п. 4) шире, чем требует spec (в spec E-13 был открытым вопросом и после G2 переведён в scope). Если пользователь предпочтёт маскировать только значения из URL, `_mask_ip_literals` исключается из `_mask_message`, а E-13 переходит в «известные ограничения».
