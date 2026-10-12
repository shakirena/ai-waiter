"""Загрузка демо-данных в БД (ADR-7.12): ``apply_seed(session)``.

Функция не управляет транзакцией: ``python -m app.seed`` оборачивает её в одну транзакцию,
db-тесты — в откатываемую. Все запросы — ``INSERT … ON CONFLICT`` по естественным ключам:

- заведение — по ``id`` (фиксированный ``DEMO_TENANT_ID``), DO UPDATE;
- аллергены — ``(tenant_id, code)``, залы — ``(tenant_id, name)``, столы — ``qr_token``,
  категории и позиции — ``(tenant_id, external_id)``, цены — ``(menu_item_id, price_tier)``,
  мета — ``menu_item_id``, строки корзины — ``(tenant_id, visit_id, menu_item_id, comment)``,
  визит и сообщения — фиксированный ``id``; всё это DO UPDATE: повторный запуск возвращает
  эталонные значения;
- аллергены позиций — DO NOTHING, лишние связи демо-позиций удаляются (список эталонный);
- заказ, его строки и событие ``created`` — DO NOTHING по фиксированному ``id``: это история
  (журнал ``order_events`` append-only, ADR-7.6), повторный запуск её не меняет и не дублирует.

``RETURNING id`` берёт ключ существующей строки, поэтому дочерние строки ссылаются на неё, даже
если строку создал не сид. Стол с тем же токеном у другого заведения сид не трогает и падает.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.models.enums import ActorType, OrderEventType, OrderStatus, VisitStatus
from app.models.menu import Allergen, Category, MenuItem, MenuItemAllergen, MenuItemMeta, MenuItemPrice
from app.models.order import Order, OrderEvent, OrderItem
from app.models.reference import default_allergen_rows
from app.models.tenant import Hall, Table, Tenant
from app.models.visit import CartItem, Message, Visit
from app.seed import data


class SeedError(RuntimeError):
    """Демо-данные нельзя загрузить без порчи чужих данных (текст — для разработчика)."""


@dataclass(frozen=True, slots=True)
class SeededTable:
    name: str
    qr_token: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class SeedSummary:
    tenant_id: uuid.UUID
    tables: tuple[SeededTable, ...]


async def _upsert(
    session: AsyncSession,
    model: type[Base],
    values: Mapping[str, Any],
    conflict: Iterable[str],
    update: Iterable[str],
    *,
    where: Any = None,
) -> uuid.UUID | None:
    """``INSERT … ON CONFLICT (conflict) DO UPDATE SET update [WHERE where] RETURNING id``.

    ``updated_at`` обновляется явно: ``onupdate`` ORM на Core-UPSERT не срабатывает.
    ``None`` — строка есть, но условие ``where`` запретило её менять.
    """
    table = model.__table__
    stmt = pg_insert(table).values(**values)
    set_: dict[str, Any] = {column: stmt.excluded[column] for column in update}
    if "updated_at" in table.c:
        set_["updated_at"] = func.now()
    stmt = stmt.on_conflict_do_update(index_elements=list(conflict), set_=set_, where=where)
    if "id" not in table.c:
        await session.execute(stmt)
        return None
    return (await session.execute(stmt.returning(table.c.id))).scalar_one_or_none()


async def _upsert_id(
    session: AsyncSession,
    model: type[Base],
    values: Mapping[str, Any],
    conflict: Iterable[str],
    update: Iterable[str],
    *,
    where: Any = None,
) -> uuid.UUID:
    row_id = await _upsert(session, model, values, conflict, update, where=where)
    if row_id is None:
        raise SeedError(f"{model.__tablename__}: строка с ключом сида принадлежит другому заведению")
    return row_id


async def _insert_if_absent(session: AsyncSession, model: type[Base], values: Mapping[str, Any]) -> None:
    """``INSERT … ON CONFLICT DO NOTHING`` — для истории (заказ, строки, события)."""
    await session.execute(pg_insert(model.__table__).values(**values).on_conflict_do_nothing())


async def _seed_tenant(session: AsyncSession) -> uuid.UUID:
    tenant = data.TENANT
    return await _upsert_id(
        session,
        Tenant,
        {
            "id": tenant.id,
            "name": tenant.name,
            "currency": tenant.currency,
            "timezone": tenant.timezone,
            "languages": list(tenant.languages),
            "settings": {},
        },
        ["id"],
        ["name", "currency", "timezone", "languages", "settings"],
    )


async def _seed_allergens(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for row in default_allergen_rows(tenant_id):
        ids[row["code"]] = await _upsert_id(
            session, Allergen, row, ["tenant_id", "code"], ["name_az", "name_ru", "sort_order"]
        )
    return ids


async def _seed_halls(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for hall in data.HALLS:
        ids[hall.key] = await _upsert_id(
            session,
            Hall,
            {"tenant_id": tenant_id, "name": hall.name, "sort_key": hall.sort_key},
            ["tenant_id", "name"],
            ["sort_key"],
        )
    return ids


async def _seed_tables(
    session: AsyncSession, tenant_id: uuid.UUID, hall_ids: Mapping[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for table in data.TABLES:
        ids[table.qr_token] = await _upsert_id(
            session,
            Table,
            {
                "tenant_id": tenant_id,
                "hall_id": hall_ids[table.hall],
                "name": table.name,
                "type": table.type.value,
                "price_tier": table.price_tier,
                "qr_token": table.qr_token,
                "is_active": table.is_active,
            },
            ["qr_token"],
            ["hall_id", "name", "type", "price_tier", "is_active"],
            # Токен глобально уникален: стол другого заведения не перезаписывается.
            where=Table.__table__.c.tenant_id == tenant_id,
        )
    return ids


async def _seed_categories(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for category in data.CATEGORIES:
        ids[category.external_id] = await _upsert_id(
            session,
            Category,
            {
                "tenant_id": tenant_id,
                "external_id": category.external_id,
                "pos_name": category.pos_name,
                "name_az": category.name_az,
                "name_ru": category.name_ru,
                "sort_key": category.sort_key,
                "is_hidden": False,
                "synced_at": func.now(),
            },
            ["tenant_id", "external_id"],
            ["pos_name", "name_az", "name_ru", "sort_key", "is_hidden", "synced_at"],
        )
    return ids


async def _seed_dish(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    dish: data.DishSeed,
    category_ids: Mapping[str, uuid.UUID],
    allergen_ids: Mapping[str, uuid.UUID],
) -> uuid.UUID:
    item_id = await _upsert_id(
        session,
        MenuItem,
        {
            "tenant_id": tenant_id,
            "category_id": category_ids[dish.category],
            "external_id": dish.external_id,
            "pos_name": dish.pos_name,
            "currency": data.TENANT.currency,
            "station": dish.station,
            "sort_key": dish.sort_key,
            "is_available": dish.is_available,
            "is_hidden": dish.is_hidden,
            "synced_at": func.now(),
        },
        ["tenant_id", "external_id"],
        ["category_id", "pos_name", "currency", "station", "sort_key", "is_available", "is_hidden", "synced_at"],
    )
    for price_tier, price in dish.prices.items():
        await _upsert(
            session,
            MenuItemPrice,
            {"tenant_id": tenant_id, "menu_item_id": item_id, "price_tier": price_tier, "price": price},
            ["menu_item_id", "price_tier"],
            ["price"],
        )
    meta = {
        "name_az": dish.name_az,
        "name_ru": dish.name_ru,
        "description_az": dish.description_az,
        "description_ru": dish.description_ru,
        "ingredients_az": None,
        "ingredients_ru": None,
        "allergens_verified": dish.allergens_verified,
        "spice_level": dish.spice_level,
        "prep_minutes": dish.prep_minutes,
        "weight_amount": dish.weight_amount,
        "weight_unit": dish.weight_unit.value if dish.weight_unit is not None else None,
        "photo_path": None,
        "tags": list(dish.tags),
        "visible_to_ai": True,
    }
    await _upsert(
        session,
        MenuItemMeta,
        {"tenant_id": tenant_id, "menu_item_id": item_id, **meta},
        ["menu_item_id"],
        list(meta),
    )
    wanted = [allergen_ids[code] for code in dish.allergens]
    links = MenuItemAllergen.__table__
    await session.execute(
        delete(links).where(
            links.c.tenant_id == tenant_id,
            links.c.menu_item_id == item_id,
            links.c.allergen_id.not_in(wanted),
        )
    )
    for allergen_id in wanted:
        await _insert_if_absent(
            session, MenuItemAllergen, {"tenant_id": tenant_id, "menu_item_id": item_id, "allergen_id": allergen_id}
        )
    return item_id


async def _seed_visit(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    table_ids: Mapping[str, uuid.UUID],
    item_ids: Mapping[str, uuid.UUID],
) -> uuid.UUID:
    visit = data.VISIT
    table = data.table_by_token(visit.table_token)
    visit_id = await _upsert_id(
        session,
        Visit,
        {
            "id": visit.id,
            "tenant_id": tenant_id,
            "table_id": table_ids[visit.table_token],
            "status": VisitStatus.OPEN.value,
            "lang": visit.lang.value,
            "last_activity_at": func.now(),
            "closed_at": None,
            "closed_by": None,
            "closed_by_staff_id": None,
        },
        ["id"],
        ["table_id", "status", "lang", "last_activity_at", "closed_at", "closed_by", "closed_by_staff_id"],
        where=Visit.__table__.c.tenant_id == tenant_id,
    )
    for message in visit.messages:
        await _upsert_id(
            session,
            Message,
            {
                "id": message.id,
                "tenant_id": tenant_id,
                "visit_id": visit_id,
                "role": message.role.value,
                "text": message.text,
                "content": [{"type": "text", "text": message.text}],
                "redacted_at": None,
            },
            ["id"],
            ["visit_id", "role", "text", "content", "redacted_at"],
            where=Message.__table__.c.tenant_id == tenant_id,
        )
    for line in visit.cart:
        dish = data.dish_by_external_id(line.dish)
        await _upsert_id(
            session,
            CartItem,
            {
                "tenant_id": tenant_id,
                "visit_id": visit_id,
                "menu_item_id": item_ids[line.dish],
                "qty": line.qty,
                "comment": line.comment,
                "price_tier": table.price_tier,
                "price_at_add": data.price_for(dish, table.price_tier),
            },
            ["tenant_id", "visit_id", "menu_item_id", "comment"],
            ["qty", "price_tier", "price_at_add"],
        )
    return visit_id


async def _seed_order(
    session: AsyncSession, tenant_id: uuid.UUID, visit_id: uuid.UUID, item_ids: Mapping[str, uuid.UUID]
) -> None:
    order = data.ORDER
    price_tier = data.table_by_token(data.VISIT.table_token).price_tier
    await _insert_if_absent(
        session,
        Order,
        {
            "id": order.id,
            "tenant_id": tenant_id,
            "visit_id": visit_id,
            "idempotency_key": order.idempotency_key,
            "status": OrderStatus.SUBMITTED.value,
            "price_tier": price_tier,
            "total": data.order_total(order, price_tier),
            "currency": data.TENANT.currency,
        },
    )
    # Заказ мог быть создан раньше (в том числе с другим id по тому же ключу идемпотентности).
    order_id = (
        await session.execute(
            select(Order.id).where(Order.tenant_id == tenant_id, Order.idempotency_key == order.idempotency_key)
        )
    ).scalar_one()
    for line in order.lines:
        dish = data.dish_by_external_id(line.dish)
        await _insert_if_absent(
            session,
            OrderItem,
            {
                "id": line.id,
                "tenant_id": tenant_id,
                "order_id": order_id,
                "menu_item_id": item_ids[line.dish],
                "name_snapshot": dish.pos_name,
                "qty": line.qty,
                "price_at_order": data.price_for(dish, price_tier),
                "comment": line.comment,
            },
        )
    await _insert_if_absent(
        session,
        OrderEvent,
        {
            "id": order.created_event_id,
            "tenant_id": tenant_id,
            "order_id": order_id,
            "type": OrderEventType.CREATED.value,
            "to_status": OrderStatus.SUBMITTED.value,
            "actor_type": ActorType.GUEST.value,
            "payload": {"source": "seed"},
        },
    )


async def apply_seed(session: AsyncSession) -> SeedSummary:
    """Загрузить или обновить демо-данные в текущей транзакции сессии (без commit)."""
    tenant_id = await _seed_tenant(session)
    allergen_ids = await _seed_allergens(session, tenant_id)
    hall_ids = await _seed_halls(session, tenant_id)
    table_ids = await _seed_tables(session, tenant_id, hall_ids)
    category_ids = await _seed_categories(session, tenant_id)
    item_ids = {
        dish.external_id: await _seed_dish(session, tenant_id, dish, category_ids, allergen_ids) for dish in data.DISHES
    }
    visit_id = await _seed_visit(session, tenant_id, table_ids, item_ids)
    await _seed_order(session, tenant_id, visit_id, item_ids)
    return SeedSummary(
        tenant_id=tenant_id,
        tables=tuple(SeededTable(t.name, t.qr_token, t.is_active) for t in data.TABLES),
    )
