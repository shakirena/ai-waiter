# Feature #8: Импорт меню из CSV/XLSX (файловый коннектор)

## 📋 Задача (analyst)

**Stories:** #61, #62, #63, #64, #65, #66, #67
**Spec:** docs/specs/feature-8-menu-import.md
**Открытые вопросы:** 12 пунктов в spec, согласованы с arch ADR-8.1…8.8 (главные: 1 — «всё или ничего» и чужая валюта; 2 — хеш в `menu_sync_runs`, без `connectors.last_menu_hash`; 3 — mass_hide ≥ 10 и ≥ 30 %; 4 — нет колонки `is_available`; 5 — смысл `menu.disabled`)
**Arch:** docs/arch/feature-8-menu-import.md
**Вне #8:** HTTP `PUT /menu`, `connectors` (#16), загрузка из админки и FR-20 (#29), стоп-лист отдельно (#16, #28), meta/аллергены (#28, #33)
