# Story #50: Модель данных — меню (categories, menu_items, цены, meta, аллергены)

*Parent: #7. Spec: docs/specs/feature-7-data-model.md (AC-3). Arch: docs/arch/feature-7-data-model.md (ADR-7.3, 7.4; словарь «Меню»).*

---

## 💻 Реализация (developer)

**Branch:** feature/7-data-model
**Новые файлы:**
- backend/alembic/versions/0002_menu.py (rev 0002, down_revision 0001; данные справочника не кладёт)
- backend/tests/db/test_menu.py (AC-3 целиком, CHECK, значения по умолчанию, CASCADE/RESTRICT, COLLATE "C", вставка справочника ЕС для двух заведений)

**Изменённые файлы:**
- backend/app/models/menu.py (Category, MenuItem, MenuItemPrice, MenuItemMeta, Allergen, MenuItemAllergen), backend/app/models/__init__.py (+ menu)
- backend/app/models/reference.py — `EU14_ALLERGENS` (код + названия AZ/RU), `EU14_ALLERGEN_CODES` выводится из него, `default_allergen_rows(tenant_id)` — чистая фабрика строк `allergens` (TypedDict без id; `Allergen(**row)` или `insert(Allergen).values(rows)`), шаг `sort_order` 10
- backend/app/models/checks.py (+ `sql_not_match`)
- backend/tests/test_models_metadata.py, backend/tests/test_migrations_offline.py, backend/tests/db/test_migrations.py, backend/tests/db/test_tenant_isolation.py, backend/tests/db/factories.py — расширены под меню

**Решения:**
- ON DELETE: цены/мета/аллергены позиции → CASCADE на menu_items; menu_items → categories RESTRICT; menu_item_allergens → allergens RESTRICT.
- `menu_item_meta.weight_amount` NUMERIC(8,2) — в явном списке исключений денежного инварианта.
- `photo_path`: CHECK `photo_path !~ '^([/\]|[A-Za-z]:)' AND strpos(photo_path, '..') = 0` (также отвергается UNC-путь и обратный слеш в начале).
- Индекс `ix_menu_items_tenant_id_category_id` (по arch), а не `(tenant_id, category_id, is_hidden)` из текста issue; состав — `ingredients_az/ru` (arch), не `composition_*`.
- Relationships не объявлены (ADR-7.3).

**Build:** ruff OK · ruff format OK · pytest -m "not db and not scaled" 618 passed · pytest -m db 93 passed (ai_waiter_test) · общий прогон 711 passed, 3 skipped (scaled без Redis) · покрытие app/models и app/db 100% (кроме заглушки `can_transition` — #52) · alembic upgrade head / downgrade base / upgrade head / check — код 0
