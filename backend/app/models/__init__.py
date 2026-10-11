"""ORM-модели (ТЗ, раздел 7; docs/arch/feature-7-data-model.md).

Модули по доменам (порядок совпадает с ревизиями Alembic 0001–0004):

- ``tenant.py`` — ``Tenant``, ``Hall``, ``Table``;
- ``menu.py`` — ``Category``, ``MenuItem``, ``MenuItemPrice``, ``MenuItemMeta``, ``Allergen``,
  ``MenuItemAllergen``;
- ``visit.py`` — ``Visit``, ``Message``, ``CartItem``;
- ``order.py`` — ``Order``, ``OrderItem``, ``OrderEvent``;
- ``enums.py`` — значения статусов для CHECK (без SQLAlchemy);
- ``reference.py`` — справочные данные по умолчанию (коды 14 аллергенов ЕС).

Пакет импортирует все модули с моделями, чтобы ``Base.metadata`` в ``alembic/env.py``
содержала все таблицы (модули добавляются вместе со своей ревизией Alembic).
"""

from app.models import menu, tenant

__all__ = ["menu", "tenant"]
