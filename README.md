# AI Waiter

ИИ-официант для ресторанов: гость сканирует QR-код на столе, общается с ботом на азербайджанском или русском, собирает заказ и отправляет его официанту. Официант подтверждает заказ в своей панели, а коннектор передаёт его в кассовую систему заведения.

Продукт не зависит от кассы: любая касса подключается через коннектор по [Integration API](docs/TZ.md#44-integration-api-v1). Первый коннектор — для Yii2-программы «restoran».

## Статус

Этап проектирования. Техническое задание: [docs/TZ.md](docs/TZ.md). Задачи и этапы — в Issues, Milestones и в GitHub Project «AI Waiter».

## Архитектура

```
Гость (QR, PWA) ─┐
Официант (PWA) ──┼──► AI Waiter: FastAPI + PostgreSQL + Redis + Claude API
Админ ───────────┘            ▲
                              │ Integration API (исходящие запросы коннектора)
                 ┌────────────┼──────────────┐
          Коннектор Yii2   Коннектор r_keeper   Импорт CSV/XLSX
```

## Стек

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic, arq
- БД и очереди: PostgreSQL 16, Redis
- Frontend: React, Vite, TypeScript, Tailwind (PWA)
- LLM: Claude API (tool use, стриминг)
- Инфраструктура: Docker Compose, Caddy

## Структура (планируется)

```
backend/    FastAPI-приложение
frontend/   React-приложение (гость, официант, админ)
deploy/     docker-compose, Caddyfile, инструкции развёртывания
docs/       ТЗ и документация
```
