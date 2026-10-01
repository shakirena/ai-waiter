# /kanban — Full Pipeline

Полный pipeline от идеи до staging деплоя одной командой.

## Входные данные

`/kanban <описание фичи>`

## Что произойдёт

Выполняет последовательно все 6 Quality Gates:

```
1. /feature <описание>     → создаёт GitHub Issue
2. /analyze #{N}           → G1 + G2: spec + arch + stories
3. /develop #{stories}     → G3 + G4: реализация + security
4. /test all               → G5: unit tests + TC docs
5. /deploy staging         → G6: build + deploy + health check
```

## Алгоритм

1. Создать Feature Issue (как `/feature`)
2. Дождаться номера issue → запустить analysis-lead (как `/analyze`)
3. Дождаться child stories → запустить dev-lead для каждой (как `/develop`)
4. Дождаться `kanban:testing` → запустить qa-lead (как `/test all`)
5. Дождаться `kanban:ready-to-deploy` → запустить ops-lead (как `/deploy staging`)

## Остановка при BLOCKED

Если любой gate возвращает BLOCKED:
- Вывести причину блокировки
- Остановиться
- Указать что нужно исправить вручную

## Время выполнения

Ожидаемое время для средней фичи (size:m, 2-3 stories):
- Analysis: ~5 мин
- Development: ~10-15 мин (параллельно)
- Testing: ~5 мин
- Deploy: ~5 мин
- **Итого: ~25-30 мин**

## Альтернатива: пошагово

Для контроля над каждым этапом используй отдельные команды:
```
/feature → /analyze → /develop → /test → /deploy
```
