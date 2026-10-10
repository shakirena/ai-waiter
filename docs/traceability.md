# Traceability Matrix

*Last updated: 2026-10-10 (фаза анализа feature #7)*

| Feature | Story | ТЗ | Spec | Arch | Code (router/service) | Tests | TC Doc | Status |
|---------|-------|----|------|------|------------------------|-------|--------|--------|
| #6 Каркас проекта | #37, #38, #39, #40, #41, #42, #43, #44, #45 | раздел 8, 9.1–9.3, NFR-2, NFR-3, NFR-4, NFR-7 | docs/specs/feature-6-project-scaffold.md | docs/arch/feature-6-project-scaffold.md | backend/app/ (api, core, tasks, web), frontend/ | backend/tests/test_*.py, frontend/src/**/*.test.ts* | docs/test-cases/feature-37..45-*.md, docs/test-cases/traceability-tc.md | ✅ ready-to-deploy |
| #7 Модель данных v1 | #48, #49, #50, #51, #52, #53, #54 | раздел 7, 3.1–3.4 (FR-1…FR-21), 4.4–4.6 (INT-1…INT-7), 5 (AI-2), NFR-3, NFR-4, NFR-5, NFR-8, 9.2 | docs/specs/feature-7-data-model.md | docs/arch/feature-7-data-model.md | backend/app/db/, backend/app/models/, backend/app/seed/ (заглушки), backend/alembic/ (ещё нет) | — (ещё нет) | — (ещё нет) | 📝 ready-for-dev |

## Детализация feature #7 по stories

| Story | Содержание | Spec | Arch (ревизия Alembic) | Код | Статус |
|-------|-----------|------|------------------------|-----|--------|
| #48 | Alembic async, сессия, базовый класс, фикстура `db` | FR-1, FR-2, FR-3, AC-1 | ADR сессии/Alembic | backend/app/db/ (base, ids, mixins, session) | заглушка |
| #49 | `tenants`, `halls`, `tables` | FR-4, AC-2 | `0001_tenants_tables` | backend/app/models/tenant.py | заглушка |
| #50 | меню, цены, meta, аллергены | FR-5, AC-3 | `0002_menu` | backend/app/models/menu.py, reference.py | заглушка |
| #51 | `visits`, `messages`, `cart_items` | FR-6, AC-4 | `0003_visits` | backend/app/models/visit.py | заглушка |
| #52 | `orders`, `order_items`, `order_events` | FR-7, AC-5 | `0004_orders` | backend/app/models/order.py, enums.py | заглушка |
| #53 | сид-данные `python -m app.seed` | FR-8, AC-6 | — | backend/app/seed/ | заглушка |
| #54 | проверка миграций и инвариантов в CI | FR-9, AC-7 | — | .github/workflows/ (изменений ещё нет) | не начато |

Порядок: #48 → #49 → #50 → #51 → #52 (одна цепочка Alembic), затем #53 и #54 параллельно.
