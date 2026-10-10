# /analyze — Analysis Phase (G1 + G2)

Запустить `analysis-lead` агент для анализа фичи: декомпозиция на User Stories + архитектурный документ.

## Входные данные

`/analyze #N` — номер GitHub Issue

## Что произойдёт

Запускается агент **analysis-lead**, который:

1. **G1** (backlog → analysis): проверяет business value, AC, тип, приоритет
2. Запускает параллельно:
   - **analyst** → `docs/specs/feature-{N}-{name}.md` + User Stories (child issues)
   - **architect** → `docs/arch/feature-{N}-{name}.md` + code stubs
3. **G2** (analysis → ready-for-dev): проверяет SD-1..SD-5, spec, arch doc
4. Запускает **doc-sync** → обновляет `docs/traceability.md`

## Запуск

Используй Agent tool с агентом `analysis-lead`:

```
Agent({
  subagent_type: "analysis-lead",
  prompt: "Analyze GitHub issue #N for ai-waiter project. Read .claude/AGENTS_FRAMEWORK.md for context. Follow the analysis-lead protocol: G1 → analyst+architect parallel → G2 → doc-sync."
})
```

## Результат

- GitHub Issue переведён в `kanban:ready-for-dev`
- Child story issues созданы с `kanban:backlog`
- `docs/specs/feature-{N}-{name}.md` создан
- `docs/arch/feature-{N}-{name}.md` создан
- Code stubs добавлены в `src/`
- `.claude/memory/stories/story-{N}.md` создан

## Следующий шаг

`/develop #{child-story-N}` для разработки stories.
