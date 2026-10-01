# /board — Kanban-доска

Визуализировать текущее состояние Kanban-доски с метриками.

## Что отобразить

```bash
# Получить все открытые issues с labels
gh issue list --state open --json number,title,labels,assignees --limit 100
```

## Формат вывода

```
╔══════════════════════════════════════════════════════════════╗
║                    KANBAN BOARD — {date}                     ║
╠══════════════════════════════════════════════════════════════╣
║ BACKLOG (N)        ║ ANALYSIS (N)       ║ READY FOR DEV (N) ║
║  #1 Feature X [H] ║  #2 Story A [M]    ║  #4 Story C [H]   ║
║  ...               ║  ...               ║  ...              ║
╠══════════════════════════════════════════════════════════════╣
║ IN DEV (N/5) ⚠WIP ║ TESTING (N/5)      ║ READY TO DEPLOY   ║
║  #5 Story D [H]   ║  #7 Story F [M]    ║  #9 Story H [C]   ║
║  🔒 security:pass  ║  ✅ qa:passed      ║  ✅ qa+sec:passed ║
╠══════════════════════════════════════════════════════════════╣
║ DONE (this week)                                             ║
║  #10 Feature Z — deployed:staging                           ║
╚══════════════════════════════════════════════════════════════╝

BLOCKED ISSUES:
  #6 Story E — Blocked by #5 (not done)
  
METRICS:
  WIP In-Dev: N/5 | WIP Testing: N/5
  security:passed: N issues | security:failed: N issues
  qa:passed: N issues | qa:failed: N issues
```

## Легенда приоритетов

- `[C]` = critical, `[H]` = high, `[M]` = medium, `[L]` = low

## Blocked detection

```bash
# Найти заблокированные issues
gh issue list --state open --json number,body | \
  jq '.[] | select(.body | test("Blocked by:|Depends on:|Requires:")) | {number, blocked_by: (.body | match("(?:Blocked by|Depends on|Requires):\\s*(.+)").captures[0].string)}'
```

## После /board

Рекомендации на основе состояния:
- Если много in-dev → рассмотреть `/test` перед `/develop`
- Если blocked → начать с разблокировки blocker issues
- Если ready-to-deploy → запустить `/deploy staging`
