# Architecture: Feature #7 — Модель данных v1 и миграции Alembic

**Issue:** #7 · **ТЗ:** раздел 7 (модель данных), 3.1–3.4 (FR-1…FR-21, пороги), 4.4–4.6 (Integration API, INT-1…INT-7, жизненный цикл заказа), 5 (AI-1…AI-8), 6 (NFR-3, NFR-4, NFR-5, NFR-6, NFR-8, NFR-9), 9.1–9.3, приложение A.2
**Spec:** `docs/specs/feature-7-data-model.md` (пишет analyst)
**Опирается на:** `docs/arch/feature-6-project-scaffold.md` (ADR-2 конфигурация, ADR-5 asyncpg и Windows, ADR-6 compose/CI), DEC-001…DEC-005
**Потребители модели:** #8 (импорт меню), #9 (вход по QR, визит), #10 (меню и корзина), #11 (чат), #12 (оформление заказа), #14 (лента официанта), #16–#17 (Integration API), #19 (персонал), #22 (вызовы), #23 (фоновые задачи), #25 (отзывы), #26 (лимиты), #27–#29 (админка), #31 (бэкапы)

Задача #7 — схема БД первой версии (15 таблиц), подключение SQLAlchemy 2 async к `Container`, Alembic с обратимыми миграциями, тесты с PostgreSQL и сид-данные. HTTP-эндпоинтов здесь нет; проверка `database` в `/health/ready` спроектирована (ADR-7.9), но по решению spec (открытый вопрос 19) реализуется отдельной маленькой story после #48.

---

## ADR-7.1. Первичные ключи — UUIDv7, генерируются приложением

**Контекст.** `orders.id` — это `order_id` Integration API, и он уже зафиксирован как UUID (ТЗ 4.4, `ai_order_map.order_id CHAR(36)` в приложении A.3). Идентификаторы визитов и заказов видны анонимному гостю. ТЗ 9.3 и этап 4 предполагают перенос данных пилотного заведения в общую БД на VPS.

**Решение.** Все таблицы с суррогатным ключом: `id UUID PRIMARY KEY`, значение — UUIDv7 (RFC 9562), генерирует приложение (`app/db/ids.py:new_id`, без зависимостей: Python 3.12 не имеет `uuid.uuid7`, PostgreSQL 16 — `uuidv7()`). Запасной `server_default gen_random_uuid()` (v4, встроен в PostgreSQL 13+, расширение не нужно) — для ручных INSERT. Таблицы-связки (`menu_item_prices`, `menu_item_allergens`) и `menu_item_meta` (1:1) — с натуральным/общим PK.

**Альтернативы.**
- `BIGINT GENERATED ALWAYS AS IDENTITY` — компактнее, читаемее в админке. Отклонено: перебираемые ID у гостя; конфликт последовательностей при слиянии БД пилота с общей БД на VPS; `orders` всё равно нужен UUID для Integration API — получилось бы два вида ключей.
- UUIDv4 — случайный порядок вставки ухудшает локальность B-tree и не даёт естественного порядка заказов для курсора `GET /orders`.
- Библиотека `uuid-utils`/`uuid6` — лишняя зависимость ради 10 строк кода.

**Последствия.** Ключ известен до INSERT — удобно для журнала событий и идемпотентности. `tenant_id` — тоже UUID, составные FK (ADR-7.3) занимают 32 байта — для объёмов пилота несущественно. В Integration API пример `confirmed_by.staff_id: 7` становится UUID-строкой (открытый вопрос 1). При переходе на Python 3.14 `new_id` заменяется на `uuid.uuid7()` без миграции.

---

## ADR-7.2. Статусы и перечисления — `text` + `CHECK`, а не PostgreSQL `ENUM`

**Контекст.** Статусы заказа (8 значений, ТЗ 4.6), визита, типы событий будут расширяться (например, `manual` для ручного ввода в кассу).

**Решение.** Колонка `text NOT NULL` + `CHECK (col IN (...))` с именем `ck_<table>_<col>`. Значения — `StrEnum` в `app/models/enums.py` (единый источник для CHECK, Pydantic-схем и TS-типов). В модели: `mapped_column(Text)` + `CheckConstraint(f"status IN ({...})", name="status")`, строка CHECK строится из перечисления. Изменение набора — миграция `drop_constraint` + `create_check_constraint` в одной транзакции.

**Альтернативы.** PG `ENUM`: `ALTER TYPE … ADD VALUE` необратим (значение нельзя удалить, downgrade невозможен без пересоздания типа и колонок), Alembic autogenerate не отслеживает изменения значений, тип надо создавать/удалять отдельно в миграциях. SQLAlchemy `Enum(native_enum=False, create_constraint=True)` — допустимо, но имя и текст CHECK менее предсказуемы; явный `CheckConstraint` проще читать в миграции.

**Последствия.** `alembic check` не сравнивает тексты CHECK, поэтому есть отдельный db-тест: значения в `pg_get_constraintdef` для каждого `ck_*_status`/`ck_*_type` совпадают с перечислением. Допустимые переходы (`ORDER_TRANSITIONS`) проверяет сервис, не БД.

---

## ADR-7.3. Мультиарендность: `tenant_id` везде + составные FK; RLS — будущая опция

**Контекст.** CLAUDE.md и NFR-4: `tenant_id` во всех таблицах заведения и во всех запросах. Главный риск — строка одного заведения, ссылающаяся на строку другого (например, позиция заказа на блюдо чужого меню из-за ошибки в сервисе).

**Решение.**
1. `tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT` во всех таблицах, кроме `tenants`, — включая дочерние (`order_items`, `menu_item_prices`, `cart_items`, `order_events`, `messages`, связки). Отдельный индекс по `tenant_id` не создаётся: его покрывают составные UNIQUE/индексы, начинающиеся с `tenant_id`.
2. Каждая родительская таблица имеет `UNIQUE (tenant_id, id)`; ссылки внутри заведения — **составные FK** `(tenant_id, parent_id) → parent (tenant_id, id)`. Тогда БД гарантирует, что ребёнок и родитель принадлежат одному заведению. Для nullable-ссылок (`tables.hall_id`) действует `MATCH SIMPLE`: при `hall_id IS NULL` FK не проверяется — это нужное поведение.
3. `ON DELETE`: `CASCADE` только для «владеемых» строк (`menu_item_prices`, `menu_item_meta`, `menu_item_allergens` → `menu_items`; `cart_items`, `messages` → `visits`; `order_items` → `orders`), остальное — `RESTRICT`. Данные меню не удаляются (INT-2, `is_hidden`), заказы не удаляются никогда. `ON DELETE SET NULL` на составных FK не используется (обнулил бы и `tenant_id`).
4. Глобально уникальны только `tables.qr_token` (гость приходит только с токеном — по нему определяется заведение, FR-1) и первичные ключи. Все бизнес-уникальности — в границах заведения: `UNIQUE (tenant_id, external_id)` для `categories`, `menu_items`, `tables`; `UNIQUE (tenant_id, idempotency_key)` для `orders`; `UNIQUE (tenant_id, code)` для `allergens`.
5. Справочник аллергенов — отдельный у каждого заведения (копия 14 кодов ЕС при создании заведения, `app/models/reference.py`): FR-16a говорит «по умолчанию», то есть заведение может дополнять; глобальная таблица с nullable `tenant_id` усложнила бы уникальность и RLS.
6. В приложении: репозитории/сервисы принимают `tenant_id` явным аргументом; unit-тест метаданных проверяет, что у каждой таблицы, кроме `tenants`, есть `tenant_id NOT NULL`, а каждый FK на таблицу заведения включает `tenant_id`.

**Почему `UNIQUE (tenant_id, idempotency_key)`, а не глобально и не по визиту.** Глобальная уникальность дала бы межарендный оракул/DoS: гость заведения A, подобрав ключ заведения B, получил бы конфликт. Ключ генерирует клиент (`crypto.randomUUID()`), граница заведения согласуется с RLS и будущим секционированием. Сервис при конфликте загружает существующий заказ и сверяет `visit_id`: совпал — возвращает тот же заказ (`200`, идемпотентный повтор), не совпал — `409` (#12).

**RLS (Row-Level Security) — не в #7.** Схема к нему готова: везде `tenant_id`, политика вида `USING (tenant_id = current_setting('app.tenant_id')::uuid)` и `SET LOCAL app.tenant_id` в начале транзакции добавляются миграцией без изменения таблиц. Сейчас не включаем: одна роль БД — владелец таблиц (обходит RLS без `FORCE`), есть законные межарендные операции (подметание эскалаций и визитов по всем заведениям, владелец платформы), а в пилоте одно заведение. Пересмотреть на этапе 4 (SaaS, #36) — отдельным ADR.

**Альтернативы.** Простые FK по `id` + проверка в сервисах — дешевле, но ошибка сервиса молча создаёт межарендную ссылку. Схема/БД на заведение — тяжёлые миграции и пул соединений, противоречит «один код, один процесс» для `single`.

**Последствия.** В SQLAlchemy у `relationship` через составной FK колонка `tenant_id` участвует в нескольких FK — нужны `foreign_keys=[...]` и `overlaps="..."` (или `viewonly=True` для обратных связей), иначе предупреждения «relationship X will copy column tenant_id». Это цена гарантии; relationships объявляются только там, где нужны.

---

## ADR-7.4. Деньги, количества и снимки в заказе

**Решение.**
- Деньги гостя — `NUMERIC(10,2)` (`Numeric(10, 2, asdecimal=True)` → `Decimal`), `CHECK (x >= 0)`: `menu_item_prices.price`, `cart_items.price_at_add`, `orders.total`, `orders.pos_total`, `order_items.price_at_order`. В JSON API — строка с двумя знаками (сериализация — общий тип `Money` в схемах, появляется в #10/#12).
- **Исключение:** стоимость вызова ИИ `messages.cost_usd NUMERIC(12,6)` — это не деньги гостя, а оценка расходов в долях цента (NFR-7); `NUMERIC(10,2)` округлил бы её до нуля. Unit-тест метаданных содержит это имя в явном списке исключений.
- Валюта — `text CHECK (currency ~ '^[A-Z]{3}$')`: у заведения (`tenants.currency`), у позиции (`menu_items.currency`, приходит из кассы), снимок в заказе (`orders.currency`). Синхронизация отклоняет позиции с валютой, отличной от валюты заведения.
- Количество — `integer CHECK (qty BETWEEN 1 AND 99)` в корзине и заказе (дробные порции — открытый вопрос 4). В Integration API `qty` — строка (как в ТЗ 4.4), это позволит перейти на `NUMERIC(10,3)` без смены контракта.
- **Снимки** (чтобы старые заказы не менялись при смене меню, INT-2, INT-3):
  - `cart_items.price_at_add` и `cart_items.price_tier` — цена за единицу и тариф стола в момент добавления/последнего подтверждения гостем. При отправке сервис сравнивает её с последним снимком (INT-3) и при расхождении просит подтвердить новую сумму.
  - `order_items.price_at_order` — цена после перепроверки; `order_items.name_snapshot` — `menu_items.pos_name` на момент заказа (официант без `push_order` вводит заказ в кассу по кассовому названию); локализованное название для гостя берётся из `menu_item_meta` по `menu_item_id`.
  - `orders.price_tier`, `orders.currency`, `orders.total` — снимок; `total` = сумма `qty × price_at_order` по строкам без `removed_by_staff`, пересчитывается сервисом при правке (FR-13). Инвариант проверяется тестом сервиса, не CHECK-ом.

---

## ADR-7.5. Одна текущая корзина на визит; один открытый визит на стол

**Решение.**
- Отдельной таблицы `carts` нет: корзина визита — строки `cart_items` с этим `visit_id` (ТЗ 7: «у визита одна текущая корзина»). Все устройства за столом видят одну корзину (визит — сессия стола).
- `UNIQUE (tenant_id, visit_id, menu_item_id, comment)`: то же блюдо с тем же комментарием увеличивает `qty`, с другим комментарием — отдельная строка (как в кассе после A.3 п.2). `comment text NOT NULL DEFAULT ''` (пустая строка = без комментария), поэтому `NULLS NOT DISTINCT` не нужен.
- При `POST /orders` (#12) в одной транзакции: создать `orders` + `order_items` + `order_events(created)`, удалить `cart_items` визита, `COMMIT` — и только потом уведомления/ИИ (NFR-3).
- Не больше одного открытого визита на стол: частичный уникальный индекс `uq_visits_open_table ON visits (table_id) WHERE status = 'open'`. Гонка двух первых сканирований решается `INSERT … ON CONFLICT DO NOTHING` + повторный `SELECT` (#9).

**Альтернатива.** Таблица `carts` с `visit_id UNIQUE` — лишняя сущность без собственных атрибутов; при появлении нужды (несколько корзин на стол, корзины по устройствам) добавляется миграцией.

---

## ADR-7.6. `order_events` — append-only, защищено триггером

**Контекст.** Журнал нужен для FR-9 (гость видит перечень изменений), FR-13 и разборов спорных случаев — значит, ему должна быть возможность доверять.

**Решение.** В миграции `0004`:
```sql
CREATE FUNCTION order_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'order_events is append-only' USING ERRCODE = 'restrict_violation';
END $$;
CREATE TRIGGER trg_order_events_append_only BEFORE UPDATE OR DELETE ON order_events
  FOR EACH ROW EXECUTE FUNCTION order_events_append_only();
```
`downgrade` удаляет триггер и функцию. FK `order_events.order_id` — `ON DELETE RESTRICT`. Каждое изменение статуса/строк заказа пишет событие в той же транзакции (сервис заказов; тест сервиса проверяет пару «изменение + событие»).

**Альтернативы.** Только соглашение — ошибка в коде незаметно переписывает историю. `REVOKE UPDATE, DELETE` — не работает при одной роли-владельце. Автоматическая запись события триггером на `orders` — не знает актора (`actor_type/actor_id`).

**Последствия.** `TRUNCATE` (очистка тестовой БД) триггер не вызывает; откат транзакции в тестах работает. Удаление данных заведения целиком — отдельный административный скрипт с `ALTER TABLE … DISABLE TRIGGER` (вне #7). Alembic autogenerate триггеры не видит — `alembic check` на них не реагирует; наличие триггера проверяет db-тест (UPDATE/DELETE → ошибка).

---

## ADR-7.7. Ссылки на таблицы, которые появятся позже

`staff_users` (#19), `connectors` (#16), `waiter_calls` (#22), `reviews` (#25) — вне #7. Чтобы не было тупика:

| Колонка в #7 | Сейчас | Когда появится таблица |
|---|---|---|
| `orders.confirmed_by_staff_id UUID NULL` | без FK (в прототипе #14 входа нет — остаётся `NULL`) | #19: составной FK `(tenant_id, confirmed_by_staff_id) → staff_users (tenant_id, id)` `ON DELETE RESTRICT`; перед созданием FK миграция проверяет отсутствие «висячих» значений (или `NOT VALID` + `VALIDATE`) |
| `visits.closed_by_staff_id UUID NULL` | без FK | #19: так же |
| `order_events.actor_id UUID NULL` | мягкая ссылка, без FK навсегда | полиморфна (`actor_type` = `staff`/`connector`/`guest`/`system`) — FK невозможен по смыслу; журнал не должен ломаться при деактивации сотрудника |
| `waiter_calls.visit_id`, `reviews.visit_id` | — | составной FK на `visits (tenant_id, id)`, который уже есть |
| `connectors.tenant_id` | — | FK на `tenants`; `last_menu_hash`, `last_menu_sync_at` — в `connectors` (файловый импорт #8 — коннектор вида `file`) |

`confirmed_by_staff_id` — UUID, потому что все ключи UUID (ADR-7.1). Почему не создать `staff_users` сейчас «пустой»: состав колонок авторизации (PIN/пароль/Telegram) решается в #19, и преждевременная таблица гарантирует миграцию-переделку. Владелец платформы не принадлежит заведению — рекомендуется отдельная таблица без `tenant_id` (открытый вопрос 10).

---

## ADR-7.8. Соглашение об именах ограничений

`Base.metadata = MetaData(naming_convention=NAMING_CONVENTION)` (`app/db/base.py`):

| Тип | Шаблон | Пример |
|---|---|---|
| PK | `pk_%(table_name)s` | `pk_orders` |
| FK | `fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s` | `fk_order_items_tenant_id_order_id_orders` |
| UNIQUE | `uq_%(table_name)s_%(column_0_N_name)s` | `uq_orders_tenant_id_idempotency_key` |
| INDEX | `ix_%(table_name)s_%(column_0_N_name)s` | `ix_orders_tenant_id_visit_id` |
| CHECK | `ck_%(table_name)s_%(constraint_name)s` | `ck_orders_status` (в модели `name="status"`) |

Самое длинное имя (`fk_menu_item_allergens_tenant_id_allergen_id_allergens`, 55 символов) укладывается в 63 байта PostgreSQL. Частичные и функциональные индексы получают явное `name=` (`uq_visits_open_table`, `ix_orders_pending_confirm`, …). Детерминированные имена нужны для стабильного autogenerate и для `downgrade` по имени.

---

## ADR-7.9. SQLAlchemy 2 async + asyncpg; встраивание в `Container`

**Решение.**
- Зависимости (`backend/pyproject.toml`, developer): `sqlalchemy[asyncio]>=2.0.36`, `asyncpg>=0.30`, `alembic>=1.14`, `tzdata` (на Windows у `zoneinfo` нет системной базы часовых поясов — нужна для проверки `tenants.timezone` и локального времени заведения). Драйвер — asyncpg (DEC-004; psycopg запрещён ruff).
- `app/db/session.py: Database(settings)` — `create_async_engine(DATABASE_URL, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW, pool_pre_ping=True, connect_args={"server_settings": {"application_name": "ai-waiter", "timezone": "UTC"}})`; `async_sessionmaker(engine, expire_on_commit=False)`. Методы `start()` (ничего не подключает), `stop()` (`engine.dispose()`), `ping()` (`SELECT 1`).
- `Container` получает поле `database: Database`. `build_container` создаёт его в обоих режимах одинаково (код БД не зависит от режима). Порядок запуска: `database → event_bus → rate_limiter → scheduler`, остановки — обратный (задачи планировщика могут писать в БД до своей остановки).
- `app/core/config.py`: `DATABASE_URL` становится **обязательным** (DEC-002); новые `DB_POOL_SIZE` (по умолчанию 5, `ge=1`), `DB_MAX_OVERFLOW` (5, `ge=0`). Обе — в `.env.example`. `TEST_DATABASE_URL` — **не** поле `Settings` (читается только тестами).
- `app/api/deps.py`:
  ```python
  def get_database(request: Request) -> Database: ...
  async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
      async with get_container(request).database.sessionmaker() as session:
          yield session
  SessionDep = Annotated[AsyncSession, Depends(get_session)]
  ```
  Транзакцию фиксирует сервис явным `await session.commit()`; незафиксированное откатывается при закрытии сессии. Автокоммита в зависимости нет — так SSE-эндпоинты (#11) и «сначала сохранить, потом звать ИИ» (NFR-3) управляют границей транзакции сами.
- `/health/ready`: ключ `"database"` (`ok`/`fail`) в обоих режимах, через `database.ping()` с тем же таймаутом 2 с; тело без текстов ошибок. **Вне stories #48–#54** (spec, вопрос 19): `Database.ping()` готов в #48, подключение к `/health/ready` — отдельная story; до неё ответ `/health/ready` не меняется.
- Фоновые задачи (#23) и arq-worker (`scaled`) получают `Database` из того же `Container` / создают свой в `on_startup` worker-а — решается в #23, интерфейс тот же.
- **Unit-тесты без БД (Windows-джоб) не ломаются:** `make_settings()` в `tests/conftest.py` добавляет фиктивный `DATABASE_URL=postgresql+asyncpg://test:test@db.invalid/test` (движок ленивый — соединения нет); `tests/doubles.py` получает `FakeDatabase` (тот же `_Lifecycle`: управляемые `start/stop/ping`), который подставляется в `build_container` фикстурой (monkeypatch `app.core.container.Database`). Тесты `/health/ready` обновляются под ключ `database` в той story, которая добавит проверку.

**Альтернативы.** Синхронный движок в потоке — противоречит стеку (ТЗ 8). Создание движка в модуле при импорте — нарушает «импорт `app.main` не читает окружение» (G3).

---

## ADR-7.10. Alembic: async `env.py`, ревизии по группам таблиц, обратимость, `alembic check`

**Решение.**
- `backend/alembic.ini`: `script_location = %(here)s/alembic`, `prepend_sys_path = .`, `path_separator = os`, `file_template = %%(rev)s_%%(slug)s`. **Без `sqlalchemy.url`** (строка подключения с паролем не попадает в репозиторий) и **без `timezone`** (требовал бы tzdata при генерации ревизий). Post-write hook форматирования через модуль, а не путь к exe (одинаково на Windows и Linux):
  ```ini
  [post_write_hooks]
  hooks = ruff_format
  ruff_format.type = module
  ruff_format.module = ruff
  ruff_format.options = format REVISION_SCRIPT_FILENAME
  ```
- `backend/alembic/env.py` — шаблон `alembic init -t async`: `target_metadata = Base.metadata` после `import app.models`; источник подключения по приоритету: `config.attributes["connection"]` (тесты передают готовое соединение) → `config.attributes["database_url"]` → `get_settings().database_url` (тот же `.env`, что у приложения). Онлайн-режим: `async_engine_from_config(..., poolclass=NullPool)` + `connection.run_sync(do_run_migrations)`; `context.configure(compare_type=True, compare_server_default=True)`; `transaction_per_migration=True`. Офлайн-режим (`--sql`) поддерживается — генерация SQL без БД.
- **Ревизии — по группам таблиц, линейная цепочка с ручными ID** (`alembic revision --autogenerate --rev-id 0001 -m tenants_tables`):

  | Ревизия | Story | Таблицы | Особое |
  |---|---|---|---|
  | `0001_tenants_tables` | #49 | `tenants`, `halls`, `tables` | проверка `server_encoding = UTF8` (иначе `RuntimeError` с понятным текстом, ADR-7.13) |
  | `0002_menu` | #50 | `categories`, `menu_items`, `menu_item_prices`, `menu_item_meta`, `allergens`, `menu_item_allergens` | — |
  | `0003_visits` | #51 | `visits`, `messages`, `cart_items` | частичный UNIQUE `uq_visits_open_table` |
  | `0004_orders` | #52 | `orders`, `order_items`, `order_events` | функция и триггер append-only (`op.execute`) |

  Обоснование: группы совпадают с доменами и, вероятно, с child stories — каждая story приносит свою ревизию и тест; ручные `0001…` читаемы и не дают «веток» при последовательной работе. Одна начальная ревизия на все 15 таблиц — отклонена: огромный дифф, нельзя сдавать stories по частям. Сжатие ревизий в будущем не делаем (после первого развёртывания история неизменна).
- **Обратимость:** каждая `downgrade()` удаляет ровно то, что создала `upgrade()`, в обратном порядке. db-тест: `upgrade head → downgrade base → upgrade head` на пустой схеме без ошибок, и после `downgrade base` в схеме не остаётся таблиц, кроме `alembic_version`. `downgrade` — для разработки и CI; в эксплуатации ошибки исправляются новой ревизией вперёд.
- **Соответствие моделей и миграций:** db-тест вызывает `alembic.command.check(cfg)` после `upgrade head` (Alembic ≥ 1.9: ошибка, если autogenerate видит различия). CHECK и триггеры autogenerate не сравнивает — для них отдельные db-тесты (ADR-7.2, ADR-7.6).
- **Применение миграций:** приложение при старте миграции **не** запускает (в `scaled` несколько процессов api устроили бы гонку). `scaled`: одноразовый сервис `migrate` в `deploy/docker-compose.yml` (якорь `x-app`, команда `alembic upgrade head`), `api` и `worker` — `depends_on: migrate: condition: service_completed_successfully`. `single` (Windows): `uv run alembic upgrade head` из `backend/` перед стартом службы (шаг установки/обновления в #30). Dockerfile уже копирует `backend/` целиком — `alembic.ini` и `alembic/` попадут в образ.

---

## ADR-7.11. Тесты с PostgreSQL: `TEST_DATABASE_URL`, схема из миграций, изоляция откатом

**Решение.**
- db-тесты лежат в `backend/tests/db/`, у каждого модуля `pytestmark = pytest.mark.db`. Подключение — только из `TEST_DATABASE_URL` (никогда из `DATABASE_URL`, чтобы тесты не стёрли рабочую БД). Защита: имя БД в `TEST_DATABASE_URL` обязано оканчиваться на `_test`, иначе `pytest.exit` с объяснением.
- Нет `TEST_DATABASE_URL`: локально db-тесты пропускаются (`skip` с причиной); при `CI=true` и выбранных db-тестах — ошибка (чтобы забытая переменная не дала «зелёный» пустой прогон).
- Схема создаётся **миграциями**, не `metadata.create_all` (тестируем то, что поедет в прод): сессионная синхронная фикстура `migrated_database` делает `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` и `alembic.command.upgrade(cfg, "head")`. Команды Alembic вызываются только из синхронных фикстур или через `asyncio.to_thread` — async `env.py` сам запускает `asyncio.run`, это нельзя делать из работающего цикла pytest-asyncio.
- Изоляция теста: фикстура `db_session` (function scope, совпадает с `asyncio_default_fixture_loop_scope = "function"`): движок с `NullPool` → соединение → `BEGIN` → `AsyncSession(bind=conn, join_transaction_mode="create_savepoint")` → после теста `ROLLBACK`. `commit()` в тестируемом коде фиксирует только SAVEPOINT, БД остаётся чистой. Тест обратимости миграций работает на той же БД и в конце возвращает схему в `head`.
- CI (`.github/workflows/ci.yml`, джоб `backend-services`): `POSTGRES_DB: ai_waiter_test`, env `TEST_DATABASE_URL: postgresql+asyncpg://ci:ci@localhost:5432/ai_waiter_test` (и `DATABASE_URL` на ту же БД). Комментарий о коде 5 обновить: с #7 db-тесты есть. Windows-джоб и Linux-джоб `backend` по-прежнему `-m "not db and not scaled"` — db-тестов не видят и PostgreSQL не требуют.
- Unit-тесты модели **без БД** (идут на обеих ОС): `tests/test_models_metadata.py` — инварианты `Base.metadata` (tenant_id, составные FK, типы денег/времени, наличие CHECK статусов, имена по соглашению); `tests/test_migrations_offline.py` — `alembic upgrade head --sql` (офлайн-генерация SQL) проходит и содержит все 15 таблиц и триггер.
- Локально на Windows (PostgreSQL как служба, Docker не нужен): создать роль и БД `ai_waiter_test` (ADR-7.13), задать `TEST_DATABASE_URL` в окружении сессии и запустить `.venv\Scripts\python.exe -m pytest -q -m db`.

---

## ADR-7.12. Сид-данные: `python -m app.seed`

**Решение.**
- CLI `python -m app.seed` (`app/seed/__main__.py`), подключение — из `Settings.database_url` (тот же `.env`) или `--database-url`. При `APP_ENV=prod` — отказ с кодом 2.
- **Идемпотентность:** заведение с фиксированным UUID `DEMO_TENANT_ID`; всё остальное — `INSERT … ON CONFLICT (естественный ключ) DO UPDATE`: аллергены по `(tenant_id, code)`, залы по `(tenant_id, name)`, столы по `qr_token`, категории и позиции по `(tenant_id, external_id)`, цены по `(menu_item_id, price_tier)`, мета по `menu_item_id`. Повторный запуск не плодит дублей и возвращает эталонные значения. Одна транзакция.
- **Данные вымышленные:** заведение «Demo Restoran», валюта AZN, часовой пояс `Asia/Baku`; 2 зала, 6 столов (один кабинет с тарифом `vip`, один неактивный) с детерминированными dev-токенами (`demo-table-01-…`, ≥ 22 символов, только для разработки — поэтому запрет в prod); 14 аллергенов ЕС с названиями AZ/RU; 4 категории, ~15 блюд с ценами `default`/`vip`; часть блюд с `allergens_verified = true` и списком аллергенов, часть — без флага (проверка AI-2), одно `is_hidden`, одно `is_available = false`. Без IP-адресов, ключей, реальных названий и цен заведения. Данные — Python-модуль `app/seed/data.py` (не файлы по путям — переносимость).
- В конце печатает относительные ссылки `/t/{token}` для локальной проверки.
- Тест (`tests/db/test_seed.py`): два запуска подряд → одинаковые счётчики строк; отказ при `APP_ENV=prod`.

---

## ADR-7.13. PostgreSQL на Windows-службе без Docker

**Решение.**
- Драйвер asyncpg работает с `ProactorEventLoop` — смены event loop policy нет (ADR-5 #6).
- **Кодировка и локаль БД:** создавать БД с `ENCODING 'UTF8' LOCALE 'C' TEMPLATE template0` (на Windows установщик может предложить `WIN1251` и локаль `Russian_Russia.1251`). Причины: кириллица и азербайджанская латиница без потерь; дамп с Windows восстанавливается на Linux VPS (ТЗ 9.3) — имён Windows-локалей там нет, `C` есть везде. Миграция `0001` проверяет `server_encoding` и падает с понятным текстом. Порядок, зависящий от языка, — не на уровне БД: `sort_key` сортируется побайтно (`COLLATE "C"`), что совпадает с поведением на обеих ОС.
- Только встроенные возможности PostgreSQL 16: `gen_random_uuid()` встроен, расширения (`pgcrypto`, `pg_trgm`) в #7 не нужны — не требуется суперпользователь. Если поиску меню (#10/#11) понадобится `pg_trgm`, это доверенное расширение (PG13+), его создаёт владелец БД.
- Роль приложения — владелец своей БД (`CREATE ROLE ai_waiter LOGIN PASSWORD '…'; CREATE DATABASE ai_waiter OWNER ai_waiter …`), не суперпользователь. Для тестов — отдельная `ai_waiter_test` с тем же владельцем (нужен `DROP SCHEMA public` в фикстуре — владелец БД это может, т.к. в PG15+ `public` принадлежит `pg_database_owner`).
- `DATABASE_URL` использует `localhost` (служба на той же машине) — без IP в репозитории и коде.
- `tzdata` в зависимостях (ADR-7.9): `zoneinfo.ZoneInfo("Asia/Baku")` на Windows без неё падает.
- README (раздел «Локальный запуск») получает команды `psql` для создания роли и БД, `uv run alembic upgrade head`, `uv run python -m app.seed`.

---

## ADR-7.14. Настройки заведения — `tenants.settings jsonb` с переопределениями

**Решение.** `tenants.settings jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(settings) = 'object')` хранит **только переопределения** порогов ТЗ 3.4 и правила бота (FR-19). Эффективные значения — Pydantic-модель `TenantSettings` с дефолтами из 3.4 (появляется вместе с первым потребителем: #22/#23/#26), валидация при записи из админки (#29). Языки, валюта, часовой пояс — отдельные колонки (по ним фильтруют и валидируют). Отдельная таблица `tenant_settings` (ключ-значение) — отклонена: типизация и валидация удобнее в Pydantic, а настроек немного.

---

## ERD

Ключевые колонки и связи; полный состав — «Словарь данных». Все стрелки внутри заведения — составные FK `(tenant_id, x_id)` (ADR-7.3). Пунктиром — таблицы вне #7 и ссылки без FK.

```mermaid
erDiagram
    tenants ||--o{ halls : "tenant_id"
    tenants ||--o{ tables : "tenant_id"
    tenants ||--o{ categories : "tenant_id"
    tenants ||--o{ allergens : "tenant_id"
    halls |o--o{ tables : "hall_id (nullable)"
    tables ||--o{ visits : "table_id"
    categories ||--o{ menu_items : "category_id"
    menu_items ||--|{ menu_item_prices : "по тарифам"
    menu_items ||--o| menu_item_meta : "1:1, данные админа"
    menu_items ||--o{ menu_item_allergens : ""
    allergens ||--o{ menu_item_allergens : ""
    visits ||--o{ messages : "CASCADE"
    visits ||--o{ cart_items : "CASCADE"
    menu_items ||--o{ cart_items : "RESTRICT"
    visits ||--o{ orders : "дозаказы FR-7"
    orders ||--|{ order_items : "CASCADE"
    menu_items ||--o{ order_items : "RESTRICT"
    orders ||--o{ order_events : "append-only"

    staff_users |o..o{ orders : "confirmed_by_staff_id, FK в #19"
    staff_users |o..o{ visits : "closed_by_staff_id, FK в #19"
    connectors }o..|| tenants : "#16"
    visits ||..o{ waiter_calls : "#22"
    visits ||..o| reviews : "#25"

    tenants {
        uuid id PK
        text name
        text currency "ISO 4217"
        text timezone "IANA"
        text_arr languages
        jsonb settings "переопределения 3.4"
    }
    halls {
        uuid id PK
        uuid tenant_id FK
        text name "UK tenant_id+name"
    }
    tables {
        uuid id PK
        uuid tenant_id FK
        uuid hall_id FK "nullable"
        text type "table|cabin"
        text price_tier
        text external_id "UK tenant_id+external_id"
        text qr_token UK "глобально"
        timestamptz token_issued_at
        bool is_active
    }
    categories {
        uuid id PK
        uuid tenant_id FK
        text external_id "UK tenant_id+external_id"
        text pos_name
        text sort_key
        bool is_hidden
    }
    menu_items {
        uuid id PK
        uuid tenant_id FK
        uuid category_id FK
        text external_id "UK tenant_id+external_id"
        text pos_name
        text currency
        bool is_available "стоп-лист"
        bool is_hidden "пропала из кассы"
    }
    menu_item_prices {
        uuid menu_item_id PK
        text price_tier PK
        uuid tenant_id FK
        numeric price "10,2"
    }
    menu_item_meta {
        uuid menu_item_id PK
        uuid tenant_id FK
        bool allergens_verified
        bool visible_to_ai
    }
    allergens {
        uuid id PK
        uuid tenant_id FK
        text code "UK tenant_id+code"
    }
    menu_item_allergens {
        uuid menu_item_id PK
        uuid allergen_id PK
        uuid tenant_id FK
    }
    visits {
        uuid id PK
        uuid tenant_id FK
        uuid table_id FK "1 open на стол"
        text status "open|closed"
        text lang "az|ru"
        timestamptz last_activity_at
        text closed_by "staff|pos|timeout"
    }
    messages {
        uuid id PK
        uuid tenant_id FK
        uuid visit_id FK
        text role "user|assistant"
        jsonb content "блоки Claude API"
        numeric cost_usd "12,6"
    }
    cart_items {
        uuid id PK
        uuid tenant_id FK
        uuid visit_id FK
        uuid menu_item_id FK
        int qty
        text comment
        numeric price_at_add "10,2"
    }
    orders {
        uuid id PK "order_id Integration API"
        uuid tenant_id FK
        uuid visit_id FK
        uuid idempotency_key "UK tenant_id+key"
        text status "8 значений 4.6"
        numeric total "10,2"
        uuid confirmed_by_staff_id "без FK до #19"
        numeric pos_total "10,2"
    }
    order_items {
        uuid id PK
        uuid tenant_id FK
        uuid order_id FK
        uuid menu_item_id FK
        text name_snapshot
        int qty
        numeric price_at_order "10,2"
        bool removed_by_staff
    }
    order_events {
        uuid id PK
        uuid tenant_id FK
        uuid order_id FK
        text type
        text actor_type
        uuid actor_id "без FK"
        jsonb payload
    }
    staff_users {
        uuid id PK
        uuid tenant_id FK
    }
    connectors {
        uuid id PK
        uuid tenant_id FK
    }
    waiter_calls {
        uuid id PK
        uuid visit_id FK
    }
    reviews {
        uuid id PK
        uuid visit_id FK
    }
```

---

## Словарь данных

Обозначения: **NN** — `NOT NULL`; `now()` — `DEFAULT now()`; «TS» — пара `created_at timestamptz NN now()`, `updated_at timestamptz NN now()` (обновляется ORM, `onupdate`). У всех таблиц с `id`: `id uuid PK DEFAULT gen_random_uuid()` (приложение передаёт UUIDv7). «UQ-tid» — `UNIQUE (tenant_id, id)` как цель составных FK. Длины текстов ограничены CHECK `char_length(...)` — защита от мусора в БД; бизнес-лимиты (например, `msg_max_chars`) проверяет API.

### Платформа и заведение (ревизия `0001_tenants_tables`)

**`tenants`** — без `tenant_id`.

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id` | uuid | ✓ | `gen_random_uuid()` | PK |
| `name` | text | ✓ | | CHECK длина 1–200 |
| `currency` | text | ✓ | `'AZN'` | CHECK `~ '^[A-Z]{3}$'` |
| `timezone` | text | ✓ | `'Asia/Baku'` | IANA, проверяет приложение (`zoneinfo` + tzdata) |
| `languages` | text[] | ✓ | `'{az,ru}'` | CHECK `cardinality >= 1 AND languages <@ '{az,ru}'` |
| `settings` | jsonb | ✓ | `'{}'` | CHECK `jsonb_typeof = 'object'` (ADR-7.14) |
| TS | | | | |

**`halls`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | PK; FK → `tenants` RESTRICT |
| `name` | text | ✓ | | CHECK длина 1–100 |
| `sort_key` | text | ✓ | `''` | |
| TS | | | | |

Индексы/уникальности: UQ-tid; `UNIQUE (tenant_id, name)` (зал из `PUT /tables` приходит только названием).

**`tables`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | PK; FK → `tenants` |
| `hall_id` | uuid | | | FK `(tenant_id, hall_id)` → `halls` RESTRICT |
| `name` | text | ✓ | | CHECK длина 1–100 |
| `type` | text | ✓ | `'table'` | CHECK `IN ('table','cabin')` |
| `price_tier` | text | ✓ | `'default'` | CHECK `~ '^[a-z][a-z0-9_]{0,31}$'` |
| `external_id` | text | | | CHECK длина 1–64; стол кассы (FR-15) |
| `qr_token` | text | ✓ | | **UNIQUE глобально**; CHECK `~ '^[A-Za-z0-9_-]{22,64}$'` (≥ 128 бит в base64url, FR-1) |
| `token_issued_at` | timestamptz | ✓ | `now()` | |
| `is_active` | boolean | ✓ | `true` | |
| TS | | | | |

Индексы: UQ-tid; `UNIQUE (tenant_id, external_id)` (NULL-ы не конфликтуют); `ix_tables_tenant_id_hall_id`. Перевыпуск токена (FR-1) — UPDATE `qr_token`, `token_issued_at`; старый токен перестаёт находиться.

### Меню (ревизия `0002_menu`)

**`categories`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | |
| `external_id` | text | ✓ | | CHECK длина 1–64 (у файлового импорта — свой идентификатор строки) |
| `pos_name` | text | ✓ | | название из кассы, админом не редактируется |
| `name_az`, `name_ru` | text | | | данные админа, CHECK длина ≤ 200 |
| `sort_key` | text | ✓ | `''` | сортировка `COLLATE "C"` |
| `is_hidden` | boolean | ✓ | `false` | пропала из снимка (INT-2) |
| `synced_at` | timestamptz | ✓ | `now()` | |
| TS | | | | |

Индексы: UQ-tid; `UNIQUE (tenant_id, external_id)`.

**`menu_items`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | |
| `category_id` | uuid | ✓ | | FK `(tenant_id, category_id)` → `categories` RESTRICT |
| `external_id` | text | ✓ | | CHECK длина 1–64 |
| `pos_name` | text | ✓ | | |
| `currency` | text | ✓ | | CHECK ISO 4217 |
| `station` | text | | | станция кухни/бара (информативно) |
| `sort_key` | text | ✓ | `''` | |
| `is_available` | boolean | ✓ | `true` | стоп-лист (FR-17) |
| `is_hidden` | boolean | ✓ | `false` | INT-2 |
| `synced_at` | timestamptz | ✓ | `now()` | |
| TS | | | | |

Индексы: UQ-tid; `UNIQUE (tenant_id, external_id)`; `ix_menu_items_tenant_id_category_id`. Индексы под поиск (`search_menu`, триграммы) — в #10/#11 по факту запросов.

**`menu_item_prices`** — PK `(menu_item_id, price_tier)`.

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `tenant_id` | uuid | ✓ | | FK → `tenants` |
| `menu_item_id` | uuid | ✓ | | FK `(tenant_id, menu_item_id)` → `menu_items` CASCADE |
| `price_tier` | text | ✓ | | CHECK шаблон тарифа |
| `price` | numeric(10,2) | ✓ | | CHECK `>= 0` |
| TS | | | | |

Цена для стола: тариф стола, при отсутствии — `default` (A.2: `vip` не передаётся, если `price_vip = 0`). Наличие тарифа `default` у каждой позиции проверяет синхронизация (#8/#16), не CHECK.

**`menu_item_meta`** — PK `menu_item_id` (1:1), строки создаёт только админка/сид; отсутствие строки = значения по умолчанию.

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `menu_item_id` | uuid | ✓ | | PK; FK `(tenant_id, menu_item_id)` → `menu_items` CASCADE |
| `tenant_id` | uuid | ✓ | | |
| `name_az`, `name_ru` | text | | | ≤ 200 |
| `description_az`, `description_ru` | text | | | ≤ 2000 |
| `ingredients_az`, `ingredients_ru` | text | | | состав, ≤ 2000 |
| `allergens_verified` | boolean | ✓ | `false` | AI-2, FR-16a |
| `spice_level` | smallint | | | CHECK 0–3 |
| `prep_minutes` | smallint | | | CHECK 1–240 |
| `weight_amount` | numeric(8,2) | | | CHECK `> 0` |
| `weight_unit` | text | | | CHECK `IN ('g','ml','pcs')`; CHECK `ck_menu_item_meta_weight`: оба NULL или оба заданы (локализуется на AZ/RU при показе) |
| `photo_path` | text | | | ключ в хранилище медиа: CHECK не начинается с `/` или `X:`, без `..` |
| `tags` | text[] | ✓ | `'{}'` | |
| `visible_to_ai` | boolean | ✓ | `true` | |
| TS | | | | |

**`allergens`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | |
| `code` | text | ✓ | | CHECK `~ '^[a-z][a-z0-9_]{0,31}$'` (`gluten`, `milk`, …) |
| `name_az`, `name_ru` | text | ✓ | | ≤ 100 |
| `sort_order` | smallint | ✓ | `0` | |
| TS | | | | |

Индексы: UQ-tid; `UNIQUE (tenant_id, code)`.

**`menu_item_allergens`** — PK `(menu_item_id, allergen_id)`.

| Колонка | Тип | NN | Ограничения |
|---|---|---|---|
| `tenant_id` | uuid | ✓ | |
| `menu_item_id` | uuid | ✓ | FK `(tenant_id, menu_item_id)` → `menu_items` CASCADE |
| `allergen_id` | uuid | ✓ | FK `(tenant_id, allergen_id)` → `allergens` RESTRICT — аллерген чужого заведения привязать нельзя |
| `created_at` | timestamptz | ✓ | `now()` |

Индекс: `ix_menu_item_allergens_tenant_id_allergen_id` (фильтр «без орехов» в `search_menu`).

### Визит (ревизия `0003_visits`)

**`visits`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | |
| `table_id` | uuid | ✓ | | FK `(tenant_id, table_id)` → `tables` RESTRICT |
| `status` | text | ✓ | `'open'` | CHECK `IN ('open','closed')` |
| `lang` | text | ✓ | | CHECK `IN ('az','ru')` (FR-2) |
| `opened_at` | timestamptz | ✓ | `now()` | |
| `last_activity_at` | timestamptz | ✓ | `now()` | для `visit_idle_close_hours` |
| `closed_at` | timestamptz | | | |
| `closed_by` | text | | | CHECK `IN ('staff','pos','timeout')` |
| `closed_by_staff_id` | uuid | | | без FK до #19 (ADR-7.7) |
| TS | | | | |

CHECK `ck_visits_closed_state`: `(status = 'open' AND closed_at IS NULL AND closed_by IS NULL) OR (status = 'closed' AND closed_at IS NOT NULL AND closed_by IS NOT NULL)`.
Индексы: UQ-tid; **`uq_visits_open_table`** UNIQUE `(table_id) WHERE status = 'open'`; `ix_visits_tenant_id_table_id_opened_at`; `ix_visits_open_last_activity` `(last_activity_at) WHERE status = 'open'` (межарендное подметание забытых визитов, #23).

**`messages`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | |
| `visit_id` | uuid | ✓ | | FK `(tenant_id, visit_id)` → `visits` CASCADE |
| `role` | text | ✓ | | CHECK `IN ('user','assistant')` (термины Claude API; tool_result — блоки в `user`) |
| `text` | text | | | плоский текст для показа и экспорта (FR-18); ≤ 8000 |
| `content` | jsonb | | | блоки Claude API (`text`, `tool_use`, `tool_result`) — «вызовы функций» ТЗ 7; CHECK `jsonb_typeof = 'array'` |
| `model` | text | | | модель ответа (из конфигурации, AI-8) |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens` | integer | ✓ | `0` | CHECK `>= 0` |
| `cost_usd` | numeric(12,6) | ✓ | `0` | CHECK `>= 0` (исключение ADR-7.4) |
| `latency_ms` | integer | | | NFR-6 |
| `redacted_at` | timestamptz | | | очистка по `dialog_retention_days` (открытый вопрос 6) |
| `created_at` | timestamptz | ✓ | `now()` | |

CHECK `ck_messages_content_or_redacted`: `content IS NOT NULL OR redacted_at IS NOT NULL`.
Индексы: `ix_messages_tenant_id_visit_id_created_at`; `ix_messages_retention` `(created_at) WHERE redacted_at IS NULL`.
Личных данных нет (NFR-5): ни IP, ни идентификатора устройства, ни имени. Содержимое — данные, а не инструкции (AI-3): при сборке промпта (#11) оборачивается как пользовательский ввод.

**`cart_items`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | |
| `visit_id` | uuid | ✓ | | FK `(tenant_id, visit_id)` → `visits` CASCADE |
| `menu_item_id` | uuid | ✓ | | FK `(tenant_id, menu_item_id)` → `menu_items` RESTRICT |
| `qty` | integer | ✓ | | CHECK 1–99 |
| `comment` | text | ✓ | `''` | ≤ 200 |
| `price_tier` | text | ✓ | | снимок тарифа стола, CHECK шаблон тарифа |
| `price_at_add` | numeric(10,2) | ✓ | | CHECK `>= 0` (INT-3) |
| TS | | | | |

Уникальность: `UNIQUE (tenant_id, visit_id, menu_item_id, comment)` (ADR-7.5; индекс обслуживает и выборку корзины визита).

### Заказ (ревизия `0004_orders`)

**`orders`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | `id` = `order_id` Integration API |
| `visit_id` | uuid | ✓ | | FK `(tenant_id, visit_id)` → `visits` RESTRICT |
| `idempotency_key` | uuid | ✓ | | `UNIQUE (tenant_id, idempotency_key)` (NFR-3, ADR-7.3) |
| `status` | text | ✓ | `'submitted'` | CHECK 8 значений ТЗ 4.6 |
| `price_tier` | text | ✓ | | снимок тарифа стола |
| `total` | numeric(10,2) | ✓ | | CHECK `>= 0` |
| `currency` | text | ✓ | | CHECK ISO 4217 |
| `confirmed_by_staff_id` | uuid | | | без FK до #19 (ТЗ 7: `confirmed_by`; в Integration API отдаётся как `confirmed_by.staff_id`) |
| `confirmed_at` | timestamptz | | | |
| `reject_reason` | text | | | ≤ 500 |
| `pos_ref` | text | | | номер чека кассы, ≤ 64 |
| `pos_total` | numeric(10,2) | | | CHECK `>= 0` (INT-7) |
| `pos_error` | text | | | ≤ 1000 (INT-6) |
| `sent_to_pos_at` | timestamptz | | | первая выдача коннектору |
| `pos_acked_at` | timestamptz | | | |
| TS | | | | `created_at` = время отправки гостем |

CHECK: `ck_orders_status`; `ck_orders_confirmed_at` — `status NOT IN ('confirmed','sent_to_pos','in_pos','pos_failed') OR confirmed_at IS NOT NULL`; `ck_orders_reject_reason` — `status <> 'rejected' OR reject_reason IS NOT NULL` (FR-12). `confirmed_by_staff_id` не обязателен (прототип #14 без входа персонала).
Индексы: UQ-tid; `ix_orders_tenant_id_visit_id`; `ix_orders_tenant_id_status_created_at` (лента официанта); `ix_orders_pending_confirm` `(created_at) WHERE status IN ('submitted','edited')` (межарендное подметание эскалаций, #23); `ix_orders_pos_queue` `(tenant_id, confirmed_at, id) WHERE status IN ('confirmed','sent_to_pos')` (`GET /orders?after=` с курсором `(confirmed_at, id)`, INT-5, #17).

**`order_items`**

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | |
| `order_id` | uuid | ✓ | | FK `(tenant_id, order_id)` → `orders` CASCADE |
| `menu_item_id` | uuid | ✓ | | FK `(tenant_id, menu_item_id)` → `menu_items` RESTRICT |
| `name_snapshot` | text | ✓ | | `pos_name` на момент заказа |
| `qty` | integer | ✓ | | CHECK 1–99 |
| `price_at_order` | numeric(10,2) | ✓ | | CHECK `>= 0` |
| `comment` | text | ✓ | `''` | ≤ 200 |
| `removed_by_staff` | boolean | ✓ | `false` | FR-13 (строка не удаляется) |
| TS | | | | |

Уникальность: `UNIQUE (tenant_id, order_id, menu_item_id, comment)`.

**`order_events`** — append-only (ADR-7.6).

| Колонка | Тип | NN | Default | Ограничения |
|---|---|---|---|---|
| `id`, `tenant_id` | uuid | ✓ | | |
| `order_id` | uuid | ✓ | | FK `(tenant_id, order_id)` → `orders` RESTRICT |
| `type` | text | ✓ | | CHECK `IN ('created','status_changed','item_removed','item_qty_changed','pos_ack','pos_error','pos_total_mismatch','manual_pos_entry')` |
| `from_status`, `to_status` | text | | | CHECK значения из `OrderStatus` |
| `actor_type` | text | ✓ | | CHECK `IN ('guest','staff','connector','system')` |
| `actor_id` | uuid | | | мягкая ссылка (ADR-7.7) |
| `payload` | jsonb | ✓ | `'{}'` | CHECK `jsonb_typeof = 'object'`; для правок — `{order_item_id, qty_before, qty_after}` и т.п. |
| `created_at` | timestamptz | ✓ | `now()` | |

CHECK `ck_order_events_status_change`: `type <> 'status_changed' OR to_status IS NOT NULL`. Индекс `ix_order_events_tenant_id_order_id_created_at`. Триггер `trg_order_events_append_only`.

---

## API Contracts

Новых HTTP-эндпоинтов в #7 нет. Изменяется:

| Method | Path | Кто | Request | Response | Ошибки |
|--------|------|-----|---------|----------|--------|
| GET | `/health/ready` (отдельная story после #48) | все | — | `200 {"status":"ready","checks":{"database":"ok","redis":"skipped"}}` | `503 {"status":"not_ready","checks":{"database":"fail",…}}` без деталей |

CLI: `alembic upgrade head` / `alembic downgrade -1` (из `backend/`), `python -m app.seed [--database-url URL]` (код 0 — успех, 2 — запрет в prod, 1 — ошибка БД).
Контрактные решения для будущих API, следующие из модели: деньги — строка `"12.50"`; `id` — UUID-строки; время — ISO 8601 с зоной; `qty` в Integration API — строка; `confirmed_by.staff_id` — UUID-строка (открытый вопрос 1). TS-типы в #7 не нужны (нет ответов API с моделью).

---

## События и фоновые задачи

Не публикуются и не регистрируются. Модель готовит опору для #23: подметание эскалаций (`ix_orders_pending_confirm`), автозакрытие визитов (`ix_visits_open_last_activity`), очистка диалогов (`ix_messages_retention`) — все через `@registry.periodic` и запросы к БД (DEC-001: отложенные задачи в `single` теряются при рестарте, поэтому таймеры — «подметание» БД). Межарендные выборки допустимы только в этих задачах; каждое найденное изменение пишется с `tenant_id` строки.

---

## ИИ

Таблицы ИИ не меняют поведение, но фиксируют правила раздела 5:
- AI-1: меню в промпт не кладётся — tools (#11) читают `menu_items`/`menu_item_prices`/`menu_item_meta` по `tenant_id` визита; `visible_to_ai = false` и `is_hidden = true` не попадают в выдачу tools.
- Функции отправки заказа у ИИ нет: `orders` создаёт только `POST /orders` (#12) по кнопке, `cart_*` tools пишут только `cart_items`.
- AI-2: `allergens_verified` в `menu_item_meta`, по умолчанию `false`; пустой `menu_item_allergens` без флага = «неизвестно».
- AI-3: `messages.text`/`content` и описания блюд — данные; в промпт попадают как пользовательский контент/результат tool, не как системные инструкции.
- AI-7: `msg_per_visit` — подсчёт `messages` (`role = 'user'`, без tool_result) по визиту через `ix_messages_tenant_id_visit_id_created_at`; `msg_per_table_hour` — `RateLimiter` (#26).
- AI-8 / NFR-6: `messages.model`, токены, `cost_usd`, `latency_ms`.

---

## Security

- **Tenant-изоляция:** `tenant_id NOT NULL` во всех таблицах заведения; составные FK исключают межарендные ссылки на уровне БД (ADR-7.3); бизнес-уникальности в границах заведения (нет межарендного оракула по `idempotency_key`/`external_id`). Unit-тест метаданных не даёт добавить таблицу без `tenant_id`. RLS — подготовлено, не включено (обоснование в ADR-7.3).
- **QR-токен:** глобально уникален, CHECK формата ≥ 22 символов base64url (≥ 128 бит, FR-1); генерация — `secrets.token_urlsafe(32)` в #9/#27. Хранится открытым текстом (нужен для повторной печати; открытый вопрос 5).
- **Секреты:** `alembic.ini` без строки подключения; `DATABASE_URL` и `TEST_DATABASE_URL` только в env; роль приложения — не суперпользователь (ADR-7.13). Сид — только вымышленные данные, запрет в `prod` (детерминированные dev-токены из публичного репозитория не должны попасть в рабочую БД).
- **Целостность журнала:** `order_events` защищён триггером от UPDATE/DELETE (ADR-7.6).
- **SQL-инъекции:** только ORM/параметризованные запросы; `op.execute` в миграциях — только статический SQL.
- **NFR-5:** в `messages` нет личных данных; очистка по `dialog_retention_days` (#23).
- **Тестовая БД:** имя обязано оканчиваться на `_test` — тесты не могут снести рабочую БД.
- **Ошибки БД в `/health/ready`:** только `"fail"`, детали — в лог.

---

## Трассировка: требования ТЗ ↔ таблицы

| Требование | Где в модели |
|---|---|
| FR-1 вход по QR, отзыв токена | `tables.qr_token` (UNIQUE, CHECK формата), `token_issued_at`, `is_active` |
| FR-2 язык | `visits.lang`, `tenants.languages` (первый элемент — язык по умолчанию) |
| FR-3 меню по тарифу стола | `categories`, `menu_items`, `menu_item_prices`, `menu_item_meta`, `tables.price_tier` |
| FR-4 состав, острота, время | `menu_item_meta.ingredients_*`, `spice_level`, `prep_minutes`, `weight_amount`/`weight_unit` |
| FR-5 корзина, комментарий | `cart_items` (`qty`, `comment`, UNIQUE с комментарием) |
| FR-6 явная отправка | `orders`, `order_items`, `orders.idempotency_key` |
| FR-7 дозаказ | несколько `orders` на один `visit_id` |
| FR-9 статус для гостя | `orders.status`, `reject_reason`, `order_events` |
| FR-12 подтверждение, эскалация | `orders.status` (`escalated`), `confirmed_at`, `ix_orders_pending_confirm` |
| FR-13 правка официантом | `order_items.removed_by_staff`, `qty`, `order_events` (`item_removed`, `item_qty_changed`) |
| FR-14a закрытие визита | `visits.status`, `closed_by`, `closed_by_staff_id` |
| FR-15 столы, тариф, связь с кассой | `tables.type`, `price_tier`, `external_id`, `halls` |
| FR-16 данные админа | `menu_item_meta`, `categories.name_az/ru` |
| FR-16a аллергены | `allergens`, `menu_item_allergens`, `menu_item_meta.allergens_verified` |
| FR-17 стоп-лист | `menu_items.is_available` |
| FR-18 диалоги | `messages.text` |
| FR-19, FR-21 настройки, правила бота | `tenants.settings`, `currency`, `timezone`, `languages` |
| FR-20 состояние интеграции | `orders.pos_error`, `pos_total` (+ `connectors` в #16) |
| FR-8, FR-10, FR-11, FR-14 | вне #7: `waiter_calls` (#22), `reviews` (#25), `staff_users` (#19) |
| INT-1 снимок меню | `menu_items.synced_at`, `categories.synced_at` (хеш — `connectors`, #16) |
| INT-2 связь по `external_id`, скрытие | `UNIQUE (tenant_id, external_id)`, `is_hidden` |
| INT-3 перепроверка цены | `cart_items.price_at_add`, `price_tier`, `order_items.price_at_order` |
| INT-5 доставка «как минимум один раз» | `orders.id` (UUID = `order_id`), `sent_to_pos_at`, `ix_orders_pos_queue` |
| INT-6 ошибка кассы | статус `pos_failed`, `orders.pos_error`, событие `pos_error` |
| INT-7 расхождение суммы | `orders.pos_total`, событие `pos_total_mismatch` |
| 4.6 жизненный цикл | CHECK `ck_orders_status`, `ORDER_TRANSITIONS`, `order_events` |
| AI-1, AI-2, AI-3, AI-7, AI-8 | см. раздел «ИИ» |
| NFR-3 надёжность, идемпотентность | `UNIQUE (tenant_id, idempotency_key)`, явный commit до ИИ (ADR-7.9) |
| NFR-4 безопасность | ADR-7.3, CHECK токена, раздел Security |
| NFR-5 персональные данные | `messages` без PII, `redacted_at` |
| NFR-6 наблюдаемость | `messages.*_tokens`, `cost_usd`, `latency_ms`, `model` |
| NFR-8 переносимость | ADR-7.13 (UTF8, `C`, без расширений), конфигурация из env |
| NFR-9 бэкапы | всё состояние в одной БД; локаль `C` — дамп восстанавливается на Linux |
| ТЗ 7 «Миграции — Alembic» | ADR-7.10 |

---

## Module Structure (code stubs)

Создано architect-ом (без импорта SQLAlchemy на уровне модуля — зависимостей ещё нет; `ruff check`, `ruff format --check`, `pytest -m "not db and not scaled"` зелёные):

```
backend/app/db/__init__.py        # описание пакета
backend/app/db/base.py            # NAMING_CONVENTION (готово), Base — в docstring
backend/app/db/ids.py             # new_id() -> uuid.UUID  (NotImplementedError)
backend/app/db/mixins.py          # UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin — пустые классы с описанием колонок
backend/app/db/session.py         # Database: __init__/engine/sessionmaker/start/stop/ping/session (NotImplementedError)
backend/app/models/__init__.py    # список модулей; импорт всех моделей для metadata
backend/app/models/enums.py       # OrderStatus, ORDER_TRANSITIONS, CONFIRMED_STATUSES, OrderEventType, ActorType,
                                  # VisitStatus, VisitClosedBy, TableType, MessageRole, Lang, шаблоны CHECK (готово);
                                  # can_transition() (NotImplementedError)
backend/app/models/reference.py   # EU14_ALLERGEN_CODES (готово)
backend/app/models/tenant.py      # Tenant, Hall, Table — docstring
backend/app/models/menu.py        # Category, MenuItem, MenuItemPrice, MenuItemMeta, Allergen, MenuItemAllergen — docstring
backend/app/models/visit.py       # Visit, Message, CartItem — docstring
backend/app/models/order.py       # Order, OrderItem, OrderEvent — docstring
backend/app/seed/__init__.py      # описание
backend/app/seed/__main__.py      # main(argv) -> int (NotImplementedError)
```

Создаёт/меняет developer:

```
backend/pyproject.toml            # + sqlalchemy[asyncio], asyncpg, alembic, tzdata; uv.lock — `uv lock`
backend/uv.lock
backend/alembic.ini               # ADR-7.10
backend/alembic/env.py            # async, источники подключения по приоритету
backend/alembic/script.py.mako
backend/alembic/versions/0001_tenants_tables.py
backend/alembic/versions/0002_menu.py
backend/alembic/versions/0003_visits.py
backend/alembic/versions/0004_orders.py
backend/app/db/*.py, app/models/*.py   # заполнить заглушки (Mapped-модели)
backend/app/seed/data.py          # вымышленные демо-данные
backend/app/core/config.py        # DATABASE_URL обязателен; DB_POOL_SIZE, DB_MAX_OVERFLOW
backend/app/core/container.py     # Container.database, порядок start/stop
backend/app/api/deps.py           # get_database, get_session, SessionDep
backend/app/api/health.py         # проверка "database" — отдельная story (spec, вопрос 19)
backend/tests/conftest.py         # фиктивный DATABASE_URL в make_settings, подмена Database на FakeDatabase
backend/tests/doubles.py          # FakeDatabase
backend/tests/test_models_metadata.py     # без БД: инварианты metadata
backend/tests/test_migrations_offline.py  # без БД: alembic upgrade head --sql
backend/tests/test_ids.py                 # без БД: UUIDv7 (версия, вариант, монотонность по времени)
backend/tests/test_enums.py               # без БД: переходы ORDER_TRANSITIONS
backend/tests/db/__init__.py
backend/tests/db/conftest.py              # TEST_DATABASE_URL, guard *_test, migrated_database, db_session
backend/tests/db/test_migrations.py       # upgrade/downgrade/upgrade, alembic check
backend/tests/db/test_check_constraints.py # CHECK статусов = перечисления; триггер order_events
backend/tests/db/test_tenant_isolation.py # межарендный FK отвергается БД
backend/tests/db/test_constraints.py      # уникальности, деньги >= 0, один open-визит на стол
backend/tests/db/test_seed.py             # идемпотентность, запрет в prod
.env.example                      # DATABASE_URL обязателен; DB_POOL_SIZE, DB_MAX_OVERFLOW; TEST_DATABASE_URL (закомментирован)
.github/workflows/ci.yml          # backend-services: POSTGRES_DB ai_waiter_test, TEST_DATABASE_URL
deploy/docker-compose.yml         # сервис migrate (x-app, alembic upgrade head), depends_on у api/worker
README.md                         # создание роли и БД на Windows/Linux, миграции, сид, db-тесты
```

Раскладка отличается от предварительной пометки в arch #6 (`app/core/db.py`): слой БД — отдельный пакет `app/db/`, модели — `app/models/` по доменам, потому что модулей больше одного и `app/core` отведён под инфраструктурные интерфейсы режимов.

---

## Сверка с открытыми вопросами spec (`docs/specs/feature-7-data-model.md`)

Spec оставляет окончательные решения architect-у. Принятые рекомендации analyst-а: 3 (`external_id`), 4 (валюта), 5 (`price_tier`), 6 (text + CHECK), 7 (без soft-delete), 9 (`price_at_add` и `price_tier` в корзине), 11 (один открытый визит), 13 (состав #7), 14 (`edited` как статус), 15 (`idempotency_key` в границах заведения), 16 (аллергены на заведение, `sort_order`), 17 (вес — число и единица), 18 (`tenants` без `slug`/`is_active`, только переопределения в `settings`), 19 (проверка БД в `/health` — отдельная story), 20 (savepoint + skip локально / ошибка в CI), 21 (`created_at`/`updated_at` везде, кроме журналов; у `visits` — `opened_at` + `updated_at`), 22 (`qr_token` открыто).

**Отличия от рекомендаций spec — stories нужно обновить:**

| Вопрос spec | Рекомендация analyst-а | Решение arch | Где обосновано | Что поправить |
|---|---|---|---|---|
| 1. Тип PK | `bigint` identity, `orders.id` — uuid | UUIDv7 во всех таблицах | ADR-7.1 | #48–#52: типы `id`/`tenant_id`/ссылок на персонал — `uuid`; Out of Scope spec («`bigint` без внешнего ключа») → `uuid` |
| 2. Межарендные связи | без составных FK, проверка в сервисах | составные FK `(tenant_id, x_id)` | ADR-7.3 | #49–#52: AC «межарендная ссылка отвергается БД» (тест `test_tenant_isolation.py`) |
| 8. Стоимость ИИ | `tokens_in`, `tokens_out`, `cost`, `tool_calls` | `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens` (имена как в `usage` Claude API), `cost_usd NUMERIC(12,6)`, `content jsonb` (полные блоки, включая tool_use/tool_result), `latency_ms`, `redacted_at` | ADR-7.4, словарь `messages` | #51 |
| 10. Тип количества | `NUMERIC(10,3)` | `integer` 1–99 (Integration API всё равно передаёт строку) | ADR-7.4, вопрос 4 ниже | #51, #52 (AC «`qty <= 0` отклоняется» остаётся верным) |
| 12. Значения `visits.closed_by` | `waiter`/`pos`/`timeout` | `staff`/`pos`/`timeout` (закрыть визит может и администратор) | словарь `visits` | #51 |
| 23. `name_snapshot` | название на языке визита | `pos_name` на момент заказа (официант без `push_order` ищет блюдо в кассе по кассовому названию); локализованное имя гостю — из `menu_item_meta` | ADR-7.4 | #52 |
| 24. Каталог миграций | `backend/migrations/` | `backend/alembic/` (по умолчанию Alembic и как заявлено в arch #6) | ADR-7.10 | #48 |

Имена колонок приведены к spec/ТЗ: `tables.type` (не `kind`), `orders.confirmed_by_staff_id`, `visits.closed_by_staff_id`, `cart_items.price_at_add`.

---

## Открытые вопросы по модели данных (с рекомендациями)

| # | Вопрос | Рекомендация |
|---|---|---|
| 1 | В ТЗ 4.4 `confirmed_by.staff_id: 7` — целое, а ключи UUID (ADR-7.1). | Поправить пример ТЗ на UUID-строку; `order_id` уже UUID. |
| 2 | Несколько телефонов за одним столом: общий визит — значит общие корзина, чат и язык? | v1: общий визит и корзина (ТЗ 7), общий журнал `messages`; язык ответа — по последнему сообщению (AI-6), `visits.lang` — последний выбранный. Если понадобятся раздельные чаты — `messages.device_id uuid NULL` (случайный, без PII) в #9. |
| 3 | Кто открывает визит (ТЗ 13, вопрос 8). | Первое сканирование открывает визит автоматически; один открытый визит на стол (`uq_visits_open_table`). Режим «визит открывает официант» — позже настройкой в `tenants.settings`. |
| 4 | Дробные количества (полпорции, на вес)? | v1 — целые 1–99; Integration API уже передаёт `qty` строкой, переход на `NUMERIC(10,3)` — одна миграция. |
| 5 | Хранить `qr_token` открытым текстом или хешем? | Открытым (как в ТЗ 7): токен напечатан на столе, нужен для повторной печати PDF; защита — отзыв/перевыпуск и подтверждение заказа официантом. |
| 6 | `dialog_retention_days`: удалять сообщения или обезличивать? | Обезличивать (`text`, `content` → NULL, `redacted_at`), токены и стоимость оставлять — нужны для метрик стоимости визита (раздел 11). |
| 7 | Сортировка по `sort_key` (`vid` кассы — строка цифр). | Хранить строкой, сортировать `COLLATE "C"`; коннектор обязан давать ключи фиксированной ширины (в «restoran» так и есть: 2 и 5 цифр). |
| 8 | `weight` — свободный текст или число? | Принята рекомендация spec: `weight_amount` + `weight_unit` (`g`/`ml`/`pcs`) — одинаково показывается на двух языках и сравнивается. |
| 9 | Где хранить столы кассы из `PUT /tables` (возможность `tables`) до сопоставления? | Отдельная таблица `pos_tables` в #16; в `tables.external_id` — результат сопоставления админом (FR-15). |
| 10 | Владелец платформы — строка `staff_users` без заведения? | Отдельная таблица `platform_users` без `tenant_id` (#16/#19): `staff_users.tenant_id` остаётся `NOT NULL`. |
| 11 | Можно ли править заказ в статусе `escalated` (ТЗ 4.6 разрешает из него только `confirmed`/`rejected`)? | Разрешить `escalated → edited` (FR-13: правка «перед подтверждением»); до решения `ORDER_TRANSITIONS` следует ТЗ буквально. |
| 12 | Как отмечается ручной ввод в кассу после `pos_failed`? | Статус остаётся `pos_failed`, пишется событие `manual_pos_entry` (уже в `OrderEventType`); отдельный статус — только если понадобится в метриках. |
| 13 | Пороги ТЗ 3.4 в `tenants.settings`: полная копия или переопределения? | Только переопределения (ADR-7.14) — изменение дефолтов в коде применяется ко всем заведениям без миграции данных. |
| 14 | Теги блюд — свободные или справочник? | Свободный `text[]` в v1 (FR-16); справочник — если админке понадобится выбор из списка. |
| 15 | Иерархия категорий? | Плоский список (в кассе `type` плоский); `parent_id` — при подключении кассы с вложенными категориями. |
| 16 | Валюта позиции отличается от валюты заведения? | Синхронизация отклоняет такие позиции с ошибкой коннектору (ТЗ: одна валюта у заведения). |
