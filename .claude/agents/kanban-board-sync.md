# Kanban Board Sync — Shared Protocol

Этот файл читается Team Leads напрямую. Не является агентом.

---

## Правило: Status-First

**СНАЧАЛА обновить статус → ПОТОМ начинать работу.**

При каждой смене колонки агент обязан обновить ОБА механизма:
1. **GitHub Label** — убрать старый `kanban:*`, добавить новый
2. **GitHub Project Board Status** — через `gh project item-edit`

---

## Обновление Label (через gh CLI)

```bash
# Убрать старый kanban-label и добавить новый
gh issue edit #{N} --remove-label "kanban:backlog" --add-label "kanban:analysis"
```

Маппинг меток:
- `kanban:backlog` → Backlog
- `kanban:analysis` → Analysis
- `kanban:ready-for-dev` → Ready for Dev
- `kanban:in-development` → In Development
- `kanban:testing` → Testing
- `kanban:ready-to-deploy` → Ready to Deploy
- `kanban:done` → Done

---

## Обновление Project Board

### Шаг 1: Получить PROJECT_ID

```bash
gh project list --owner @me
# или
gh api graphql -f query='{ viewer { projectsV2(first: 10) { nodes { id title } } } }'
```

### Шаг 2: Получить ITEM_ID для issue

```bash
gh api graphql -f query='
{
  repository(owner: "OWNER", name: "REPO") {
    issue(number: N) {
      projectItems(first: 5) {
        nodes { id }
      }
    }
  }
}'
```

### Шаг 3: Получить FIELD_ID (Status поле)

```bash
gh api graphql -f query='
{
  node(id: "PROJECT_ID") {
    ... on ProjectV2 {
      fields(first: 20) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
        }
      }
    }
  }
}'
```

### Шаг 4: Обновить статус

```bash
gh api graphql -f query='
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "PROJECT_ID"
    itemId: "ITEM_ID"
    fieldId: "FIELD_ID"
    value: { singleSelectOptionId: "OPTION_ID" }
  }) {
    projectV2Item { id }
  }
}'
```

---

## Кэширование IDs

При первом использовании сохраняй IDs в `.claude/memory/project-summary.md` в секции `## Board IDs`:

```markdown
## Board IDs
- PROJECT_ID: PVT_xxx
- STATUS_FIELD_ID: PVTSSF_xxx
- Options:
  - Backlog: OPTION_ID_1
  - Analysis: OPTION_ID_2
  - Ready for Dev: OPTION_ID_3
  - In Development: OPTION_ID_4
  - Testing: OPTION_ID_5
  - Ready to Deploy: OPTION_ID_6
  - Done: OPTION_ID_7
```

Следующие Team Leads читают из памяти вместо повторных API-вызовов.

---

## Быстрый путь через gh project item-edit

```bash
# Если известен номер issue и status option name
PROJ=$(gh project list --owner @me --format json | jq -r '.projects[0].number')
gh project item-edit --project-id $PROJ --id ITEM_ID --field-id FIELD_ID --single-select-option-id OPTION_ID
```

---

## При ошибке синхронизации

Если GraphQL API недоступен или Project Board не настроен:
1. Обновить только Label (обязательно)
2. Написать в comment: "⚠️ Board sync failed — label updated, board requires manual update"
3. Продолжить работу (label — основной источник истины)
