# Story #63: Журнал синхронизаций меню с пропуском неизменённого снимка

*Parent: #8. Spec: docs/specs/feature-8-menu-import.md (AC-3).*

---

## 📋 Задача (analyst)

**AC:** Given снимок применён, в `menu_sync_runs` `applied` с хешем When тот же снимок (другой порядок позиций) без force применяется снова Then таблицы меню не меняются (`updated_at`, `synced_at` прежние), в `menu_sync_runs` запись `unchanged` с тем же хешем, источником и временем
**Роли:** оператор; позже администратор (FR-20, #29)
**ТЗ:** INT-1, FR-20, INT-4, NFR-6
**Arch:** ADR-8.5 — таблица `menu_sync_runs`, ревизия `0005_menu_sync_runs`, модель `app/models/menu_sync.py`; статусы `MenuSyncStatus` (`applied`/`unchanged`/`rejected`), источник `MenuSyncSource` (`file`/`connector`); `last_applied_hash`, `record_rejected_run`; `connectors.last_menu_hash` в #16 не нужен
**Ограничения:** показ в админке (#29), алерт `menu_stale_alert_min` (#23), `connectors` и `menu_sync_runs.connector_id` (#16), очистка журнала (#23)
**Зависимости:** #62
**Spec:** docs/specs/feature-8-menu-import.md

---

## 🏗️ Архитектура (architect)

**ADR:** ADR-8.5 (журнал и хеш, уточнение ADR-7.7); DEC-012; DEC-009/DEC-010 (обязательные дополнения тестов)
**Таблицы:** `menu_sync_runs` (новая), tenant_id: да — `id`, `tenant_id`, `source` (`file`/`connector`), `source_ref` (≤ 255, имя файла без пути), `status` (`applied`/`unchanged`/`rejected`), `snapshot_hash` (`^[0-9a-f]{64}$`), `started_at`, `finished_at`, `counts` jsonb object, `issues` jsonb array, `created_at`; CHECK `hash_state` (`rejected` или хеш есть), `finished_at >= started_at`; `uq_menu_sync_runs_tenant_id_id`; `ix_menu_sync_runs_tenant_id_finished_at`; без `updated_at`
**Миграция:** `backend/alembic/versions/0005_menu_sync_runs.py`, `down_revision = "0004"`, обратимая
**API:** нет (показ в админке — #29)
**События/задачи:** нет; очистка журнала — #23
**ИИ-tools:** не затронуты
**Security:** в журнал не пишется путь к файлу и содержимое; значения ячеек в `issues` обрезаны до 60 символов, не больше 100 записей
**Code stubs:**
- `backend/app/models/menu_sync.py` — `MenuSyncRun` (подключить в `app/models/__init__.py` вместе с ревизией)
- `backend/app/models/enums.py` — `MenuSyncSource`, `MenuSyncStatus` (уже добавлены)
- `backend/app/menu_sync/snapshot.py` — `snapshot_hash(snapshot) -> str` (SHA-256 канонического JSON после `resolve_currency`)
- `backend/app/menu_sync/service.py` — `last_applied_hash(session, tenant_id) -> str | None` (последний `applied`/`unchanged`, любой источник); `record_rejected_run(session, *, tenant_id, source, source_ref, issues, snapshot_hash=None) -> uuid.UUID`; шаги 3 (хеш совпал и нет `force` → `unchanged`, таблицы меню не трогаются) и 6 (строка журнала) в `apply_menu_snapshot`
**Статус:** в коде `unchanged`, не `skipped`
**Тесты:** unit — хеш; `EXPECTED_TABLES`, `EXPECTED_CHECKS["menu_sync_runs"] = {source, source_ref, status, snapshot_hash, hash_state, finished_at, counts, issues}`, `REVISION_TABLES["0005"]` в `tests/test_migrations_offline.py` и `tests/db/test_migrations.py`, `ENUM_CHECKS` (source, status); db `tests/db/test_menu_sync_runs.py`; db-тесты #62 проходят без правок
**Зависимости:** #62
**Arch doc:** docs/arch/feature-8-menu-import.md (раздел «Истории — файлы, тесты, порядок»)

---

## 💻 Разработка (developer)

**Branch:** story/63-menu-import (от feature/8-menu-import на 4a280b5, worktree s63)
**Новые файлы:**
- backend/alembic/versions/0005_menu_sync_runs.py — таблица `menu_sync_runs`, `down_revision = "0004"`, обратимая, единственный head
- backend/tests/test_menu_sync_runs.py — unit: хеш, `journal_source_ref`
- backend/tests/db/test_menu_sync_runs.py — db: AC #63, `force`, другой источник, dry-run, rejected после отката, лимит проблем, изоляция заведений, CHECK

**Изменённые файлы:**
- backend/app/models/__init__.py — подключён `menu_sync`; backend/app/models/menu_sync.py — docstring
- backend/app/menu_sync/snapshot.py — `snapshot_hash`: `model_dump(mode="json")` (деньги — строка с двумя знаками, `null` явно), категории и позиции по `external_id` (при равенстве — по канонической записи), `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, SHA-256
- backend/app/menu_sync/service.py — `last_applied_hash` (последний `applied`/`unchanged` заведения, `ORDER BY finished_at DESC, id DESC`), шаги 3 и 6 `apply_menu_snapshot`, `record_rejected_run`, `journal_source_ref`, `_insert_run`
- backend/tests/test_models_metadata.py, test_migrations_offline.py, db/test_migrations.py — `EXPECTED_TABLES`, `EXPECTED_CHECKS["menu_sync_runs"]`, `REVISION_TABLES["0005"]`, `ENUM_CHECKS`; офлайн-тест «15 таблиц» сравнивает с объединением `REVISION_TABLES` (16)
- backend/tests/db/test_seed.py — `EXPECTED_COUNTS["menu_sync_runs"] = 0`
- backend/tests/db/test_menu_sync_apply.py — две строки AC #62 (`snapshot_hash is None`, `run_id is None`) заменены на `is not None`: они проверяли поведение до #63

**Решения:**
- `started_at`/`finished_at` — часы приложения (`datetime.now(UTC)`), а не `now()`: внутри транзакции `now()` равен её началу и может оказаться раньше `started_at` (CHECK `finished_at >= started_at`); `finished_at = max(now, started_at)`.
- Пробный прогон считает хеш и возвращает статус, который дало бы применение (`applied`/`unchanged`), но журнал не пишет (`run_id = None`).
- `rejected` в `apply_menu_snapshot` не журналируется (вызывающий откатывает транзакцию). `report.snapshot_hash`: `None` при ошибках `check_snapshot`, хеш — при ошибках плана (передаётся в `record_rejected_run`).
- `record_rejected_run` получил необязательный `started_at` (по умолчанию — момент записи), чтобы CLI #66 и `PUT /menu` #16 могли записать время начала.
- `source_ref`: для файла — `PureWindowsPath(...).name` (разделители `/` и `\` на любой ОС), затем `safe_text(…, 255)`; пустое → `None`. У коннектора — только `safe_text` (значение вида `yii2/1.0` не режется).
- `counts`: `applied` — `counts_dict()`, `unchanged` — нулевые счётчики, `rejected` — `{}`; при > 100 проблем добавляется `issues_truncated`.

**Build:** ruff check / format OK · pytest 1477 passed, 3 skipped (с db; без Redis) · покрытие service.py, snapshot.py, models/menu_sync.py — 100 % · alembic на тестовой базе: upgrade head → downgrade -1 → upgrade head → check OK; `alembic heads` — 0005

---

## 🔒 Security Review

**Verdict:** PASS (security:passed), 2026-10-15
**Scope:** delta 4a280b5..b5b21c4 — backend/alembic/versions/0005_menu_sync_runs.py, backend/app/models/{__init__,menu_sync}.py, backend/app/menu_sync/{service,snapshot}.py, тесты (test_menu_sync_runs.py, db/test_menu_sync_runs.py, db/test_menu_sync_apply.py, реестры миграций/метаданных)
**Findings:** CRITICAL 0, HIGH 0, MEDIUM 0, LOW 1, INFO 2
**Комментарий:** https://github.com/shakirena/ai-waiter/issues/63#issuecomment-6190296274

- LOW: last_applied_hash упорядочивает журнал по часам приложения (finished_at, UUIDv7). При расхождении часов воркеров в scaled возможен ложный unchanged. Рекомендация (#16/#23): порядок по clock_timestamp() после lock или по identity-колонке. Обход — `--force`.
- INFO: unchanged не видит ручного изменения меню в БД — ожидаемо по ADR-8.5, есть --force.
- INFO: нет NFC-нормализации — только лишнее применение, не коллизия.
- tenant_id во всех запросах журнала; source_ref — только имя файла; issues ≤ 100 и санитизированы; хеш после check_snapshot/resolve_currency; record_rejected_run в отдельной транзакции.
- Исправление LOW #62 (unnest вместо tuple IN, пакеты по 1000 строк) подтверждено: https://github.com/shakirena/ai-waiter/issues/62#issuecomment-6190297637
