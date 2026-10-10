# /setup-board — Инициализация GitHub Labels и Project Board

Создать недостающие GitHub Labels и настроить Status-колонки существующей доски `shakirena/projects/7`. **Выполняется один раз.**

> Метки компонентов в этом репозитории уже есть и используются в issues: `backend`, `frontend`, `ai`, `connector`, `infra`, `security`, `content`. Метки `component:*` не создаются.

## Предусловия

```bash
gh auth status  # убедиться что авторизован
gh auth refresh -s repo,project,read:org  # если нужны доп. scopes
```

## Создание Labels

```bash
# === Kanban колонки ===
gh label create "kanban:backlog"         --color "0E8A16" --description "Backlog"
gh label create "kanban:analysis"        --color "0075CA" --description "In Analysis"
gh label create "kanban:ready-for-dev"   --color "6F42C1" --description "Ready for Development"
gh label create "kanban:in-development"  --color "E4E669" --description "In Development"
gh label create "kanban:testing"         --color "F9D0C4" --description "In Testing"
gh label create "kanban:ready-to-deploy" --color "FFA500" --description "Ready to Deploy"
gh label create "kanban:done"            --color "006B75" --description "Done"

# === Типы ===
gh label create "type:feature"    --color "A2EEEF" --description "Feature Request"
gh label create "type:epic"       --color "3E4B9E" --description "Epic"
gh label create "type:story"      --color "7057FF" --description "User Story"
gh label create "type:bug"        --color "D73A4A" --description "Bug Report"
gh label create "type:tech-debt"  --color "E4E669" --description "Technical Debt"
gh label create "type:hotfix"     --color "B60205" --description "Hotfix (skips G1/G2)"
gh label create "type:spike"      --color "FBCA04" --description "Research/Spike"

# === Приоритеты ===
gh label create "priority:critical" --color "B60205" --description "Critical Priority"
gh label create "priority:high"     --color "D93F0B" --description "High Priority"
gh label create "priority:medium"   --color "FBCA04" --description "Medium Priority"
gh label create "priority:low"      --color "0E8A16" --description "Low Priority"

# === Размеры ===
gh label create "size:xs" --color "C2E0C6" --description "< 2 hours"
gh label create "size:s"  --color "C2E0C6" --description "Half day"
gh label create "size:m"  --color "C2E0C6" --description "1-2 days"
gh label create "size:l"  --color "C2E0C6" --description "3-5 days"

# === QA статусы ===
gh label create "qa:in-progress" --color "FEF2C0" --description "QA In Progress"
gh label create "qa:passed"      --color "0E8A16" --description "QA Passed (≥95% coverage)"
gh label create "qa:failed"      --color "D73A4A" --description "QA Failed"

# === Security статусы ===
gh label create "security:passed" --color "0E8A16" --description "Security Review Passed"
gh label create "security:failed" --color "B60205" --description "Security Review Failed"

# === Deploy статусы ===
gh label create "deployed:staging"    --color "006B75" --description "Deployed to Staging"
gh label create "deployed:production" --color "006B75" --description "Deployed to Production"
```

## Настройка GitHub Project Board

Доска уже есть: https://github.com/users/shakirena/projects/7 (сейчас Status: Todo / In Progress / Done).

1. Заменить опции поля Status на 7 колонок (мутация `updateProjectV2Field` с `singleSelectOptions`):
   Backlog, Analysis, Ready for Dev, In Development, Testing, Ready to Deploy, Done.
   Замена опций сбрасывает Status у карточек — после неё выставить статусы заново (шаг 3).
2. Получить ID опций: `gh project field-list 7 --owner shakirena --format json`.
3. Проставить метку `kanban:*` и Status каждому открытому issue (новые — `kanban:backlog`; issue с активной работой — по факту).
4. Сохранить PROJECT_ID, STATUS_FIELD_ID и ID опций в `.claude/memory/project-summary.md`, секция `## Board IDs`.



```bash
gh label list --limit 200 | grep -cE '^(kanban|type|priority|size|qa|security|deployed):'  # должно быть 29
gh project list --owner @me
```

## После настройки

```
✅ 29 workflow labels created (компоненты — существующие)
✅ Project #7: 7 Status-колонок
✅ Board IDs сохранены в project-summary.md

Next: /feature <описание первой фичи>
```
