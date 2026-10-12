# Story #53: Сид-данные для разработки — python -m app.seed

*Parent: #7. Spec: docs/specs/feature-7-data-model.md (AC-6). Arch: docs/arch/feature-7-data-model.md (ADR-7.12).*

---

## 🔒 Security

**Verdict:** PASS. Коммит 304fef7. Файлы: backend/app/seed/{__init__,__main__,data,loader}.py, backend/tests/test_seed.py, backend/tests/db/test_seed.py, README.md. Findings: CRITICAL 0, HIGH 0, MEDIUM 0, LOW 2, INFO 3.
- Отказ при `APP_ENV=prod` (код 2) — до остальной конфигурации и подключения, в том числе с `--database-url`; недопустимый `APP_ENV` → код 1. Пароль `DATABASE_URL` не выводится (include_input=False, маскировка в `describe_error`).
- Tenant-изоляция: стол/визит/сообщения — `ON CONFLICT … DO UPDATE … WHERE tenant_id`, чужая строка → SeedError и откат; заказ/строки/`order_events` — только `DO NOTHING`, без UPDATE/DELETE; DELETE только `menu_item_allergens` по tenant + позиции. SQL без f-строк.
- LOW: защита проверяет `APP_ENV` локальной машины, а не целевую базу (по умолчанию `dev`) — сид с `--database-url` на боевую базу создаст демо-заведение с предсказуемыми токенами `demo-table-0N-dev-only` (доступ к ИИ за счёт заведения после #11). Рекомендация: отказ, если в базе есть заведения кроме `DEMO_TENANT_ID`; проверка демо-заведения при старте в prod; `APP_ENV=prod` в чек-листе деплоя.
- LOW: неразбираемый SQLAlchemy URL (нечисловой порт) → `_mask` в `app/db/session.py` бросает внутри обработчика, трассировка вместо текста (пароль не утекает; код до #53).
- INFO: `DEMO_TENANT_ID` перезаписывается без условия (по замыслу); f-строка в `text()` в tests/db/test_seed.py:41 — имена из `pg_tables`; детерминированные токены — решение ADR-7.12, вне `app/seed` не используются.
