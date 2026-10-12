# Traceability Matrix

*Last updated: 2026-10-12 (doc-sync после фазы разработки feature #7)*

| Feature | Story | ТЗ | Spec | Arch | Code (router/service) | Tests | TC Doc | Status |
|---------|-------|----|------|------|------------------------|-------|--------|--------|
| #6 Каркас проекта | #37, #38, #39, #40, #41, #42, #43, #44, #45 | раздел 8, 9.1–9.3, NFR-2, NFR-3, NFR-4, NFR-7 | docs/specs/feature-6-project-scaffold.md | docs/arch/feature-6-project-scaffold.md | backend/app/ (api, core, tasks, web), frontend/ | backend/tests/test_*.py, frontend/src/**/*.test.ts* | docs/test-cases/feature-37..45-*.md, docs/test-cases/traceability-tc.md | ✅ ready-to-deploy |
| #7 Модель данных v1 | #48, #49, #50, #51, #52, #53, #54, #56 | раздел 7, 3.1–3.4 (FR-1…FR-21), 4.4–4.6 (INT-1…INT-7), 5 (AI-2), NFR-3, NFR-4, NFR-5, NFR-8, 9.2 | docs/specs/feature-7-data-model.md | docs/arch/feature-7-data-model.md | backend/app/db/, backend/app/models/, backend/app/seed/, backend/app/api/health.py, backend/alembic/ (0001–0004), backend/alembic.ini, .github/workflows/ci.yml | backend/tests/test_db_*.py, test_alembic_setup.py, test_models_metadata.py, test_migrations_offline.py, test_ids.py, test_order_status.py, test_seed.py, test_health.py, test_repo_artifacts.py; backend/tests/db/*.py | — (фаза тестирования) | 🧪 testing (PR #57) |

## Детализация feature #7 по stories

| Story | Содержание | Spec | Arch | Код | Тесты | Статус |
|-------|-----------|------|------|-----|-------|--------|
| #48 | Alembic async, сессия, базовый класс, фикстура `db` | FR-1, FR-2, FR-3, NFR-4, NFR-5, AC-1 | ADR-7.1, 7.8, 7.9, 7.10, 7.11 | backend/app/db/ (base, ids, mixins, session), backend/app/core/config.py, container.py, backend/app/api/deps.py, backend/alembic.ini, backend/alembic/env.py | tests/test_db_base.py, test_db_session.py, test_db_guards.py, test_alembic_setup.py, test_ids.py; tests/db/conftest.py, test_db_fixture.py, test_alembic.py | testing |
| #49 | `tenants`, `halls`, `tables` | FR-4, NFR-1, AC-2 | ADR-7.3, `0001_tenants_tables` | backend/app/models/tenant.py, backend/alembic/versions/0001_tenants_tables.py | tests/db/test_tenants_tables.py, test_tenant_isolation.py, test_migrations.py; tests/test_models_metadata.py | testing |
| #50 | меню, цены, meta, аллергены | FR-5, NFR-1, NFR-2, NFR-7, AC-3 | ADR-7.3, 7.4, `0002_menu` | backend/app/models/menu.py, reference.py, backend/alembic/versions/0002_menu.py | tests/db/test_menu.py, test_tenant_isolation.py, test_migrations.py; tests/test_models_metadata.py | testing |
| #51 | `visits`, `messages`, `cart_items` | FR-6, NFR-2, NFR-8, AC-4 | ADR-7.4, 7.5, `0003_visits` | backend/app/models/visit.py, backend/alembic/versions/0003_visits.py | tests/db/test_visits.py, test_tenant_isolation.py, test_migrations.py; tests/test_models_metadata.py | testing |
| #52 | `orders`, `order_items`, `order_events` | FR-7, NFR-3, AC-5 | ADR-7.2, 7.4, 7.6, 7.7, `0004_orders` | backend/app/models/order.py, enums.py, backend/alembic/versions/0004_orders.py | tests/db/test_orders.py, test_tenant_isolation.py, test_migrations.py; tests/test_order_status.py, test_models_metadata.py, test_migrations_offline.py | testing |
| #53 | сид-данные `python -m app.seed` | FR-8, NFR-6, AC-6 | ADR-7.12 | backend/app/seed/ (`__init__`, `__main__`, data, loader) | tests/test_seed.py, tests/db/test_seed.py | testing |
| #54 | проверка миграций и инвариантов в CI | FR-9, NFR-1, NFR-2, NFR-4, AC-7 | ADR-7.3, 7.4, 7.10, 7.11; DEC-010 | .github/workflows/ci.yml (шаги alembic upgrade/downgrade/upgrade/check до pytest), backend/app/models/menu.py и 0002_menu.py (индексы `ix_menu_item_prices_tenant_id_menu_item_id`, `ix_menu_item_meta_tenant_id_menu_item_id`), README.md | tests/db/test_schema_invariants.py, tests/test_repo_artifacts.py, tests/test_models_metadata.py | testing |
| #56 | проверка БД в `/health/ready` | spec, открытый вопрос 19 | ADR-7.9, API Contracts | backend/app/api/health.py, README.md | tests/test_health.py, tests/db/test_health_db.py | testing |

Все пути тестов — относительно `backend/`. Ревизии Alembic: `0001` (#49) → `0002` (#50) → `0003` (#51) → `0004` (#52). TC-документация по #7 появится в фазе тестирования (G5).
