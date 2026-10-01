# /sweep — Right-to-left автопилот

Безопасная обработка всей Kanban-доски: сначала самые близкие к done, потом дальше.

## Входные данные

`/sweep` — полный sweep  
`/sweep deploy` — только ready-to-deploy → done  
`/sweep test` — только testing → ready-to-deploy  
`/sweep dev` — только ready-for-dev → in-development  
`/sweep analysis` — только backlog → ready-for-dev  
`/sweep dry-run` — показать план без выполнения

## Порядок (right-to-left)

```
1. ops-lead    → ready-to-deploy  → done
2. qa-lead     → testing         → ready-to-deploy
3. dev-lead    → ready-for-dev   → testing
4. analysis-lead → backlog       → ready-for-dev
```

**Каждый шаг ждёт завершения предыдущего** — нет race conditions.

## Алгоритм

### 1. Получить состояние доски

```bash
echo "=== Ready to Deploy ===" && gh issue list --label "kanban:ready-to-deploy" --json number,title
echo "=== Testing ===" && gh issue list --label "kanban:testing" --json number,title
echo "=== Ready for Dev ===" && gh issue list --label "kanban:ready-for-dev" --json number,title
echo "=== Backlog ===" && gh issue list --label "kanban:backlog" --json number,title
```

### 2. Обработать right-to-left (последовательно)

Для каждой колонки — запустить соответствующий Team Lead агент.  
Дождаться завершения → следующая колонка.

### 3. Dependency awareness

Перед каждым Team Lead — dependency check (dependency-resolver.md).  
Заблокированные issues — пропустить с комментарием.

## Когда использовать

- Обычная обработка всей доски
- Есть зависимости между issues
- Важна предсказуемость (в отличие от `/swarm`)

## Типичный утренний workflow

```bash
/board       # проверить состояние
/sweep dry-run  # увидеть план
/sweep       # выполнить
```
