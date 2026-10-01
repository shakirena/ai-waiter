# Project Summary — AI Waiter (ИИ-официант)

*Сжатый контекст для агентов. Читать ПЕРВЫМ. Полные правила — CLAUDE.md, требования — docs/TZ.md.*

---

## Что это

Гость по QR (`/t/{token}`) общается с ботом на AZ/RU, собирает корзину и сам отправляет заказ кнопкой. Официант подтверждает в `/staff`, коннектор кассы забирает подтверждённый заказ через Integration API (`/integration/v1`). Админ заведения — `/admin`. Мультиарендность с первого дня.

## Stack

- Backend: Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, PostgreSQL 16
- Frontend: React + Vite + TypeScript + Tailwind, PWA, mobile-first
- ИИ: Claude API, tool use (`get_menu`, `search_menu`, `get_dish`, `cart_*`, `call_waiter`, `request_review`), SSE. Модель — из конфигурации
- Режимы: `single` (один процесс, in-memory EventBus, APScheduler; Windows Server 2019 без Docker) и `scaled` (Redis, arq, Docker Compose на VPS) — за интерфейсами `EventBus`, `TaskScheduler`, `RateLimiter`

## Роли

Гость (анонимно, по QR-токену стола) · Официант · Администратор заведения · Владелец платформы · Коннектор (по ключу, хранится хешем)

## Ключевые инварианты

- `tenant_id` везде; определяется сервером (QR-токен / ключ коннектора / учётка)
- Деньги: `NUMERIC(10,2)` / `Decimal` / строка "12.50"; время `timestamptz`
- В ядре нет кода под конкретную кассу; поведение — по capabilities коннектора (`menu`, `stoplist`, `tables`, `push_order`, `order_status`)
- У ИИ нет функции отправки заказа; `POST /orders` с `idempotency_key`, цена перепроверяется; заказ сохраняется до вызова ИИ
- Аллергены — только при `allergens_verified = true`
- Заказ: submitted → (edited) → confirmed | rejected | escalated → sent_to_pos → in_pos | pos_failed; всё в `order_events`
- Репозиторий публичный: без IP, ключей, данных заведения

## Build Commands

*Появятся с каркасом (issue #6). Ожидаемо:*

```bash
cd backend && ruff check . && pytest -q
cd frontend && npm run lint && npm run test -- --run && npm run build
```

## Layout (план, issue #6)

```
backend/     FastAPI app, alembic/, tests/
frontend/    React PWA
deploy/      docker-compose.yml (scaled), скрипты службы Windows (single)
e2e-tests/   Playwright (TypeScript)
docs/        TZ.md, specs/, arch/, test-cases/
```

## Current State

Этап проектирования, кода нет. 36 issues в milestones «Этап 0…4». Этап 0 (#2–#5) — задачи в кассе restoran (отдельный репозиторий, не здесь).

## Labels

Компоненты (существующие, без префикса): `backend`, `frontend`, `ai`, `connector`, `infra`, `security`, `content`. Workflow-метки (`kanban:*`, `type:*`, `priority:*`, `size:*`, `qa:*`, `security:*`, `deployed:*`) — созданы `/setup-board` (29 шт.).

## Board IDs

- Project: https://github.com/users/shakirena/projects/7
- PROJECT_ID: PVT_kwHOBagplc4Bk6tq
- STATUS_FIELD_ID: PVTSSF_lAHOBagplc4Bk6tqzhjpfS0
- Options (настроены /setup-board 2026-09-30):
  - Backlog: 11b999a0
  - Analysis: 9a4ff031
  - Ready for Dev: fd594dc5
  - In Development: ab9f2d6e
  - Testing: e348627e
  - Ready to Deploy: 8292685c
  - Done: 52e76674
