# Traceability Matrix

*Last updated: 2026-10-13 (doc-sync после фазы тестирования feature #7)*

| Feature | Story | ТЗ | Spec | Arch | Code (router/service) | Tests | TC Doc | Status |
|---------|-------|----|------|------|------------------------|-------|--------|--------|
| #6 Каркас проекта | #37, #38, #39, #40, #41, #42, #43, #44, #45 | раздел 8, 9.1–9.3, NFR-2, NFR-3, NFR-4, NFR-7 | docs/specs/feature-6-project-scaffold.md | docs/arch/feature-6-project-scaffold.md | backend/app/ (api, core, tasks, web), frontend/ | backend/tests/test_*.py, frontend/src/**/*.test.ts* | docs/test-cases/feature-37..45-*.md, docs/test-cases/traceability-tc.md | ✅ ready-to-deploy |
| #7 Модель данных v1 | #48, #49, #50, #51, #52, #53, #54, #56 | раздел 7, 3.1–3.4 (FR-1…FR-21), 4.4–4.6 (INT-1…INT-7), 5 (AI-2), NFR-3, NFR-4, NFR-5, NFR-8, 9.2 | docs/specs/feature-7-data-model.md | docs/arch/feature-7-data-model.md | backend/app/db/, backend/app/models/, backend/app/seed/, backend/app/api/health.py, backend/alembic/ (0001–0004), backend/alembic.ini, .github/workflows/ci.yml | backend/tests/test_db_*.py, test_alembic_setup.py, test_models_metadata.py, test_migrations_offline.py, test_ids.py, test_order_status.py, test_seed.py, test_seed_loader.py, test_health.py, test_repo_artifacts.py, test_config.py, test_qa_coverage_gaps.py; backend/tests/db/*.py | docs/test-cases/feature-48..56-*.md (57 TC), docs/test-cases/traceability-tc.md | stories: ✅ ready-to-deploy (G5 PASS 2026-10-13); feature: 🧪 testing (PR #57); дефект #58 |

## Детализация feature #7 по stories

| Story | Содержание | Spec | Arch | Код | Тесты | TC | Статус |
|-------|-----------|------|------|-----|-------|----|--------|
| #48 | Alembic async, сессия, базовый класс, фикстура `db` | FR-1, FR-2, FR-3, NFR-4, NFR-5, AC-1 | ADR-7.1, 7.8, 7.9, 7.10, 7.11 | backend/app/db/ (base, ids, mixins, session), backend/app/core/config.py, container.py, backend/app/api/deps.py, backend/alembic.ini, backend/alembic/env.py | tests/test_db_base.py, test_db_session.py, test_db_guards.py, test_alembic_setup.py, test_ids.py, test_migrations_offline.py, test_config.py, test_qa_coverage_gaps.py; tests/db/conftest.py, test_db_fixture.py, test_alembic.py | docs/test-cases/feature-48-db-foundation.md: TC-48-001…TC-48-008 | ready-to-deploy (G5 PASS, qa:passed) |
| #49 | `tenants`, `halls`, `tables` | FR-4, NFR-1, AC-2 | ADR-7.3, `0001_tenants_tables` | backend/app/models/tenant.py, backend/alembic/versions/0001_tenants_tables.py | tests/db/test_tenants_tables.py, test_tenant_isolation.py, test_migrations.py; tests/test_models_metadata.py, test_migrations_offline.py | docs/test-cases/feature-49-tenants-tables.md: TC-49-001…TC-49-007 | ready-to-deploy (G5 PASS, qa:passed) |
| #50 | меню, цены, meta, аллергены | FR-5, NFR-1, NFR-2, NFR-7, AC-3 | ADR-7.3, 7.4, `0002_menu` | backend/app/models/menu.py, reference.py, backend/alembic/versions/0002_menu.py | tests/db/test_menu.py, test_tenant_isolation.py, test_migrations.py, test_schema_invariants.py; tests/test_models_metadata.py | docs/test-cases/feature-50-menu.md: TC-50-001…TC-50-008 | ready-to-deploy (G5 PASS, qa:passed) |
| #51 | `visits`, `messages`, `cart_items` | FR-6, NFR-2, NFR-8, AC-4 | ADR-7.4, 7.5, `0003_visits` | backend/app/models/visit.py, backend/alembic/versions/0003_visits.py | tests/db/test_visits.py, test_tenant_isolation.py, test_migrations.py, test_schema_invariants.py; tests/test_models_metadata.py, test_migrations_offline.py | docs/test-cases/feature-51-visits.md: TC-51-001…TC-51-007 | ready-to-deploy (G5 PASS, qa:passed) |
| #52 | `orders`, `order_items`, `order_events` | FR-7, NFR-3, AC-5 | ADR-7.2, 7.4, 7.6, 7.7, `0004_orders` | backend/app/models/order.py, enums.py, backend/alembic/versions/0004_orders.py | tests/db/test_orders.py, test_tenant_isolation.py, test_migrations.py; tests/test_order_status.py, test_models_metadata.py, test_migrations_offline.py | docs/test-cases/feature-52-orders.md: TC-52-001…TC-52-009 | ready-to-deploy (G5 PASS, qa:passed) |
| #53 | сид-данные `python -m app.seed` | FR-8, NFR-6, AC-6 | ADR-7.12 | backend/app/seed/ (`__init__`, `__main__`, data, loader) | tests/test_seed.py, test_seed_loader.py, tests/db/test_seed.py | docs/test-cases/feature-53-seed.md: TC-53-001…TC-53-007 | ready-to-deploy (G5 PASS, qa:passed); TC-53-007 — FAIL, дефект #58 (xfail strict); TC-53-006 — ручной, не выполнен |
| #54 | проверка миграций и инвариантов в CI | FR-9, NFR-1, NFR-2, NFR-4, AC-7 | ADR-7.3, 7.4, 7.10, 7.11; DEC-010 | .github/workflows/ci.yml (шаги alembic upgrade/downgrade/upgrade/check до pytest), backend/app/models/menu.py и 0002_menu.py (индексы `ix_menu_item_prices_tenant_id_menu_item_id`, `ix_menu_item_meta_tenant_id_menu_item_id`), README.md | tests/db/test_schema_invariants.py, test_alembic.py; tests/test_repo_artifacts.py, test_models_metadata.py, test_db_guards.py | docs/test-cases/feature-54-migrations-ci.md: TC-54-001…TC-54-007 | ready-to-deploy (G5 PASS, qa:passed) |
| #56 | проверка БД в `/health/ready` | spec, открытый вопрос 19 | ADR-7.9, API Contracts | backend/app/api/health.py, README.md | tests/test_health.py, test_db_session.py, tests/db/test_health_db.py | docs/test-cases/feature-56-health-db.md: TC-56-001…TC-56-004 | ready-to-deploy (G5 PASS, qa:passed) |

Все пути тестов — относительно `backend/`. Ревизии Alembic: `0001` (#49) → `0002` (#50) → `0003` (#51) → `0004` (#52). Пофайловая привязка каждого TC к тестам и результат прогона — в `docs/test-cases/traceability-tc.md`.

## Требования feature #7 → TC → тесты

| Требование (spec) | Story / AC | TC | Основные автотесты | Результат G5 |
|-------------------|-----------|----|--------------------|--------------|
| FR-1, FR-2, FR-3, NFR-4, NFR-5 — Alembic async, сессия, базовый класс, тестовая БД с guard `*_test` | #48 / AC-1 | TC-48-001…TC-48-008 | db/test_alembic.py, db/test_db_fixture.py, test_db_guards.py, test_db_base.py, test_db_session.py, test_alembic_setup.py, test_ids.py | PASS (TC-48-008 — ручной, PASS) |
| FR-4, NFR-1 — заведения, залы, столы; уникальность `qr_token` | #49 / AC-2 | TC-49-001…TC-49-007 | db/test_tenants_tables.py, db/test_tenant_isolation.py, db/test_migrations.py | PASS |
| FR-5, NFR-1, NFR-2, NFR-7, AI-2 — меню, цены, meta, аллергены, скрытие без удаления | #50 / AC-3 | TC-50-001…TC-50-008 | db/test_menu.py, db/test_tenant_isolation.py, test_models_metadata.py | PASS |
| FR-6, NFR-2, NFR-8 — визиты, сообщения, корзина | #51 / AC-4 | TC-51-001…TC-51-007 | db/test_visits.py, db/test_tenant_isolation.py, db/test_schema_invariants.py | PASS |
| FR-7, NFR-3 — заказы, 8 статусов, `idempotency_key`, `order_events` только дописывается | #52 / AC-5 | TC-52-001…TC-52-009 | db/test_orders.py, test_order_status.py, db/test_migrations.py | PASS |
| FR-8, NFR-6 — идемпотентный сид, запрет в prod, вымышленные данные | #53 / AC-6 | TC-53-001…TC-53-007 | db/test_seed.py, test_seed.py, test_seed_loader.py | PASS, кроме TC-53-007 (дефект #58) и TC-53-006 (ручной, не выполнен) |
| FR-9, NFR-1, NFR-2, NFR-4 — миграции и инварианты схемы в CI | #54 / AC-7 | TC-54-001…TC-54-007 | db/test_schema_invariants.py, db/test_alembic.py, test_repo_artifacts.py | PASS (TC-54-007 — ручной, PASS) |
| Открытый вопрос 19 spec — проверка БД в `/health/ready` | #56 / AC | TC-56-001…TC-56-004 | db/test_health_db.py, test_health.py | PASS |

Финальный прогон G5 2026-10-13: полный `pytest -q` с db — 1053 passed, 3 skipped, 1 xfailed, 70 с, покрытие `app` 100%; без db — 830 passed, 3 skipped, 22 с, покрытие 100%. Итого по #7: 57 TC (PASS 55, FAIL 1, не выполнен 1).

### Известные дефекты

| Issue | TC | Тест | Описание | Статус |
|-------|----|------|----------|--------|
| #58 | TC-53-007 | `tests/db/test_seed.py::test_seed_rerun_when_demo_table_has_another_open_visit` (`xfail(strict=True, raises=IntegrityError)`) | Повторный `python -m app.seed` падает на `uq_visits_open_table`, если демо-визит закрыт, а на демо-столе открыт другой визит | bug в бэклоге; после исправления снять `xfail` (strict-маркер сам сделает прогон красным при XPASS) |
