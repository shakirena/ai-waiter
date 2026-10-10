# /develop — Development Phase (G3 + G4 + Security)

Запустить `dev-lead` агент для разработки story/фичи.

## Входные данные

`/develop #N [#M ...]` — один или несколько номеров issues

## Что произойдёт

Запускается **dev-lead**, который:

1. Проверяет зависимости (dependency-resolver)
2. Проверяет WIP (< 5 in-development)
3. **G3** (ready-for-dev → in-development): build OK, AC testable
4. Запускает **developer** (isolation: worktree) — реализация в `feature/{N}-{name}` branch
5. **G4**: build + lint + unit tests + нет TODO/FIXME
6. Запускает **security-reviewer** — OWASP, tenant-изоляция, роли, prompt injection, IDOR, XSS
7. Если security PASS → **G4 финал** (in-development → testing)

## Запуск

```
Agent({
  subagent_type: "dev-lead",
  prompt: "Develop story #N for ai-waiter. Read .claude/agents/dev-lead.md for protocol. Issues to process: #N."
})
```

## Несколько issues параллельно

`/develop #3 #4 #5` — dev-lead запускает developer агентов параллельно в отдельных worktrees.

## Результат

- Issue переведён в `kanban:testing`
- `security:passed` label выставлен
- Branch `feature/{N}-{name}` с реализацией
- `.claude/memory/stories/story-{N}.md` обновлён (💻 + 🔒 разделы)

## Следующий шаг

`/test #N` для QA фазы.
