"""ORM-модели (ТЗ, раздел 7; docs/arch/feature-7-data-model.md).

Модули по доменам (порядок совпадает с ревизиями Alembic 0001–0005):

- ``tenant.py`` — ``Tenant``, ``Hall``, ``Table``;
- ``menu.py`` — ``Category``, ``MenuItem``, ``MenuItemPrice``, ``MenuItemMeta``, ``Allergen``,
  ``MenuItemAllergen``;
- ``visit.py`` — ``Visit``, ``Message``, ``CartItem``;
- ``order.py`` — ``Order``, ``OrderItem``, ``OrderEvent``;
- ``menu_sync.py`` — ``MenuSyncRun`` (журнал синхронизаций меню, #63);
- ``enums.py`` — значения статусов для CHECK (без SQLAlchemy);
- ``reference.py`` — справочные данные по умолчанию (коды 14 аллергенов ЕС).

Пакет импортирует все модули с моделями, чтобы ``Base.metadata`` в ``alembic/env.py``
содержала все таблицы (модули добавляются вместе со своей ревизией Alembic).
"""

from app.models import menu, menu_sync, order, tenant, visit

__all__ = ["menu", "menu_sync", "order", "tenant", "visit"]
