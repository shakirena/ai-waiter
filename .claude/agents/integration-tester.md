---
name: integration-tester
description: НЕ АКТИВЕН. Зарезервирован для будущего использования. Интеграционные тесты с реальной PostgreSQL.
model: opus
---

# integration-tester

> **СТАТУС: НЕ АКТИВЕН**
> 
> Этот агент зарезервирован для будущего использования.
> Текущий pipeline использует unit tests (tester) и E2E (e2e-tester).
> Интеграционные тесты с реальной БД добавятся при необходимости.

## Планируемый scope

- pytest с реальной PostgreSQL 16 (service container в CI / локальная БД), Alembic upgrade head на чистой базе
- Запросы SQLAlchemy, tenant-изоляция на уровне БД, конкурентная идемпотентность `POST /orders`
- Integration API против эталонного фейкового коннектора; EventBus/TaskScheduler в обоих режимах
- Не заменяет unit tests (tester) — дополняет их
