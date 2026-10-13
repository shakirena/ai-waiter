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
