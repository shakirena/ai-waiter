# Architecture: Feature #8 — Импорт меню из CSV/XLSX (файловый коннектор)

**Issue:** #8 · **Milestone:** Этап 1: прототип · **ТЗ:** 4.2 (файловый импорт — вид коннектора, встроен в ядро), 4.4 (`PUT /menu`, `PUT /stoplist`), 4.5 INT-1, INT-2 (INT-3, INT-4 — как потребители), 3.3 FR-16, FR-17, FR-20, FR-21, 9.1–9.2, приложение A.1–A.2, B C-07
**Spec:** `docs/specs/feature-8-menu-import.md` (AC-1…AC-7, FR-1…FR-8)
**Опирается на:** `docs/arch/feature-7-data-model.md` (ADR-7.3, 7.4, 7.7, 7.10–7.12), DEC-001…DEC-010
**Потребители:** #16 (`PUT /menu`, `PUT /stoplist` — тот же сервис применения), #10/#11 (меню гостя и ИИ читают результат), #12 (INT-3 — перепроверка цены по последнему снимку), #18 (коннектор «restoran» — `ai-sync`), #23 (алерт устаревшего меню, очистка журнала), #27–#29 (админка: загрузка файла, FR-20)

Задача #8 — первый путь, по которому меню попадает в ядро. Главное архитектурное решение: **файловый импорт не пишет в таблицы меню сам**. Он превращает файл в тот же снимок, что придёт в `PUT /integration/v1/menu` (#16), и отдаёт его общему сервису применения. Тогда правила INT-1/INT-2 реализуются и тестируются один раз.

Решения пользователя по #7 (комментарий 6095528969) не меняются. Уточнение ADR-7.7 (где хранить хеш снимка) — ADR-8.5, вынесено в открытые вопросы.

---

## ADR-8.1. Единый снимок меню и единый сервис применения — пакет `app/menu_sync`

**Контекст.** ТЗ 4.2: файловый импорт — вид коннектора. ТЗ 4.4: `PUT /menu` — полный снимок. Issue #16 должен применять снимок тем же путём. Если #8 напишет «свой» импорт, правила скрытия, цен, наличия и валюты разойдутся.

**Решение.**
- `app/menu_sync/snapshot.py` — Pydantic-модель `MenuSnapshot {categories[], items[]}`, форма тела `PUT /menu` (позиция — как пример ТЗ 4.4). Деньги — `MoneyStr` из `app/schemas/money.py` (DEC-013). Модель проверяет только форму элементов; межэлементные проверки (дубли, ссылки на категории, валюта заведения) — функция `check_snapshot`, чтобы все ошибки собирались сразу. Точка входа для сырых данных (#16) — `parse_snapshot(data, tenant_currency)`.
- `app/menu_sync/plan.py` — **чистая** функция `plan_menu_sync(current, snapshot)`: сравнение текущего меню со снимком, счётчики, защита от массового скрытия. Без БД: основная логика проверяется unit-тестами на Windows-джобе.
- `app/menu_sync/service.py` — `apply_menu_snapshot(session, tenant_id=…, snapshot=…, source=…)`: lock, хеш, загрузка текущего меню, план, пакетная запись, журнал. Транзакцию не фиксирует (как `apply_seed`).
- `app/menu_sync/files/` — CSV/XLSX → `MenuSnapshot`. Не импортирует SQLAlchemy.
- `app/menu_sync/__main__.py` — CLI.
- #16: роутер `PUT /integration/v1/menu` валидирует тело как `MenuSnapshot` и вызывает `apply_menu_snapshot(source=connector)`. Новой логики применения в #16 нет.

**Почему пакет верхнего уровня, а не `app/core` или `app/services`.** `app/core` — инфраструктура (конфигурация, контейнер, интерфейсы режимов), бизнес-логики там нет (DEC-001). Общего `app/services` пока нет; доменный пакет (`menu_sync`, как `seed`) держит снимок, план, файлы и CLI рядом и даёт простые границы импортов.

**Границы импортов** (дополнить `tests/test_import_boundaries.py` и ruff banned-api):

| Правило | Проверка |
|---|---|
| `openpyxl` — только `app/menu_sync/files/xlsx_reader.py` | `RESTRICTED["openpyxl"]` + `banned-api` с `per-file-ignores` |
| `app/menu_sync/files/**` не импортирует `sqlalchemy`, `app.db`, `app.models` (кроме `app.models.enums`) | новый тест по AST |
| `app/menu_sync/**` не импортирует `fastapi`, `app.api` | новый тест |
| `app/core/**` не импортирует `app.menu_sync` | новый тест |

**Альтернативы.** (а) Импорт пишет в таблицы напрямую, а #16 потом делает рефакторинг. Отклонено: две реализации INT-2 и переделка тестов. (б) Сначала #16, потом файл через HTTP к собственному API. Отклонено: в CLI нужен был бы ключ коннектора, а у файлового импорта ключа нет (ключи — scope #16).

**Последствия.** #8 «съедает» общую часть #16: на долю #16 остаются авторизация по ключу, `hello`/`heartbeat`, `PUT /stoplist`, `PUT /tables` и HTTP-обёртка над `apply_menu_snapshot`. В #16 нужно сослаться на этот ADR.

---

## ADR-8.2. Формат файла: одна плоская таблица, CSV (UTF-8) или XLSX

**Решение.** Одна строка — одна позиция, категория повторяется в каждой строке своих позиций. Такой файл понятнее в Excel и проще выгружается из кассы (один SELECT с JOIN). Отдельный лист или файл для категорий не нужен: пустых категорий в файле не бывает, и это нормально.

### Колонки

Заголовок — первая непустая строка. Имена сравниваются без учёта регистра и пробелов по краям, порядок колонок любой.

| Колонка | Обяз. | Значение → поле снимка |
|---|---|---|
| `category_external_id` | да | текст 1–64 → `categories[].external_id`, `items[].category_external_id` |
| `category_name` | да | текст 1–200 → `categories[].name` (→ `categories.pos_name`) |
| `category_sort_key` | нет | текст ≤ 64, по умолчанию `""` |
| `external_id` | да | текст 1–64; `007` и `7` — разные id |
| `name` | да | текст 1–200 → `menu_items.pos_name` |
| `price_default` | да | деньги, тариф `default` |
| `price_<tier>` | нет | деньги, тариф `<tier>` (`^[a-z][a-z0-9_]{0,31}$`, как `PRICE_TIER_PATTERN`); пустая ячейка — у позиции этого тарифа нет |
| `currency` | нет | ISO 4217; пусто — валюта заведения; другая — ошибка (ADR-8.3) |
| `station` | нет | текст ≤ 100 |
| `sort_key` | нет | текст ≤ 64 |
| `is_available` | нет | `1/0`, `true/false`, `yes/no` (без учёта регистра). **Нет колонки** — наличие не меняется. **Колонка есть** — значение обязательно в каждой строке |

- Колонка, имя которой начинается с `#`, игнорируется (комментарий, служебные поля выгрузки).
- Любая другая неизвестная колонка — ошибка `unknown_column`. Опечатка вроде `is_avalable` или `price_VIP` не должна молча пропасть: иначе стоп-лист или тариф тихо потерялись бы.
- Повтор колонки — `duplicate_column`.

### Значения

- **Текст:** пробелы по краям обрезаются; пустая строка значит «нет значения»; управляющие символы (U+0000–U+001F, U+007F) — ошибка.
- **Деньги:** `8`, `8.5`, `8.50`. Ядро **не округляет**, больше двух знаков после точки — ошибка `too_many_decimals`. Округление `float` кассы — задача выгрузки (A.2, C-07). Запрещены минус, экспонента и разделители тысяч; максимум `99999999.99` (`NUMERIC(10,2)`). Нулевая цена допускается с предупреждением `zero_price`.
- **Десятичная запятая** (`8,50`) допускается только в CSV с разделителем `;`: так сохраняет Excel с русской и азербайджанской локалью. В CSV с `,` запятая — разделитель полей.
- **Числа из XLSX:** `external_id` 7.0 → `"7"`, дробный id — ошибка `invalid_id`. Чтобы сохранить ведущие нули (`007`), колонку в Excel нужно сделать текстовой: это сказано в инструкции к формату. Цена-`float` переводится через `repr` (`8.1` → `Decimal("8.1")`). Шум двоичной дроби (|x − round(x, 2)| < 1e-9, например результат формулы `0.1+0.2`) округляется, остальное с > 2 знаками — ошибка.
- **Даты, время, ошибки Excel (`#N/A`)** в любой колонке — ошибка `invalid_cell_type`.

### CSV

- Кодировка UTF-8, BOM допускается (`utf-8-sig`, так сохраняет Excel «CSV UTF-8»). Другая кодировка — ошибка `encoding` с подсказкой «Сохраните как “CSV UTF-8”». Угадывать cp1251 нельзя: азербайджанские буквы (ə, ş, ğ) там не представимы.
- Разделитель `,` или `;` определяется по заголовку: выбирается тот, при котором находятся обязательные колонки.
- Кавычки — RFC 4180 (модуль `csv`), перенос строки внутри кавычек допустим. Номер строки в сообщениях — номер физической строки, с которой начинается запись.
- Полностью пустые строки пропускаются.

### XLSX

- Читается лист из `--sheet`; если он не задан — лист `menu` (без учёта регистра), иначе первый лист.
- `openpyxl.load_workbook(read_only=True, data_only=True)`: формулы не вычисляются, берётся сохранённое значение. Формула без сохранённого значения (файл собран библиотекой без пересчёта) — ошибка `formula_without_value`.
- `.xls` (старый формат) и `.xlsm`/`vbaProject.bin` (макросы) не поддерживаются: `unsupported_format` с подсказкой «Сохраните как .xlsx».
- Безопасность — ADR-8.7.

### Лимиты

| Лимит | Значение | Где |
|---|---|---|
| Размер файла | 5 МБ | `files.MAX_FILE_BYTES` (проверка `stat` до чтения) |
| Распакованный XLSX | 50 МБ, сжатие члена ≤ 100× | `xlsx_reader` |
| Строк данных | 5000 | `format.MAX_DATA_ROWS` = `snapshot.MAX_ITEMS` |
| Колонок | 50 | `format.MAX_COLUMNS` |
| Длина ячейки | 1000 символов | `format.MAX_CELL_CHARS` |
| Категорий / тарифов на позицию | 500 / 10 | `snapshot` |

Лимиты заданы константами в коде, а не переменными окружения: они не зависят от развёртывания (DEC-002 касается настроек развёртывания).

### Ошибки строк

Собираются все (не только первая). Дубликат `external_id` позиции — ошибка с номерами обеих строк. Одна `category_external_id` с разными `category_name`/`category_sort_key` в разных строках — `category_conflict`. Пустой файл (только заголовок) — `empty_snapshot`.

### Синтетический пример

`backend/tests/fixtures/menu/menu_valid.csv`: 3 категории, 9 позиций, тарифы `default` и `vip` (у части позиций `vip` нет), пустая `currency`, `007`, кавычки с запятой, азербайджанские буквы, все формы `is_available`. Данные выдуманные.

```csv
category_external_id,category_name,category_sort_key,external_id,name,price_default,price_vip,currency,station,sort_key,is_available
10,Salatlar,10,007,Çoban salatı,4.50,5.50,AZN,Mətbəx,10001,1
20,İsti yeməklər,20,101,Dolma,8.00,10.00,AZN,Mətbəx,20001,1
30,İçkilər,30,203,Limonad ev üsulu,2.80,,,Bar,30003,no
```

**Альтернативы.** Два листа или два файла (категории и позиции) — нормализованнее, но CSV так не умеет, и появляется класс ошибок «позиция ссылается на категорию из другого файла». JSON-файл — неудобен для ручной правки. Русские или азербайджанские заголовки колонок — отклонено: заголовки совпадают с полями API (`external_id`, `prices.vip` → `price_vip`) и одинаковы для всех касс.

---

## ADR-8.3. Алгоритм применения снимка

Сопоставление — по `(tenant_id, external_id)`, отдельно для категорий и позиций.

| Ситуация | Категория | Позиция |
|---|---|---|
| Нет в БД, есть в снимке | создать (`created`) | создать, `is_available` = значение снимка или `true` |
| Есть, видима, поля совпали | `unchanged` | `unchanged` |
| Есть, видима, поля изменились | `updated` (`pos_name`, `sort_key`) | `updated` (`pos_name`, `category_id`, `currency`, `station`, `sort_key`, цены) |
| Скрыта, снова в снимке | `is_hidden=false`, `restored` (с обновлением полей) | то же |
| Видима, нет в снимке | `is_hidden=true`, `hidden` | `is_hidden=true`, `hidden`; цены не трогаются |
| Скрыта и нет в снимке | не считается | не считается |

- **Цены.** Тарифы из снимка добавляются или обновляются (`ON CONFLICT (menu_item_id, price_tier)`). Тарифы позиции, которых в снимке нет, **удаляются**. Так `vip` пропадает, когда `price_vip` в кассе обнулили, и стол VIP получает `default` (A.2). Удаление безопасно: заказы и корзины хранят свои снимки цены (`price_at_order`, `price_at_add`, ADR-7.4).
- **`default` обязателен** у каждой позиции снимка (валидатор `SnapshotItem`). CHECK в БД это не проверяет (словарь данных #7).
- **Валюта.** `currency=None` → валюта заведения. Валюта позиции ≠ `tenants.currency` → ошибка `currency_mismatch`, и по ADR-8.4 отклоняется весь снимок. Это строгая форма ADR-7.4 («синхронизация отклоняет позиции»): если пропустить одну позицию, она скрылась бы как пропавшая, что хуже явного отказа.
- **Наличие и стоп-лист (FR-17).** `is_available=None` (в файле нет колонки) — колонка не меняется: файловый коннектор без стоп-листа, переключатель в админке (#28) не перезаписывается при каждом импорте. Значение есть — записывается. `PUT /stoplist` (#16) пишет то же поле и берёт тот же lock (ADR-8.4). При одновременной работе `PUT /menu` с `is_available` и `PUT /stoplist` действует последний пришедший снимок. Коннектор «restoran» шлёт одинаковые данные в обоих (A.2).
- **`menu_item_meta`, `menu_item_allergens`** не трогаются никогда (FR-16), в том числе у скрываемых позиций (INT-2: данные админа сохраняются).
- **`synced_at`** = `now()` для всех строк, присутствующих в применённом снимке. `updated_at` меняется только у изменившихся строк (явно, т. к. `onupdate` ORM не срабатывает на Core-UPSERT, как в `apply_seed`).
- **Скрытые позиции в корзинах.** FK `cart_items → menu_items` — RESTRICT, строки не удаляются; оформление заказа (#12) обязано отвергать скрытые и недоступные позиции при перепроверке (INT-3).
- **Категория без видимых позиций** остаётся видимой; гостевое меню (#10) не показывает пустые категории.
- **Округление** — не в ядре (ADR-8.2): снимок с > 2 знаками отвергается.

Запись — пакетами (`INSERT … ON CONFLICT … DO UPDATE` с `executemany`, `UPDATE … WHERE id = ANY(:ids)`, `DELETE … WHERE (menu_item_id, price_tier) IN …`). Меню пилота — сотни строк, одна транзакция на снимок занимает доли секунды.

---

## ADR-8.4. Транзакция, блокировка и «всё или ничего»

**Решение.**
- Один снимок — одна транзакция. Первым шагом идёт `SELECT pg_try_advisory_xact_lock(8, hashtext(:tenant_id::text))` (`MENU_SYNC_LOCK_NAMESPACE = 8`). Не получили lock — `MenuSyncBusyError` (CLI — код 3, #16 — `409`/`503` с `Retry-After`). Ожидания нет: синхронизация повторится по расписанию. Lock транзакционный, сам снимается при COMMIT/ROLLBACK и при обрыве соединения. Advisory lock не блокирует строку `tenants`, поэтому правки настроек заведения в админке не ждут импорта. Тот же lock обязаны брать `PUT /stoplist` (#16) и ручной переключатель наличия (#28).
- **«Всё или ничего».** Любая ошибка (`severity=error`) — ничего не пишется, в отчёте весь список ошибок (до 100 штук и «ещё N»). Причина: снимок полный, и пропуск невалидной строки молча скрыл бы позицию у гостей (INT-2). Предупреждения (`zero_price`) применению не мешают.
- **Защита от массового скрытия.** Если план скрывает ≥ 10 позиций и ≥ 30 % видимых сейчас, это ошибка `mass_hide`. Она снимается флагом `--allow-mass-hide`, в API (#16) — по решению #16. Защищает от «не того файла», пустого листа и выгрузки с фильтром. Пустой снимок (0 позиций) отвергается всегда.
- **`--dry-run`** строит тот же план под тем же lock и ничего не пишет. Счётчики пробного прогона совпадают с реальным применением на том же состоянии БД.
- Отклонённый снимок журналируется отдельной короткой транзакцией после отката основной (`record_rejected_run`). Иначе запись об ошибке откатилась бы вместе с ней.

**Отчёт** (`MenuSyncReport`, `app/menu_sync/report.py`): `status` (`applied`/`unchanged`/`rejected`), `dry_run`, `snapshot_hash`; счётчики `categories` и `items` (`created`, `updated`, `hidden`, `restored`, `unchanged`), `prices` (`created`, `updated`, `deleted`), `availability_changed`; `issues[]` — `{code, severity, message, row?, column?, external_id?, value?}`. Значение ячейки обрезается до 60 символов. Коды — `IssueCode` (стабильны для тестов и фронтенда), сообщения — на русском.

**Альтернативы.** Применять валидные строки и пропускать невалидные — отклонено (см. выше). `SELECT … FROM tenants FOR UPDATE` — работает, но блокирует правки заведения. Блокирующий `pg_advisory_xact_lock` с `lock_timeout` — сложнее объяснить в CLI, выигрыша нет.

---

## ADR-8.5. Идемпотентность (INT-1) и журнал `menu_sync_runs`

**Контекст.** INT-1: неизменный снимок не пересчитывается. ADR-7.7 планировал `connectors.last_menu_hash`/`last_menu_sync_at` в #16. Но у файлового импорта нет ключа и записи коннектора, а создавать `connectors` в #8 значит забегать в scope #16 (ключи, возможности). FR-20 и INT-4 нужны время последней синхронизации и её ошибки — для любого источника.

**Решение.** Новая таблица-журнал `menu_sync_runs` (ревизия `0005_menu_sync_runs`).
- Хеш — SHA-256 канонического JSON снимка после `resolve_currency`. Категории и позиции сортируются по `external_id`, деньги записываются строкой с двумя знаками, `null` пишется явно. Порядок строк и формат файла на хеш не влияют.
- Последний применённый хеш — у последней строки заведения со статусом `applied`/`unchanged` **любого источника**: состояние меню одно на заведение. Совпал и нет `--force` → `unchanged`, таблицы меню не трогаются, но строка журнала пишется (иначе INT-4 считал бы меню устаревшим при неизменной кассе).
- `--force` — применить заново (например, после ручной правки БД в разработке).
- **Уточнение ADR-7.7:** `connectors.last_menu_hash`/`last_menu_sync_at` в #16 не нужны — источник правды по хешу и времени синхронизации меню — `menu_sync_runs`. #16 добавляет `menu_sync_runs.connector_id` (составной FK на `connectors`) вместе со своей таблицей. Требует подтверждения пользователя (открытый вопрос 1).
- Объём: коннектор раз в 5 минут даёт 288 строк в сутки. Очистка (например, старше 30 дней, кроме последней `applied`) — периодическая задача #23.

### ERD

```
menu_sync_runs                                  -- журнал, строки только добавляются
  id            uuid PK DEFAULT gen_random_uuid()       (UUIDv7 из new_id)
  tenant_id     uuid NOT NULL FK → tenants(id) ON DELETE RESTRICT
  source        text NOT NULL  CHECK IN ('file','connector')           ck_menu_sync_runs_source
  source_ref    text NULL      CHECK char_length 1–255                 ck_menu_sync_runs_source_ref
                               -- имя файла без каталога / «тип версия» коннектора
  status        text NOT NULL  CHECK IN ('applied','unchanged','rejected')  ck_menu_sync_runs_status
  snapshot_hash text NULL      CHECK ~ '^[0-9a-f]{64}$'                ck_menu_sync_runs_snapshot_hash
  started_at    timestamptz NOT NULL
  finished_at   timestamptz NOT NULL DEFAULT now()  CHECK finished_at >= started_at  ck_menu_sync_runs_finished_at
  counts        jsonb NOT NULL DEFAULT '{}'  CHECK jsonb_typeof = 'object'         ck_menu_sync_runs_counts
  issues        jsonb NOT NULL DEFAULT '[]'  CHECK jsonb_typeof = 'array'          ck_menu_sync_runs_issues
  created_at    timestamptz NOT NULL DEFAULT now()
  CHECK status = 'rejected' OR snapshot_hash IS NOT NULL                 ck_menu_sync_runs_hash_state
  UNIQUE (tenant_id, id)                         uq_menu_sync_runs_tenant_id_id (TenantMixin)
  INDEX (tenant_id, finished_at)                 ix_menu_sync_runs_tenant_id_finished_at
```

`updated_at` нет: строки не меняются. Значения `source`/`status` — `MenuSyncSource`/`MenuSyncStatus` в `app/models/enums.py`, CHECK строится `sql_in` (DEC-009). Денежных и `numeric` колонок нет.

**Миграция** `backend/alembic/versions/0005_menu_sync_runs.py`, `down_revision = "0004"`, одна ревизия, обратимая. `downgrade` удаляет таблицу. Модель — `app/models/menu_sync.py` (заглушка уже написана, **в `app/models/__init__.py` не подключена**: подключается вместе с ревизией, иначе упадут тесты метаданных).

**Обязательные дополнения тестов (DEC-009, DEC-010):**
- `tests/test_models_metadata.py`: `EXPECTED_TABLES += {"menu_sync_runs"}`; `EXPECTED_CHECKS["menu_sync_runs"] = {"source", "source_ref", "status", "snapshot_hash", "hash_state", "finished_at", "counts", "issues"}`; `NUMERIC_EXCEPTIONS` не меняется;
- `tests/test_migrations_offline.py` и `tests/db/test_migrations.py`: `REVISION_TABLES["0005"] = {"menu_sync_runs"}`;
- `tests/db/test_migrations.py`: `ENUM_CHECKS` += `ck_menu_sync_runs_source` → `MenuSyncSource`, `ck_menu_sync_runs_status` → `MenuSyncStatus`;
- `tests/db/test_tenant_isolation.py`: межарендных FK нет — проверить, что таблица попала в общий перебор «у каждой таблицы `tenant_id`»;
- `tests/db/test_schema_invariants.py` проходит без правок (`tenant_id` ведёт UNIQUE и индекс, `*_at` — `timestamptz`);
- CI `backend-services` (`alembic upgrade head / downgrade base / upgrade head / check`) — без правок.

**Альтернативы.**
- (а) Минимальная `connectors` (id, tenant_id, kind, last_menu_hash, last_menu_sync_at) в #8. Отклонено: схема ключей и возможностей — #16, а файловый «коннектор» без ключа как строка `connectors` — натяжка. История синхронизаций (FR-20 «ошибки коннектора») всё равно нужна.
- (б) Хеш в `tenants.settings` — смешение настроек и состояния; истории ошибок нет.
- (в) Без хеша в #8 (импорт файла вручную редкий) — отклонено: INT-1 — общий путь, #16 получил бы его недоделанным.

---

## ADR-8.6. Кто запускает: CLI сейчас, админка после #19, расписание — вне scope

**CLI** (`app/menu_sync/__main__.py`, по образцу `python -m app.seed`):

```
python -m app.menu_sync check  FILE [--sheet NAME] [--json]
python -m app.menu_sync import FILE --tenant UUID [--dry-run] [--force] [--allow-mass-hide]
                                    [--sheet NAME] [--database-url URL] [--json]
```

| Код | Когда |
|---|---|
| 0 | применено; без изменений (хеш совпал); `check`/`--dry-run` без ошибок |
| 1 | ошибка окружения: файла нет или он нечитаем, конфигурация, БД недоступна, заведения нет |
| 2 | ошибки в данных — ничего не записано (`rejected` в журнале, кроме `--dry-run`) |
| 3 | синхронизация меню этого заведения уже идёт (lock) |

- `check` работает без БД и без `.env`: подходит для проверки выгрузки кассы (ADR-8.8) и для unit-тестов CLI на Windows.
- Заведение задаётся только `--tenant UUID`. Slug в `tenants` нет, `name` не уникально. UUID печатает `python -m app.seed`, позже его покажет админка платформы. Подстановка «единственного заведения в БД» отвергнута как неявная (открытый вопрос 3).
- Разрешено при `APP_ENV=prod`: это рабочая операция, в отличие от сида.
- Вывод: отчёт по-русски в stdout (файл, формат, число строк, заведение, счётчики, хеш, id записи журнала, ошибки «строка N, колонка X: сообщение»). Ошибки окружения — в stderr. Пароль БД не печатается (`Database.describe_error`). Путь к файлу в журнал не пишется — только имя (`source_ref`): путь может содержать имя пользователя Windows.
- **single на Windows:** та же `.venv` и тот же `.env`; работает при запущенной службе ai-waiter (согласованность обеспечивают транзакция и lock в PostgreSQL).
- **Без событий EventBus:** CLI — отдельный процесс, а в `single` шина в памяти не пересекает процессы. Поэтому меню гостя (#10) и инструменты ИИ (#11) **читают меню из БД и не кешируют его в памяти процесса**. Если кеш понадобится, ключом будет `menu_sync_runs.id` последней `applied` (одинаково в обоих режимах).

**Админка (после #19, вне #8) — контракт на будущее:**

| Method | Path | Кто | Request | Response | Ошибки |
|---|---|---|---|---|---|
| POST | `/api/admin/menu/import?dry_run=true\|false&force=…&allow_mass_hide=…` | администратор заведения (сессия #19), `tenant_id` — из учётной записи | `multipart/form-data`: `file` (.csv/.xlsx ≤ 5 МБ), `sheet?` | `200 MenuSyncReport` (`applied`/`unchanged`, или `dry_run=true`) | `413` > 5 МБ; `415` формат; `422 MenuSyncReport` (`rejected`, `issues[]`); `409` lock занят; `429` RateLimiter (10/мин на заведение) |
| GET | `/api/admin/menu/sync-runs?limit=20` | администратор заведения | — | `200 [{id, source, source_ref, status, started_at, finished_at, counts, issues_count}]` | — |

Тело читается потоком с обрывом после 5 МБ, затем вызывается `parse_menu_bytes` (общая точка с CLI). Время — ISO 8601 с зоной. FR-20 «синхронизировать сейчас»: для файлового коннектора — повторная загрузка файла; для коннекторов — флаг в ответе `heartbeat` (#16).

**Импорт по расписанию** (ТЗ 4.2 «или по расписанию») — **вне scope #8**. Сейчас достаточно Планировщика заданий Windows или cron, запускающих тот же CLI с файлом, который кладёт касса. Кода для этого не нужно. Встроенный вариант на потом: периодическая задача `menu_sync.file_poll` через `TaskScheduler` (`@registry.periodic`, DEC-001), каталог из новой переменной `MENU_IMPORT_DIR` (`Settings` + `.env.example`), идемпотентность — по хешу. В `scaled` каталог должен быть томом контейнера `worker`. Отдельная story, если понадобится.

---

## ADR-8.7. Зависимости и безопасность разбора

**Новые зависимости** (`backend/pyproject.toml`, основная группа — нужны и в `single` на Windows; добавляет developer вместе с `uv.lock`):
- `openpyxl>=3.1` — чтение XLSX, чистый Python, работает на Windows и Linux.
- `defusedxml>=0.7` — openpyxl сам использует его, если пакет установлен: защита от XML-бомб и внешних сущностей (XXE). Тест: `openpyxl.xml.DEFUSEDXML is True`.
- CSV — стандартный `csv`, без pandas. pandas — тяжёлый для сервера пилота (9.1a) и сам угадывает типы (`007` → 7).

**Безопасность:**
- **Zip-бомба:** до openpyxl — `zipfile`: сумма `file_size` членов ≤ 50 МБ, `file_size/compress_size` ≤ 100, плюс лимит файла 5 МБ.
- **Формулы** не вычисляются (`data_only=True`): читаются сохранённые значения, внешние ссылки не разрешаются.
- **Макросы:** `.xlsm` и `vbaProject.bin` отвергаются (не исполняются в любом случае, но такой файл скорее всего не тот).
- **CSV injection** (`=cmd|…` в ячейке) не касается импорта: данные не исполняются, а пишутся в БД как текст. Учесть при будущем экспорте из админки (FR-18): экранировать `= + - @` в начале ячейки.
- **Prompt injection (AI-3):** `pos_name` и `station` из файла — данные, а не инструкции. Длина ограничена, управляющие символы отвергнуты; при выдаче ИИ (#11) значения оборачиваются как данные. Меню целиком в промпт не кладётся (AI-правила).
- **Tenant-изоляция:** `tenant_id` — явный аргумент CLI или из учётной записи админа (не из файла); каждый SELECT/UPDATE/DELETE в `service` фильтрует по `tenant_id`; составные FK из #7 не дают позиции сослаться на чужую категорию. Тест: импорт в заведение A не меняет меню заведения B с теми же `external_id`.
- **Путь файла** приходит только из аргумента CLI, в коде путей нет (9.2). Загрузка в админке файл на диск не сохраняет (разбор из памяти).
- **Логи:** без содержимого файла и пароля БД; в журнал попадают только имя файла и проблемы (значение ячейки обрезано до 60 символов).

---

## ADR-8.8. Выгрузка меню «restoran» — консольная команда на стороне кассы

**Факты.** Дамп `restoran(3).sql` содержит DDL `menu` и строки `type`, но **строк `menu` в нём нет**, поэтому для тестового меню его недостаточно. Живые данные лежат в каталоге данных MariaDB 10.3 OpenServer (`userdata/MariaDB-10.3-x64/restoran`: есть `menu.ibd`, `type.ibd`, `store.ibd`), а сейчас в OpenServer запущен MySQL 8.0. Каталог MariaDB 10.3 ему не подходит, InnoDB-файлы MariaDB и MySQL 8 несовместимы. DDL: `menu(id, id_type, name varchar(20), price float, price_vip float NULL, vid varchar(5), id_store NULL, disabled tinyint NULL DEFAULT 0)`, `type(id, name varchar(20), vid varchar(2))`, `store(id, name varchar(50) NULL)`.

**Решение.** Утилита живёт **в коде кассы**: консольная команда Yii2 `php yii ai-export-menu <file.csv>` (`commands/AiExportMenuController.php`, `actionIndex`) и класс `MenuSnapshotBuilder` с соответствием A.2. В #18 тот же класс соберёт тело `PUT /menu` для `php yii ai-sync`, то есть соответствие полей пишется один раз. В ядре ai-waiter кода под кассу нет (CLAUDE.md), в `tools/` репозитория ai-waiter — тоже.

Соответствие (A.2) → колонки файла:

| Колонка | Касса |
|---|---|
| `category_external_id`, `category_name`, `category_sort_key` | `type.id`, `type.name`, `type.vid` |
| `external_id`, `name`, `sort_key` | `menu.id`, `menu.name`, `menu.vid` |
| `price_default` | `menu.price`, округление до 2 знаков half-up (`round($price, 2)` → `number_format(…, 2, '.', '')`) |
| `price_vip` | `menu.price_vip`, если `> 0`; `NULL`/`≤ 0` → пустая ячейка (тарифа нет) |
| `currency` | пусто (валюта заведения, A.1: AZN) |
| `station` | `store.name` через `menu.id_store` (`LEFT JOIN`; нет склада — пусто) |
| `is_available` | `menu.disabled` = 0 или `NULL` → `1`, иначе `0` |

Файл пишется `fputcsv` в UTF-8 без BOM, разделитель `,`, первая строка — заголовок. Проверка — `python -m app.menu_sync check <file>` (без БД).

**Получение данных** (один из способов, выбирает пользователь, открытый вопрос 5):
1. Переключить OpenServer на модуль MariaDB-10.3-x64 (настройки → модули → MySQL/MariaDB), чтобы поднялась база `restoran` из `userdata`, и запустить `php yii ai-export-menu`. Перед этим скопировать каталог `userdata/MariaDB-10.3-x64` (резервная копия).
2. Свежий дамп рабочей базы от заведения → импорт в MariaDB 10.3 → та же команда.

`config/db.php` кассы не копируется и нигде не цитируется.

**Где лежит результат.** Реальная выгрузка — только локально: `local-data/` в корне ai-waiter (добавлено в `.gitignore`) или каталог вне репозитория. В репозиторий ai-waiter попадает только синтетический пример (`backend/tests/fixtures/menu/menu_valid.csv`). Названия и цены заведения в публичный репозиторий не попадают.

**Альтернативы.**
- (а) Python-утилита в `tools/restoran_export/` с `pymysql` — драйвер MySQL и код под конкретную кассу в репозитории ядра, дублирование соответствия A.2 с будущим PHP-коннектором. Отклонено.
- (б) SQL-запрос через `mysql --batch` — без кода, но округление и правило `price_vip` в SQL плохо тестируются, а результат (TSV) требует поддержки табуляции. Годится как разовый обходной путь, если команда Yii2 задерживается.

**Последствия.** Код команды коммитится в репозиторий кассы по его процессу, как задачи этапа 0 (#2–#5). В ai-waiter #67 даёт только инструкцию выгрузки и проверку `check` на реальной выгрузке; формат и пример — #64, `.gitignore` уже изменён.

---

## Security

| Аспект | Решение |
|---|---|
| Tenant-изоляция | `tenant_id` из аргумента CLI или учётной записи, не из файла; фильтр во всех запросах `service`; составные FK #7; тест «два заведения с одинаковыми `external_id`» |
| Роль | CLI — оператор сервера (доступ к `.env`); будущий эндпоинт — администратор заведения (#19); `PUT /menu` — коннектор по ключу (#16) |
| Rate-limit | CLI — нет; эндпоинт админки — `RateLimiter` 10/мин на заведение; `PUT /menu` — решает #16 |
| Валидация | Pydantic `extra="forbid"`, длины, шаблоны, `MoneyStr` без `float`; лимиты размера и строк; «всё или ничего» |
| Файлы | zip-бомба, `defusedxml`, формулы не вычисляются, макросы отвергаются, разбор из памяти |
| Prompt injection | названия — данные (AI-3), без управляющих символов, длина ≤ 200; меню не в промпте |
| Секреты | пароль БД маскируется; путь файла не журналируется; реальные выгрузки — в `local-data/` (gitignore) |

ИИ не затронут: инструментов не добавляется, функции отправки заказа нет. События EventBus и задачи TaskScheduler в #8 не появляются (ADR-8.6).

---

## Module Structure (code stubs)

Заглушки уже в рабочей копии. Тела — `raise NotImplementedError`, docstring на русском.

```
backend/app/schemas/__init__.py            общие Pydantic-типы API
backend/app/schemas/money.py               MoneyStr, parse_money, format_money, MONEY_MAX (DEC-013)
backend/app/models/enums.py                + MenuSyncSource, MenuSyncStatus
backend/app/models/menu_sync.py            MenuSyncRun (не подключена в app/models/__init__.py до 0005)
backend/app/menu_sync/__init__.py          описание пакета и границ импортов
backend/app/menu_sync/snapshot.py          MenuSnapshot, SnapshotCategory, SnapshotItem, check_snapshot, parse_snapshot, resolve_currency, snapshot_hash
backend/app/menu_sync/report.py            IssueCode, Severity, SyncIssue, EntityCounts, PriceCounts, MenuSyncReport, limit_issues
backend/app/menu_sync/plan.py              CurrentMenu/Category/Item, CategoryWrite, ItemWrite, MenuSyncPlan, plan_menu_sync
backend/app/menu_sync/service.py           apply_menu_snapshot, load_current_menu, last_applied_hash, record_rejected_run, ошибки
backend/app/menu_sync/files/__init__.py    FileFormat, ParsedMenuFile, detect_format, parse_menu_bytes, read_menu_file
backend/app/menu_sync/files/format.py      колонки, Cell, SheetRow, TabularData, parse_header, cell_to_*, rows_to_snapshot
backend/app/menu_sync/files/csv_reader.py  read_csv_table
backend/app/menu_sync/files/xlsx_reader.py check_xlsx_archive, read_xlsx_table (openpyxl — только здесь)
backend/app/menu_sync/__main__.py          CLI check/import, коды выхода
backend/tests/fixtures/menu/menu_valid.csv синтетический пример
.gitignore                                 + local-data/
```

Предстоит создать developer-у: `backend/alembic/versions/0005_menu_sync_runs.py`, тесты (ниже), зависимости `openpyxl`/`defusedxml`, банлист ruff для `openpyxl`, раздел README «Импорт меню». Фронтенда в #8 нет.

---

## Истории — файлы, тесты, порядок

### Соответствие гипотезы и story-issues

| Гипотеза | Story | Что | Размер |
|---|---|---|---|
| A1 | #61 | Снимок: `MoneyStr`, `MenuSnapshot`, `check_snapshot`, `parse_snapshot`, `resolve_currency`, `SyncIssue`/`IssueCode` | M |
| A2 | #62 | Применение: `plan_menu_sync`, `apply_menu_snapshot` (lock, «всё или ничего», mass-hide), без журнала | L |
| E | #63 | Журнал `menu_sync_runs`, ревизия `0005`, `snapshot_hash`, пропуск по хешу (`unchanged`), `force`, `record_rejected_run` | M |
| B | #64 | Формат файла, разбор CSV, синтетический пример | M |
| C | #65 | Разбор XLSX, зависимости `openpyxl`/`defusedxml` | M |
| D | #66 | CLI `python -m app.menu_sync check` / `import` | M |
| F | #67 | Выгрузка «restoran»: команда Yii2 в репозитории кассы + инструкция | M (основная работа в кассе) |

Порядок: #61 → (#62 ∥ #64) → #63 (после #62) и #65 (после #64) → #66 (после #63 и #64; XLSX подхватывается сам, если #65 уже влит) → #67 (нужен формат #64; проверка импортом — #66).

### Как разбивка #62/#63 ложится на дизайн

Противоречий нет, если зафиксировать владельцев:

- **Ревизия `0005` и модель `MenuSyncRun` — только #63.** #62 миграций не добавляет и `app/models/__init__.py` не трогает; заглушка `app/models/menu_sync.py` до #63 не подключена.
- **Перечисления `MenuSyncSource`/`MenuSyncStatus`** уже лежат в `app/models/enums.py`. #62 использует `MenuSyncStatus.APPLIED`/`REJECTED` в отчёте и `MenuSyncSource` в сигнатуре; `UNCHANGED` начинает возвращать только #63. CHECK по ним появляется в #63.
- **#62 работает без журнала:** шаги 1, 2, 4, 5 сервиса (docstring `service.py`). В отчёте `snapshot_hash = None` и `run_id = None`. Параметр `force` уже в сигнатуре, но ни на что не влияет. В #63 сигнатура `apply_menu_snapshot` не меняется, меняется только поведение.
- **#63 добавляет поверх:**
  - `snapshot_hash` (реализация в `snapshot.py`) и `last_applied_hash`;
  - шаг 3: пропуск по хешу → `unchanged`, без записи в таблицы меню;
  - шаг 6: строка журнала `applied`/`unchanged`;
  - `record_rejected_run`;
  - ревизию `0005` и дополнения тестов по DEC-009/DEC-010.

  db-тесты #62 при этом не ломаются: они проверяют таблицы меню, а не журнал. Условие приёмки #63 — эти тесты проходят без правок.
- **Название статуса:** во всех документах и AC — `unchanged` (`MenuSyncStatus.UNCHANGED`, CHECK `ck_menu_sync_runs_status`).
- **CLI #66** зависит от #63: `--force`, `unchanged` и журналирование отклонённых импортов без журнала не реализуются.

### Файлы и тесты по story

| Story | Файлы | Тесты |
|---|---|---|
| #61 | `app/schemas/__init__.py`, `app/schemas/money.py`, `app/menu_sync/__init__.py`, `app/menu_sync/report.py` (`SyncIssue`, `IssueCode`, `Severity`, `limit_issues`; счётчики объявлены, заполняет #62), `app/menu_sync/snapshot.py` (кроме `snapshot_hash`) | unit `tests/test_money.py`: `str`/`Decimal`/`int`; `float` → ошибка; 3 знака, минус, экспонента, максимум; сериализация `"8.50"` в JSON. unit `tests/test_menu_snapshot.py`: AC #61 — три ошибки сразу (нет `default`, USD, неизвестная категория); дубли; `extra` запрещён; управляющие символы; имя тарифа; `resolve_currency`; `parse_snapshot` с сырыми данными. Тест границы: `app.menu_sync` не импортирует `fastapi` |
| #62 | `app/menu_sync/plan.py`, `app/menu_sync/service.py` (шаги 1, 2, 4, 5) | unit `tests/test_menu_plan.py`: каждая строка таблицы ADR-8.3; удаление тарифа; `is_available=None`; mass-hide на границе 10 позиций / 30 % и `allow_mass_hide`; счётчики; `restored` важнее `updated`. db `tests/db/test_menu_sync_apply.py`: AC #62; meta и аллергены не тронуты; два заведения; `rejected` ничего не пишет; `dry_run` ничего не пишет и даёт те же счётчики; lock занят → `MenuSyncBusyError` (через второе соединение); нет заведения → `TenantNotFoundError`; `synced_at`/`updated_at` |
| #63 | `app/models/menu_sync.py` (подключить в `app/models/__init__.py`), `alembic/versions/0005_menu_sync_runs.py`, `snapshot.snapshot_hash`, `service.last_applied_hash`, `service.record_rejected_run`, шаги 3 и 6 | unit: хеш — порядок категорий, позиций и тарифов не влияет; цена, наличие и `null` влияют; 64 hex-символа. Дополнения DEC-009: `EXPECTED_TABLES`, `EXPECTED_CHECKS`, `REVISION_TABLES` в двух тестах, `ENUM_CHECKS`. db `tests/db/test_menu_sync_runs.py`: AC #63 — повтор → `unchanged`, `updated_at`/`synced_at` прежние; `force` применяет; другой источник с тем же хешем → `unchanged`; `rejected` пишется после отката; CHECK `hash_state` и `finished_at`; `dry_run` не журналируется |
| #64 | `app/menu_sync/files/__init__.py`, `files/format.py`, `files/csv_reader.py`, `tests/fixtures/menu/menu_valid.csv` (есть) и фикстуры с ошибками | unit: AC #64 — BOM, `;`, запятая, `abc` в строке 4, повтор в строке 7 ↔ строке 3; разделители `,`/`;`; кавычки и переносы; cp1251 → `encoding`; все коды заголовка и ячеек; `category_conflict`; `#`-колонки; лимиты; `007`; `is_available` есть/нет. Тест границы: `files` не импортирует `sqlalchemy`/`app.db` |
| #65 | `app/menu_sync/files/xlsx_reader.py`; `pyproject.toml` + `uv.lock` (`openpyxl`, `defusedxml`); ruff `banned-api` для `openpyxl`; `RESTRICTED["openpyxl"]` | unit: AC #65 — лист `Menu` не первый, снимок совпадает со снимком CSV-примера. Книги собираются в самом тесте. Числовой id, float-шум, формула с кешем и без, дата → ошибка, zip-бомба, `.xlsm`, не-zip, `DEFUSEDXML is True` |
| #66 | `app/menu_sync/__main__.py`, README (раздел «Импорт меню») | unit без БД: `check` на примере → 0, на битом файле → 2, нет файла → 1; `--json`; разбор аргументов. db: AC #66 — `--dry-run` → 0 без изменений, затем `applied` → 0, затем `unchanged` → 0; ошибки → 2 и `rejected` в журнале; нет заведения → 1; lock занят → 3; `APP_ENV=prod` разрешён |
| #67 | касса: `commands/AiExportMenuController.php`, `MenuSnapshotBuilder`. ai-waiter: инструкция (README или `docs/`), `local-data/` в `.gitignore` (есть) | касса: тесты округления `7.999999` → `8.00`, `price_vip` 0/NULL → пустая ячейка, `disabled` 1/NULL. Ручная приёмка: `python -m app.menu_sync check` на реальной выгрузке → 0, `import --dry-run` в БД разработки |

**Изменения для #16.** Сослаться на ADR-8.1/8.4/8.5:
- `PUT /menu` = `parse_snapshot` + `apply_menu_snapshot(source=connector)`;
- `PUT /stoplist` берёт тот же lock;
- `connectors.last_menu_hash` не создаётся, вместо него добавляется `menu_sync_runs.connector_id`.

---

## Риски

| Риск | Митигация |
|---|---|
| Excel портит id (`007` → `7`) и цены (`8.10` → `8.1` — безвредно; формулы) | инструкция «колонка id — текстовая»; проверка `check`; `float` с > 2 знаками — ошибка, а не тихое округление |
| Не тот файл скрывает всё меню | «всё или ничего», пустой снимок отвергается, защита `mass_hide`, `--dry-run` |
| `menu.disabled` в кассе означает «снято с продажи навсегда», а не стоп-лист | по A.2 — наличие; уточнить у заведения (открытый вопрос 6) |
| CLI и служба одновременно, либо две команды разом | advisory lock, код 3 |
| Кеш меню в памяти процесса не узнает об импорте из CLI | ADR-8.6: меню читается из БД; ключ кеша — id последней `applied` |
| Рост `menu_sync_runs` при коннекторе каждые 5 мин | очистка в #23 |
| openpyxl медленный на больших книгах | `read_only=True`, лимит 5 МБ / 5000 строк; меню пилота — сотни строк |

---

## Открытые вопросы для пользователя (с рекомендациями)

1. **Где хранить хеш и время синхронизации меню.** Рекомендация: журнал `menu_sync_runs` в #8 (ревизия 0005); в #16 `connectors.last_menu_hash` не создаётся, вместо него `menu_sync_runs.connector_id`. Это уточняет ADR-7.7.
2. **Политика ошибок — «всё или ничего»** (одна невалидная строка — файл не применяется, выводится полный список ошибок) и **отклонение всего снимка при чужой валюте**. Рекомендация: да.
3. **Как указывать заведение в CLI.** Рекомендация: `--tenant UUID`, обязательный. Альтернатива — подставлять заведение, если оно в БД одно (удобно в пилоте, но неявно).
4. **Колонка `is_available` в файле.** Рекомендация: необязательная; нет колонки — наличие не меняется (ручной стоп-лист в админке не затирается). Выгрузка «restoran» колонку заполняет.
5. **Как получить живые данные «restoran».** Рекомендация: переключить OpenServer на MariaDB 10.3 (предварительно скопировав `userdata/MariaDB-10.3-x64`) и выполнить команду Yii2; иначе — свежий дамп от заведения.
6. **Смысл `menu.disabled` в кассе** («Deaktiv»): временный стоп-лист или снятие с продажи? Рекомендация: пока по A.2 (`is_available`), уточнить у заведения; если это «снято навсегда», позиции с `disabled=1` не выгружать (будут скрыты).
7. **Где код выгрузки.** Рекомендация: команда Yii2 в репозитории кассы (переиспользуется в #18); в ai-waiter — только формат, пример и инструкция.
8. **Защита от массового скрытия** (≥ 10 позиций и ≥ 30 % видимых → отказ без `--allow-mass-hide`). Рекомендация: оставить для файла; для `PUT /menu` решить в #16.
