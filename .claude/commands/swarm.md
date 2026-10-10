# /swarm — Все Team Leads параллельно

Запустить все 4 Team Leads одновременно по всей Kanban-доске.

## Входные данные

`/swarm` — запустить по всей доске  
`/swarm develop` — только dev-lead  
`/swarm test` — только qa-lead  
`/swarm analyze` — только analysis-lead  
`/swarm dry-run` — показать что будет обработано, не запускать

## Алгоритм

### 1. Получить состояние доски

```bash
gh issue list --label "kanban:ready-for-dev" --json number,title,labels
gh issue list --label "kanban:testing" --json number,title,labels
gh issue list --label "kanban:ready-to-deploy" --json number,title,labels
gh issue list --label "kanban:backlog" --json number,title,labels
```

### 2. dry-run

Показать что будет обработано:
```
📋 Would process:
  analysis-lead: #1 (backlog → ready-for-dev)
  dev-lead: #3, #4 (ready-for-dev → testing)
  qa-lead: #6 (testing → ready-to-deploy)
  ops-lead: #8 (ready-to-deploy → done)
```

### 3. Запустить параллельно

Запустить все Team Leads одновременно через Agent tool:
- analysis-lead для всех `kanban:backlog` issues
- dev-lead для всех `kanban:ready-for-dev` issues (WIP check!)
- qa-lead для всех `kanban:testing` issues
- ops-lead для всех `kanban:ready-to-deploy` issues

### Предупреждение о race conditions

Если несколько Team Leads работают с пересекающимися issues — возможны конфликты labels. Используй `/sweep` для безопасной обработки right-to-left.

## Когда использовать

- Нужна максимальная скорость
- Доска чистая (мало issues, нет зависимостей)
- Готов принять риск minor race conditions на labels
