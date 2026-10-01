# /pick — Взять следующую задачу

Выбрать следующую задачу по приоритету из указанной колонки.

## Входные данные

`/pick` — взять задачу из любой колонки (right-to-left)  
`/pick backlog` — следующая задача для анализа  
`/pick ready-for-dev` — следующая задача для разработки  
`/pick testing` — следующая задача для тестирования

## Алгоритм

### 1. Найти следующую задачу

```bash
# По приоритету: critical → high → medium → low
gh issue list \
  --label "kanban:{колонка}" \
  --json number,title,labels \
  --jq 'sort_by(
    if (.labels[].name | test("priority:critical")) then 0
    elif (.labels[].name | test("priority:high")) then 1
    elif (.labels[].name | test("priority:medium")) then 2
    else 3 end
  ) | .[0]'
```

### 2. Проверить зависимости

```bash
gh issue view #{N} --json body -q '.body' | grep -E "Blocked by:|Depends on:"
```

Если есть неразрешённые блокеры — пропустить, взять следующую.

### 3. Запустить соответствующий Team Lead

| Колонка | Агент |
|---------|-------|
| backlog | analysis-lead |
| ready-for-dev | dev-lead |
| testing | qa-lead |
| ready-to-deploy | ops-lead |

### 4. Вывод

```
Picking: #N "{title}" [priority:high] from {колонка}
Launching: {team-lead}...
```

## Стратегия выбора при одинаковом приоритете

При равном приоритете — выбирать по `size`: xs перед s перед m перед l.  
Маленькие задачи проходят pipeline быстрее, освобождая WIP.
