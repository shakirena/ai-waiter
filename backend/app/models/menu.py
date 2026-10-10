"""Меню: ``Category``, ``MenuItem``, ``MenuItemPrice``, ``MenuItemMeta``, ``Allergen``,
``MenuItemAllergen``.

Заглушка: колонки — docs/arch/feature-7-data-model.md, «Словарь данных → Меню».
Ревизия Alembic ``0002_menu``.

Разделение владения данными: ``categories``/``menu_items``/``menu_item_prices`` пишет только
синхронизация (коннектор или файловый импорт), ``menu_item_meta``/``menu_item_allergens`` —
только админ (FR-16). Синхронизация никогда не удаляет строки, а ставит ``is_hidden``
(INT-2). ``allergens_verified = false`` означает «неизвестно» даже при пустом списке (AI-2).
"""
