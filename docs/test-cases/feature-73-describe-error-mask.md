# Test Cases: Story #73 — Маскирование DATABASE_URL в describe_error

**Feature:** #73 (type:bug, сам issue и есть story) — `describe_error` раскрывает детали подключения из DATABASE_URL
**Spec:** docs/specs/feature-73-describe-error-mask.md (AC-1, FR-1…FR-5, NFR-1…NFR-4, E-1…E-13)
**Arch:** docs/arch/feature-73-describe-error-mask.md (решения 1–6, раздел «Реализация»)
**Created:** 2026-11-04

Обозначения: **Авто** — тест в `backend/tests/...` (маркер `db` — `backend/tests/db/`, нужен PostgreSQL); **Ручной** — шаги вручную; **Статус прогона** — на 2026-11-04: локально (Windows) unit-набор `uv run pytest -q -m "not db and not scaled"` — 1496 passed (с тестами G5), покрытие `app/db/session.py` 100% строк и ветвей; db-тесты локально (PostgreSQL 16) — 286 passed; Linux — CI PR #74 зелёный. Пути тестов ниже — относительно `backend/`.

AC-1 (= AC issue #73): **Given** `DATABASE_URL` = `postgresql+asyncpg://waiter_user:pw-s3cret@192.0.2.10:5433/waiter_db`, текст ошибки драйвера содержит хост, порт, пользователя, базу и пароль / **When** вызывается `Database.describe_error` / **Then** все пять значений заменены на `***`, имя типа и остальной текст сохранены.

Решения, от которых зависят ожидаемые результаты (arch #73):
- Решение 1: пароль (`url.password`, `?password=`) — **подстрока** без границ, с учётом регистра; хост (целиком и по частям через `,`, формы `h:p`, `[v6]:p`), явный порт, пользователь, база, `?host/port/user/database/passfile` — **токены**. Прочие параметры query (`ssl`, `prepared_statement_cache_size`) не маскируются.
- Решение 2: варианты каждого значения — raw, `quote(v, safe="")`, `quote_plus(v)`; токены — одним regex, длинные первыми.
- Решение 3: граница токена `(?<!\w)…(?!\w)`, `re.IGNORECASE`; маскируется каждое `str(exc)` отдельно, имена типов и ` <- ` подставляются как есть.
- Решение 4: любые литералы IPv4/IPv6 в тексте маскируются (кандидат подтверждается `ipaddress.ip_address`).
- Решение 5: порт по умолчанию не маскируется, явно указанный (даже `5432`) — маскируется.
- Решение 6: ошибка `make_url` или `_url_secrets` → `UNPARSABLE_URL_TEXT` (fail-closed).
- Security review #73 (LOW), исправлено в той же ветке: a2688fd — все участки (пароль, токены, IP) ищутся по исходному тексту, пересекающиеся объединяются и заменяются за один проход (`_replace_spans`), хвостов `ad***`, `192.0.2.***` нет; 0c0ac1c — копия текста с вырезанным паролем для поиска токенов и IP собирается за один проход.

Все адреса и значения в TC — из документационных диапазонов (`192.0.2.0/24`, `198.51.100.0/24`, `2001:db8::/32`, `*.example.com`, `*.invalid`) и вымышленные.

---

## TC-73-001: Все значения из DATABASE_URL заменены на `***`, тип и текст сохранены (AC-1)

**Priority:** Critical
**Type:** Security / Functional
**AC:** AC-1; FR-1, FR-2; NFR-1
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_masks_all_url_parts`; запись WARNING `Database.ping` — `tests/test_db_session.py::test_ping_failure_returns_false_and_masks_password` (нет `pw-s3cret`, `db.invalid`, `ai_waiter`; `exc_info is None`; `component="database"`).
**Статус прогона:** PASS

### Preconditions
- `Database` создан с `DATABASE_URL` = `postgresql+asyncpg://waiter_user:pw-s3cret@192.0.2.10:5433/waiter_db`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `describe_error(OSError('connection to server at "192.0.2.10", port 5433 failed: password pw-s3cret rejected for user "waiter_user" database "waiter_db"'))` | Ровно `OSError: connection to server at "***", port *** failed: password *** rejected for user "***" database "***"` |
| 2 | Проверить результат | Нет `192.0.2.10`, `5433`, `waiter_user`, `pw-s3cret`, `waiter_db`; кавычки, запятые и слова сообщения на месте |
| 3 | `ping` с движком, который бросает `ConnectionError("password pw-s3cret rejected")` с причиной `OSError` с полным URL | `ping` → `False`; одна запись WARNING: `ConnectionError: password *** rejected` и `OSError: cannot connect to postgresql+asyncpg://***:***@***:***/***`; нет хоста `db.invalid` и пользователя/базы `ai_waiter` |

---

## TC-73-002: Строка подключения целиком — остаются только схема и драйвер (E-10)

**Priority:** Critical
**Type:** Security
**AC:** E-10; FR-1, FR-2 (схема и драйвер не секретны)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_masks_whole_url_leaving_scheme`, `::test_ping_failure_returns_false_and_masks_password`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL из TC-73-001; `describe_error(RuntimeError("cannot connect to <тот же URL>"))` | `RuntimeError: cannot connect to postgresql+asyncpg://***:***@***:***/***` |
| 2 | Проверить схему | `postgresql+asyncpg` не замаскирован; разделители `://`, `:`, `@`, `/` на месте |

---

## TC-73-003: Хост — домен, регистр, IPv6 в скобках, список хостов, путь сокета (E-5, E-6)

**Priority:** High
**Type:** Security / Functional
**AC:** FR-1 (хост: домен, IPv4, IPv6); E-5, E-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_tokens_are_case_insensitive_password_is_not`, `::test_describe_error_masks_ipv6_host_in_brackets`, `::test_describe_error_masks_multihost_netloc`, `::test_describe_error_masks_unix_socket_path`, `::test_describe_error_does_not_mask_default_port` (домен в кавычках).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL `…://Waiter:Pw-Secret@db.example.com/x`; сообщение `DB.Example.COM WAITER Pw-Secret pw-secret` | `OSError: *** *** *** pw-secret` — хост и пользователь без учёта регистра, домен целиком (точки — часть значения); пароль с учётом регистра (`pw-secret` — не тот пароль, остаётся) |
| 2 | URL `…://w:pw@[2001:db8::1]:5433/x`; сообщение `at [2001:db8::1]:5433 and 2001:DB8::1 port 5433` | `OSError: at [***]:*** and *** port ***` — адрес в скобках и без, скобки вокруг `***` допустимы |
| 3 | URL `…://w:pw@192.0.2.10,db2.example.com:5433/x`; сообщение `hosts 192.0.2.10,db2.example.com; failed db2.example.com:5433` | `OSError: hosts ***; failed ***:***` — список целиком и каждый хост отдельно |
| 4 | URL `…://w:pw@/x?host=/var/run/postgresql`; сообщение `connect to /var/run/postgresql/.s.PGSQL.5432 failed` | `OSError: connect to ***/.s.PGSQL.5432 failed` — путь сокета маскируется, имя файла сокета остаётся |

---

## TC-73-004: Порт — явный маскируется (даже 5432), по умолчанию — нет (E-1)

**Priority:** High
**Type:** Functional / Security
**AC:** FR-1 (порт, если явно указан); E-1; решение 5
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_does_not_mask_default_port`, `::test_describe_error_masks_explicit_default_port`, `::test_describe_error_token_boundaries` (`15432` при порте `5432` не тронут).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL `…://waiter_user:pw@db.example.com/waiter_db` (порт не указан); сообщение `server "db.example.com" port 5432: user "waiter_user" db "waiter_db"` | `OSError: server "***" port 5432: user "***" db "***"` — порт по умолчанию остаётся, остальное замаскировано |
| 2 | URL `…://w:pw@db.example.com:5432/x`; сообщение `port 5432 failed` | `OSError: port *** failed` |
| 3 | URL с явным `:5432`; сообщение содержит `port 15432` | `15432` не меняется (граница токена) |

---

## TC-73-005: Параметры подключения из query — host, port, user, password, database, passfile (E-7)

**Priority:** Critical
**Type:** Security
**AC:** FR-1 (query-параметры asyncpg); E-7; решение 1
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_masks_query_hosts_ports_and_password`, `::test_describe_error_masks_query_user_database_and_passfile`, `::test_describe_error_does_not_mask_other_query_values`, `::test_url_secrets_cover_asyncpg_connect_args[*]` (оракул по `PGDialect_asyncpg().create_connect_args`, 8 URL), `::test_describe_error_masks_query_ipv6_host_without_port` (`?host=[v6]` без порта, G5).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL `…://w@/x?host=192.0.2.10:5432&host=[2001:db8::2]:5434&password=q-pw` (повтор ключа, формы `h:p` и `[v6]:p`); сообщение `h 192.0.2.10:5432 [2001:db8::2]:5434 port 5434 q-pw` | Начинается с `OSError: h `; нет `192.0.2.10`, `5432`, `2001:db8::2`, `5434`, `q-pw` (`?password=` раньше не маскировался вовсе) |
| 2 | URL `…://w@db.example.com/x?user=other_user&database=other_db&port=6543&passfile=pgpass.conf`; сообщение `other_user other_db 6543 pgpass.conf ssl` | `OSError: *** *** *** *** ssl` |
| 3 | URL `…?ssl=require&prepared_statement_cache_size=0`; сообщение `ssl require, cache 0` | Без изменений: прочие параметры query не маскируются |
| 4 | Оракул: для каждого из 8 URL (`ORACLE_URLS`) взять `host`/`port`/`user`/`password`/`database`, которые диалект asyncpg передаёт драйверу | Каждый пароль — в `substrings`, каждое остальное значение (`str(port)`) — в `tokens`; проверено не меньше 3 значений на URL |

---

## TC-73-006: URL-кодированные пароль, пользователь и база (E-9)

**Priority:** High
**Type:** Security
**AC:** FR-1 («и в исходном виде, и в URL-кодированном»); E-9
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_masks_url_encoded_password` (тест до #73, ожидание не менялось), `::test_describe_error_masks_url_encoded_user_and_database`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL `…://u:p%40ss%2Fword@db.invalid/x`; сообщение `raw p@ss/word, quoted p%40ss%2Fword` | Ровно `RuntimeError: raw ***, quoted ***` |
| 2 | URL `…://svc%2Bwaiter:pw@db.example.com/my%2Fdb`; сообщение `svc+waiter svc%2Bwaiter my/db my%2Fdb` | `OSError: *** *** *** ***` |

---

## TC-73-007: Литералы IPv4/IPv6 в тексте — разрешённый IP маскируется, время и версии — нет (E-13)

**Priority:** Critical
**Type:** Security
**AC:** E-13; FR-1 (IP-литералы); решение 4
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_masks_resolved_ip_literals`, `::test_mask_ip_literals[*]` (13 параметров), `::test_describe_error_with_password_only_masks_password_and_ip_literals` (в URL только пароль — токенов нет, IP всё равно маскируются; G5).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL с доменом `…://w:pw@db.example.com/x`; сообщение `Connect call failed ('192.0.2.10', 5432) [2001:db8::1] at 12:30:45` | `OSError: Connect call failed ('***', 5432) [***] at 12:30:45` |
| 2 | `_mask_ip_literals`: `at 192.0.2.10:5432`, `('198.51.100.7', 5432)`, `[2001:db8::1]:5433`, `host ::1 port` | `at ***:5432`, `('***', 5432)`, `[***]:5433`, `host *** port` |
| 3 | Хвосты: `addr 2001:db8::7: refused`, `mapped ::ffff:192.0.2.10.`, `zone fe80::1%eth0`, `seq 192.0.2.4.5` | `addr ***: refused`, `mapped ***.` (IPv4-mapped целиком), `zone ***%eth0`, `seq ***.5` |
| 4 | Не IP: `time 12:30:45`, `bad 1.2.300.4`, `v1.2 and 10.0`, `ab:cd:ef deadbeef`, `no ip here` | Без изменений |

### Notes
Цена решения 4: замаскируется и посторонний литерал вида IP (например, четырёхчастная версия `1.2.3.4`) — принято arch #73.

---

## TC-73-008: Имена типов, разделитель ` <- ` и цепочка причин (FR-2, FR-5, E-12)

**Priority:** High
**Type:** Functional (регрессия)
**AC:** FR-2; FR-5 (обход цепочки по одному разу, без зацикливания); E-12; решение 3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_keeps_exception_type_names`, `::test_describe_error_masks_each_message_in_cause_chain`, `::test_describe_error_follows_implicit_context_once`, `::test_describe_error_without_password_and_empty_message` (два последних — тесты до #73, ожидания не менялись).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL `…://OSError:pw@db.example.com/x`; `describe_error(OSError('auth failed for user "OSError"; RuntimeErrorx'))` | `OSError: auth failed for user "***"; RuntimeErrorx` — имя типа не маскируется, значение внутри сообщения маскируется, `RuntimeErrorx` не задет |
| 2 | URL из TC-73-001; `ConnectionError('user "waiter_user"')` с `__cause__ = OSError("at 192.0.2.10")` | `ConnectionError: user "***" <- OSError: at ***` — каждое сообщение маскируется отдельно, разделитель как есть |
| 3 | `RuntimeError("second")` с неявным `__context__` `KeyError("first")`, у которого `__context__` замкнут на исходное | `RuntimeError: second <- KeyError: 'first'` — цикл обходится один раз |
| 4 | URL без пароля; `TimeoutError` без сообщения, `raise … from None` | Ровно `TimeoutError` (только имя типа, подавленный контекст не выводится) |

---

## TC-73-009: Границы токенов и пересекающиеся значения — без хвостов (E-2, E-3, E-4)

**Priority:** High
**Type:** Functional / Negative
**AC:** E-2, E-3, E-4; FR-2 (обычные слова не портятся); решения 2, 3
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_overlapping_values_masked_without_tails[*]` (3 параметра), `::test_describe_error_token_boundaries`, `::test_describe_error_masks_url_encoded_password` (пользователь `u`, база `x`: `RuntimeError` не задет).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | E-2: пользователь и база `waiter`; сообщение `user waiter db waiter` | `RuntimeError: user *** db ***` |
| 2 | E-3: пользователь `waiter`, база `waiter_db`; сообщение `user "waiter" database "waiter_db"` | `RuntimeError: user "***" database "***"` — нет `***_db` |
| 3 | E-3: хост `db.example.com`, база `db`; сообщение `host db.example.com database db` | `RuntimeError: host *** database ***` — нет `***.example.com` |
| 4 | E-4: URL `…://u:pw@db.example.com:5432/waiter`; сообщение `app ai-waiter port 15432 user u in RuntimeErrorU waiterdb` | `RuntimeError: app ai-*** port 15432 user *** in RuntimeErrorU waiterdb` — токен через дефис маскируется; значение внутри числа и слова — нет |
| 5 | Пользователь `u`, база `x`; сообщение с `RuntimeError` | Имя типа и слова не превращаются в `R***ntimeError` |

---

## TC-73-010: Пароль внутри других значений — без хвостов `ad***`, `192.0.2.***` (security review #73, LOW)

**Priority:** High
**Type:** Security / Negative (регрессия исправления)
**AC:** NFR-1; FR-1; исправления a2688fd (участки объединяются, замена за один проход) и 0c0ac1c (копия без пароля за один проход)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_password_inside_other_values_leaves_no_tails[*]` (4 параметра).
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL `…://admin:min@db.example.com/x`; сообщение `role "admin" failed` | `RuntimeError: role "***" failed` — не `role "ad***" failed` |
| 2 | URL `…://u:10@192.0.2.10/x`; сообщение `Connect call failed ('192.0.2.10', 5432)` | `RuntimeError: Connect call failed ('***', 5432)` — не `192.0.2.***` |
| 3 | URL `…://admin:pw-s3cret@db.example.com/x`; сообщение `adminpw-s3cret` (пароль вплотную к пользователю) | `RuntimeError: ******` — токен `admin` найден в копии, где пароль вырезан; ни `admin`, ни пароля в тексте нет |
| 4 | URL `…://u:example@db.example.com/x`; сообщение `host db.example.com` | `RuntimeError: host ***` — пароль внутри домена не разрезает его, домен замаскирован целиком |

### Notes
Ожидаемые результаты шагов 1–2 до a2688fd были бы `ad***` и `192.0.2.***` (последовательные замены). 0c0ac1c — оптимизация сборки копии без пароля; поведение то же, проверяется теми же параметрами.

---

## TC-73-011: URL без пароля — хост, пользователь и база всё равно маскируются (FR-3, E-8)

**Priority:** High
**Type:** Security / Negative
**AC:** FR-3; E-8
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_url_without_password`, `::test_describe_error_without_password_and_empty_message`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL `…://waiter@db.example.com/waiter_db`; сообщение `user "waiter" on db.example.com/waiter_db` | `OSError: user "***" on ***/***` (до #73 текст возвращался без изменений) |
| 2 | Тот же URL; сообщение `timeout expired` | `OSError: timeout expired` — сообщение без значений не меняется |

---

## TC-73-012: Неразбираемый URL и сбой разбора — UNPARSABLE_URL_TEXT, текст скрыт (FR-4, E-11)

**Priority:** Critical
**Type:** Security / Negative
**AC:** FR-4; E-11; решение 6 (fail-closed)
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_db_session.py::test_describe_error_with_unparsable_url_hides_text` (тест до #73, ожидание не менялось), `::test_describe_error_url_secrets_failure_is_fail_closed`; вывод CLI меню — `tests/test_menu_sync_cli.py::test_unparsable_database_url_is_exit_1_without_password`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | URL с нечисловым портом `…://u:Unparsable-Pa55@db.invalid:port/x`; сообщение содержит пароль и хост | Ровно `UNPARSABLE_URL_TEXT`; пароля нет |
| 2 | `_url_secrets` подменён функцией, которая бросает `RuntimeError`; URL из TC-73-001; сообщение `pw-s3cret` | `UNPARSABLE_URL_TEXT` |
| 3 | Текст константы `UNPARSABLE_URL_TEXT` | Прежний: «строка подключения DATABASE_URL не разбирается (проверьте её формат), текст ошибки скрыт» |

---

## TC-73-013: Вызывающие — health, demo_data, seed, menu_sync выводят текст без деталей подключения (FR-5, NFR-1)

**Priority:** Critical
**Type:** Security (интеграция с вызывающими)
**AC:** FR-5 (контракт `describe_error(exc) -> str` и места вызова прежние); NFR-1
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_health.py::test_ready_with_real_database_object_masks_password_in_log`, `::test_check_database_exception_logged_masked_without_traceback`; `tests/test_demo_data.py::test_exception_is_unknown_with_masked_password`; `tests/test_seed.py::test_database_error_in_target_check_is_exit_1_without_password`; `tests/test_menu_sync_cli.py::test_import_database_error_hides_password`, `::test_database_error_text_is_escaped_and_limited` (обрезка `safe_text` после маскирования); с БД — `tests/db/test_seed.py::test_cli_wrong_password_is_not_shown`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `/health/ready` с настоящим `Database` и движком, бросающим `ConnectionRefusedError` с полным URL (`ai_waiter:pw-s3cret@db.invalid`) | 503, `database: "fail"`; в логе `ConnectionRefusedError`, нет `pw-s3cret`, `db.invalid`, `ai_waiter` |
| 2 | `_check`: `ping` настоящего `Database` бросает то же исключение | Одна запись `app.api.health`, `component="database"`, `exc_info is None`, текст через `describe_error` без хоста и пользователя |
| 3 | Проверка демо (`DemoDataMonitor.refresh`) падает с DSN в тексте | `UNKNOWN`; WARNING `DEMO_CHECK_FAILED…` с `ConnectionRefusedError` и `***`; нет `pw-s3cret`, `db.invalid` |
| 4 | Сид: проверка целевой базы падает с `connection to dev:<пароль>@db.invalid/demo_dev failed` | Код 1; в stderr `connection to ***:***@***/*** failed` и подсказка `alembic upgrade head`; нет пароля, `db.invalid`, `demo_dev` |
| 5 | `python -m app.menu_sync import`: сервис падает с `ConnectionRefusedError` с паролем и хостом | Код ошибки; stderr `Не удалось выполнить импорт меню: ConnectionRefusedError…`, `***`, пароля нет; длинный текст обрезан `MAX_SHOWN_ERROR_CHARS` с `…` после маскирования |
| 6 | db: сид с неверным паролем в `--database-url` на настоящий PostgreSQL | Код 1; ни пароля, ни хоста, ни пользователя из `TEST_DATABASE_URL` (целым токеном, без учёта регистра) в stdout/stderr |
| 7 | Сигнатура и места вызова | `describe_error(exc) -> str`; вызовы в `app/api/health.py`, `app/api/demo_data.py`, `app/seed/__main__.py`, `app/menu_sync/__main__.py` не менялись (проверено чтением кода, менялись только docstring) |

### Notes
- `tests/test_menu_sync_cli.py::test_import_database_error_hides_password` проверяет отсутствие пароля и хоста `db.invalid` в stderr и наличие `***` (проверка хоста добавлена на G5).
- В CI хост `TEST_DATABASE_URL` — `localhost`/`127.0.0.1`: `localhost` маскируется как токен, `127.0.0.1` — и как токен, и шаблоном IP.

---

## TC-73-014: Переносимость, тестовые адреса и стоимость (NFR-2, NFR-3, NFR-4)

**Priority:** Medium
**Type:** Functional (переносимость, производительность)
**AC:** NFR-2, NFR-3, NFR-4
**E2E Automated:** No
**Автоматизация:** Авто — весь набор `tests/test_db_session.py` без маркеров `db`/`scaled` (матрица CI Windows и Linux); успешный путь — `tests/test_db_session.py::test_ping_ok`, `::test_session_yields_async_session_and_closes_it`, `::test_engine_is_created_lazily_once_with_pool_settings`. Остальное — чтением кода `backend/app/db/session.py`.
**Статус прогона:** PASS (локально Windows: 1496 passed, 2026-11-04; Linux — CI PR #74)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Прогнать `uv run pytest -q -m "not db and not scaled"` на Windows и Linux | PASS на обеих ОС; тесты #73 без маркеров |
| 2 | Проверить импорты и код маскирования | Только стандартная библиотека (`re`, `ipaddress`, `urllib.parse`) и `sqlalchemy.make_url`; нет зависимости от ОС, режима (`single`/`scaled`), Redis и драйвера |
| 3 | Проверить адреса в тестах #73 | Только `192.0.2.0/24`, `198.51.100.0/24`, `2001:db8::/32`, служебные (`::1`, `fe80::1`), `*.example.com`, `*.invalid`; невалидные кандидаты (`1.2.300.4`) |
| 4 | Проверить, где вызываются `make_url`/`_url_secrets` | Только в `describe_error` (путь ошибки); `ping` при успехе и `session` их не вызывают; кэша и новых переменных окружения нет |

---

## TC-73-015: Регрессия TC-60-006 и TC-60-010 шаг 7 — сид при ошибке БД без деталей подключения

**Priority:** High
**Type:** Security / Negative (регрессия)
**AC:** spec #73 NFR-1 (снимает известное ограничение NFR-1 spec #60); spec #60 E-6
**E2E Automated:** No
**Автоматизация:** Авто — `tests/test_seed.py::test_database_error_in_target_check_is_exit_1_without_password`, `tests/test_seed_guard.py::test_database_error_is_not_caught`, `tests/db/test_seed.py::test_cli_without_schema_fails_with_hint`, `tests/db/test_seed.py::test_cli_wrong_password_is_not_shown`. Ручная часть (шаг 7 TC-60-010) — TC-73-016.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Выполнить TC-60-006 (`docs/test-cases/feature-60-demo-seed-guard.md`) с расширенным ожидаемым результатом | Код 1; в stderr нет пароля, хоста, порта, пользователя и базы; подсказка `alembic upgrade head` |
| 2 | Выполнить автоматизируемую часть TC-60-010 шаг 7 (ошибка соединения) | Код 1; «Не удалось загрузить демо-данные: …»; детали подключения заменены на `***` |

---

## TC-73-016: Ручной — сид на недоступный порт, Windows single — вывод без деталей подключения

**Priority:** High
**Type:** Security / Negative
**AC:** AC-1; NFR-1, NFR-2; E-1 (явный порт), E-13 (IP из ошибки соединения); TC-60-010 шаг 7
**E2E Automated:** No
**Автоматизация:** Ручной. Автоматически покрыто через подменённые исключения (TC-73-013, TC-73-015); ручной прогон проверяет настоящий текст ошибки asyncpg на Windows (`Multiple exceptions: … Connect call failed (…)`, `[WinError 1225]`/`[Errno 10061]`).
**Статус прогона:** PASS (2026-11-04, Windows 11, PowerShell 5.1, коммит 0c0ac1c, `APP_ENV=dev`, `APP_MODE=single`)

### Preconditions
- Windows, PowerShell, `backend/` с `uv sync`; локальный PostgreSQL может быть запущен или нет — используется порт, на котором ничего не слушает (например, `5999`).
- Строка подключения — тестовая (`*_test`), с вымышленным паролем; боевые базы и реальные пароли не использовать.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | В PowerShell из `backend/`: `$env:APP_ENV='dev'; $env:APP_MODE='single'` | — |
| 2 | `uv run python -m app.seed --database-url 'postgresql+asyncpg://waiter_test:Manual-Pa55-73@localhost:5999/waiter_test'` | Процесс завершается |
| 3 | `$LASTEXITCODE` | `1` |
| 4 | Посмотреть stderr | «Не удалось загрузить демо-данные: <ТипОшибки>: …» и подсказка `alembic upgrade head`; имя типа ошибки видно |
| 5 | Проверить stderr на детали подключения | Нет `Manual-Pa55-73`, `localhost`, `5999`, `waiter_test`, `127.0.0.1`, `::1` — вместо них `***` |
| 6 | Повторить шаг 2 с хостом `127.0.0.1` вместо `localhost` | Код 1; ни `127.0.0.1`, ни `5999` в выводе нет |
| 7 | Вернуть переменные окружения | — |

### Фактический результат
Шаги 1–7 выполнены (`backend\.venv\Scripts\python.exe -m app.seed`, `Start-Process` с перенаправлением stdout/stderr). Для `localhost` и для `127.0.0.1`: код 1, stdout пуст, stderr — «Не удалось загрузить демо-данные: ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection» и «Проверьте DATABASE_URL и примените миграции: uv run alembic upgrade head». Поиск по stderr: `Manual-Pa55-73`, `localhost`, `5999`, `waiter_test`, `127.0.0.1`, `::1` не найдены. Знаков `***` в выводе нет: на Windows asyncpg не включает адрес в текст отказа соединения, маскировать было нечего. Маскирование, когда адрес и пользователь в тексте есть, проверяют TC-73-001…TC-73-013 и db-тест `tests/db/test_seed.py::test_cli_wrong_password_is_not_shown` (PASS локально 2026-11-04). Повторный прогон на Linux (там текст ошибки другой) — по желанию на пилоте.

---

## Принятые остаточные риски (не дефекты)

Приняты в arch #73 (раздел Security) и spec #73 («Решённые вопросы»). Тесты фиксируют поведение, где это имеет смысл; это не дефекты и в G5 как FAIL не учитываются.

| # | Риск | Пример | Почему принят | Где видно |
|---|------|--------|---------------|-----------|
| R-1 | Значение, слитое с буквами/цифрами/`_`, не маскируется (граница `\w`) | `waiterdb` при пользователе `waiter` (проверено вызовом 2026-11-04 — остаётся); `RuntimeErrorU` при пользователе `u` | Драйверы печатают значения в кавычках или через разделители; подстрочная замена портила бы обычный текст и имена типов | `test_describe_error_token_boundaries` (`waiterdb` остаётся) |
| R-2 | Пароль, совпадающий с частью слитного слова, оставляет видимый остаток токена | Пользователь `admin`, пароль `min`, в тексте `adminmin` → `ad******` (проверено вызовом `describe_error` 2026-11-04): пароль вырезан подстрокой оба раза, но `admin` в исходном тексте слит с `min`, а в копии без пароля от него остаётся `ad` — токен не находится | Частный случай R-1 (слитное написание). Пароль и большая часть значения скрыты; в отдельном токене (`role "admin"`) хвоста нет — TC-73-010, шаг 1 | `test_describe_error_password_inside_other_values_leaves_no_tails` (раздельные случаи); слитный `adminmin` — без автотеста |
| R-3 | Порт по умолчанию не маскируется | `port 5432` при URL без порта | Значения нет в `DATABASE_URL`, `5432` общеизвестен; маскирование задело бы посторонние числа (решение 5) | `test_describe_error_does_not_mask_default_port` |
| R-4 | Домен из DNS-ошибки, отличный от указанного в URL (CNAME), не маскируется | URL `db.example.com`, драйвер печатает `pg-01.internal.example.com` | asyncpg печатает исходное имя; риск теоретический | — (нет автотеста) |
| R-5 | IPv4 с ведущими нулями не распознаётся шаблоном IP | `192.0.002.10` в тексте при домене в URL | `ipaddress.ip_address` отвергает ведущие нули (Python 3.9.5+), а драйвер их не печатает; если такое значение указано в URL, оно маскируется как токен хоста. Проверено вызовом 2026-11-04: `192.0.002.10` при домене в URL остаётся в тексте | — (нет автотеста) |

Также сознательно шире, чем требует spec: маскируется любой IP-литерал в тексте ошибки БД (TC-73-007, Notes).

---

## Related TCs
- TC-60-006 (сид, ошибка БД — код 1) — ожидаемый результат расширен #73: нет хоста, порта, пользователя и базы; регрессия — TC-73-015
- TC-60-010, шаг 7 (ручной сид на недоступный порт) — повторный ручной прогон после #73 — TC-73-016
- TC-71-003, TC-71-006, TC-71-007 (WARNING `DEMO_CHECK_FAILED` и `_check` через `describe_error`) — известное ограничение из Notes TC-71-003 закрыто #73; проверка — TC-73-013, шаги 2–3
- TC-56-001…TC-56-003 (`/health/ready`, проверка `database`, тело без деталей) — запись в лог при ошибке теперь без деталей подключения (TC-73-013, шаг 1)
- TC-53-005 (ошибки запуска сида без раскрытия пароля) — расширено до всех деталей подключения (TC-73-013, шаг 4)
- TC-66-* (`docs/test-cases/feature-66-menu-cli.md`, CLI `python -m app.menu_sync`, ошибки БД в отчёте) — текст через `describe_error`, обрезка после маскирования (TC-73-013, шаг 5)
