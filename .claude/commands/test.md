# /test — Testing Phase (G5)

Запустить `qa-lead` агент для тестирования story.

## Входные данные

`/test #N` — номер issue  
`/test all` — все issues в `kanban:testing`

## Что произойдёт

Запускается **qa-lead**, который:

1. Проверяет `security:passed` label (BLOCKED если отсутствует)
2. Проверяет WIP (< 5 in-testing)
3. Параллельно запускает:
   - **tester** → unit tests (≥ 95% coverage, < 2 мин)
   - **test-case-writer** → TC документация
4. **G5** (testing → ready-to-deploy): coverage OK, TC docs OK, security:passed есть
5. Запускает **doc-sync**

## Запуск

```
Agent({
  subagent_type: "qa-lead",
  prompt: "Test story #N for ai-waiter. Read .claude/agents/qa-lead.md for protocol."
})
```

## Результат

- Issue в `kanban:ready-to-deploy` + `qa:passed`
- `backend/tests/test_*.py`, `frontend/src/**/*.test.tsx` — unit tests
- `docs/test-cases/feature-{N}-{name}.md` — TC документация
- `docs/test-cases/traceability-tc.md` — обновлён

## Следующий шаг

`/deploy staging`
