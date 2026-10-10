# /deploy — Deploy Phase (G6)

Запустить `ops-lead` агент для деплоя на staging или production.

## Входные данные

`/deploy staging` — деплой на staging  
`/deploy production` — деплой на production (требует `APPROVE PRODUCTION DEPLOY`)  
`/deploy all` — все `kanban:ready-to-deploy` issues

## Что произойдёт

Запускается **ops-lead**, который:

1. **G6 Pre-flight**: qa:passed + security:passed + build OK
2. Запускает **devops** → Docker build + deploy + health check + smoke tests
3. **G6 Post-deploy**: health OK, smoke OK, logs clean
4. Если всё OK → `kanban:done` + `deployed:staging` + issue closed

### Production специфика

ops-lead создаёт Production Checklist comment и ждёт `APPROVE PRODUCTION DEPLOY` от человека. **Без одобрения — не деплоит**.

## Запуск

```
Agent({
  subagent_type: "ops-lead",
  prompt: "Deploy to staging for ai-waiter. Read .claude/agents/ops-lead.md for protocol. Target: staging."
})
```

## Rollback

Всегда документируется в comment до деплоя:
```bash
# см. Rollback в DevOps Report: предыдущий тег образа + alembic downgrade {revision} (если обратима)
```

## Следующий шаг

После staging: `/e2e all` для E2E тестирования.  
После production: мониторинг логов 24ч.
