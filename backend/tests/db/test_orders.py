"""AC-5 (#52): заказы на настоящем PostgreSQL — идемпотентность в границах заведения, статусы,
снимки названия и цены, журнал append-only (триггер). Межарендные ссылки — ``test_tenant_isolation.py``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus
from app.models.menu import MenuItem, MenuItemPrice
from app.models.order import Order, OrderEvent, OrderItem
from app.models.visit import Visit
from tests.db.factories import (
    add,
    build_order,
    build_order_event,
    build_order_item,
    create_menu_item,
    create_order,
    create_tenant,
    create_visit,
    expect_insert_violation,
    expect_violation,
)

pytestmark = pytest.mark.db

RESTRICT_VIOLATION = "23001"


async def _set_status(session: AsyncSession, order_id: uuid.UUID, **values: object) -> None:
    await session.execute(update(Order).where(Order.id == order_id).values(**values))


async def _expect_append_only(session: AsyncSession, statement: object) -> None:
    """UPDATE/DELETE журнала отвергается триггером (SQLSTATE restrict_violation); сессия остаётся рабочей."""
    with pytest.raises(IntegrityError) as info:
        async with session.begin_nested():
            await session.execute(statement)  # type: ignore[call-overload]
    cause = info.value.orig.__cause__ if info.value.orig is not None else None
    assert getattr(cause, "sqlstate", None) == RESTRICT_VIOLATION
    assert "order_events is append-only" in str(info.value)


async def test_ac5_scenario(db_session: AsyncSession) -> None:
    """AC-5 целиком: повтор ключа и неизвестный статус отклоняются, confirmed с confirmed_at
    принимается, снимок позиции не меняется вместе с меню, событие связано с заказом и неизменно."""
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    plov = await create_menu_item(db_session, tenant.id, pos_name="Toyuq plov")
    tea = await create_menu_item(db_session, tenant.id, pos_name="Çay")
    await add(
        db_session,
        MenuItemPrice(tenant_id=tenant.id, menu_item_id=plov.id, price_tier="default", price=Decimal("12.50")),
    )
    key = uuid.uuid4()
    order = await create_order(db_session, tenant.id, visit.id, idempotency_key=key, total=Decimal("15.50"))
    assert order.status == OrderStatus.SUBMITTED
    assert order.id.version == 7
    assert order.created_at.tzinfo is not None
    db_session.add_all(
        [
            build_order_item(
                tenant.id, order.id, plov.id, name_snapshot=plov.pos_name, price_at_order=Decimal("12.50")
            ),
            build_order_item(tenant.id, order.id, tea.id, name_snapshot=tea.pos_name, price_at_order=Decimal("3.00")),
        ]
    )
    await db_session.flush()

    await expect_insert_violation(
        db_session, "uq_orders_tenant_id_idempotency_key", build_order(tenant.id, visit.id, idempotency_key=key)
    )

    async def unknown_status() -> None:
        await _set_status(db_session, order.id, status="unknown_status")

    await expect_violation(db_session, "ck_orders_status", unknown_status)

    confirmed_at = datetime.now(UTC)
    staff_id = uuid.uuid4()
    await _set_status(
        db_session, order.id, status="confirmed", confirmed_at=confirmed_at, confirmed_by_staff_id=staff_id
    )
    event = await add(
        db_session,
        build_order_event(
            tenant.id,
            order.id,
            type="status_changed",
            from_status="submitted",
            to_status="confirmed",
            actor_type="staff",
            actor_id=staff_id,
        ),
    )
    assert event.created_at.tzinfo is not None
    assert event.payload == {}

    # Меню изменилось после заказа: название и цена в строках заказа остаются прежними.
    await db_session.execute(update(MenuItem).where(MenuItem.id == plov.id).values(pos_name="Plov (yeni)"))
    await db_session.execute(
        update(MenuItemPrice).where(MenuItemPrice.menu_item_id == plov.id).values(price=Decimal("14.00"))
    )
    order_id, event_id, plov_id = order.id, event.id, plov.id
    db_session.expire_all()
    [snapshot] = (
        await db_session.execute(
            select(OrderItem.name_snapshot, OrderItem.price_at_order).where(
                OrderItem.order_id == order_id, OrderItem.menu_item_id == plov_id
            )
        )
    ).all()
    assert tuple(snapshot) == ("Toyuq plov", Decimal("12.50"))
    stored = await db_session.get(Order, order_id)
    assert stored is not None
    assert (stored.status, stored.confirmed_by_staff_id) == ("confirmed", staff_id)
    assert stored.confirmed_at == confirmed_at

    await _expect_append_only(
        db_session, update(OrderEvent).where(OrderEvent.id == event_id).values(actor_type="system")
    )
    await _expect_append_only(db_session, delete(OrderEvent).where(OrderEvent.id == event_id))
    db_session.expire_all()
    kept = await db_session.get(OrderEvent, event_id)
    assert kept is not None
    assert (kept.order_id, kept.type, kept.actor_type, kept.actor_id) == (order_id, "status_changed", "staff", staff_id)


@pytest.mark.parametrize("status", list(OrderStatus))
async def test_all_eight_statuses_accepted(db_session: AsyncSession, status: OrderStatus) -> None:
    tenant = await create_tenant(db_session)
    values: dict[str, object] = {"status": status.value}
    if status in {"confirmed", "sent_to_pos", "in_pos", "pos_failed"}:
        values["confirmed_at"] = datetime.now(UTC)
    if status == "rejected":
        values["reject_reason"] = "Нет в наличии"
    order = await create_order(db_session, tenant.id, **values)
    assert order.status == status


@pytest.mark.parametrize("status", ["unknown_status", "SUBMITTED", "cancelled", ""])
async def test_unknown_order_status_rejected(db_session: AsyncSession, status: str) -> None:
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    await expect_insert_violation(db_session, "ck_orders_status", build_order(tenant.id, visit.id, status=status))


async def test_idempotency_key_unique_only_within_tenant(db_session: AsyncSession) -> None:
    """ADR-7.3: тот же ключ в другом заведении принимается (нет межарендного оракула)."""
    tenant = await create_tenant(db_session)
    other = await create_tenant(db_session)
    key = uuid.uuid4()
    first = await create_order(db_session, tenant.id, idempotency_key=key)
    second_visit = await create_visit(db_session, tenant.id)
    await expect_insert_violation(
        db_session,
        "uq_orders_tenant_id_idempotency_key",
        build_order(tenant.id, second_visit.id, idempotency_key=key),
    )
    foreign = await create_order(db_session, other.id, idempotency_key=key)
    assert foreign.idempotency_key == first.idempotency_key
    assert foreign.tenant_id != first.tenant_id


async def test_several_orders_per_visit(db_session: AsyncSession) -> None:
    """Дозаказы (FR-7): у визита может быть несколько заказов с разными ключами."""
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    for _ in range(3):
        await create_order(db_session, tenant.id, visit.id)
    count = await db_session.scalar(select(func.count()).select_from(Order).where(Order.visit_id == visit.id))
    assert count == 3


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"status": "confirmed"}, "ck_orders_confirmed_at"),
        ({"status": "sent_to_pos"}, "ck_orders_confirmed_at"),
        ({"status": "in_pos"}, "ck_orders_confirmed_at"),
        ({"status": "pos_failed"}, "ck_orders_confirmed_at"),
        ({"status": "rejected"}, "ck_orders_reject_reason"),
        ({"status": "rejected", "reject_reason": ""}, "ck_orders_reject_reason_length"),
        ({"reject_reason": "x" * 501}, "ck_orders_reject_reason_length"),
        ({"total": Decimal("-0.01")}, "ck_orders_total"),
        ({"pos_total": Decimal("-0.01")}, "ck_orders_pos_total"),
        ({"currency": "azn"}, "ck_orders_currency"),
        ({"price_tier": "VIP"}, "ck_orders_price_tier"),
        ({"pos_ref": "x" * 65}, "ck_orders_pos_ref"),
        ({"pos_error": "x" * 1001}, "ck_orders_pos_error"),
    ],
)
async def test_order_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    await expect_insert_violation(db_session, constraint, build_order(tenant.id, visit.id, **values))


async def test_confirming_without_confirmed_at_rejected_on_update(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    order = await create_order(db_session, tenant.id)

    async def confirm() -> None:
        await _set_status(db_session, order.id, status="confirmed")

    async def reject() -> None:
        await _set_status(db_session, order.id, status="rejected")

    await expect_violation(db_session, "ck_orders_confirmed_at", confirm)
    await expect_violation(db_session, "ck_orders_reject_reason", reject)


async def test_pos_fields_accepted(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    now = datetime.now(UTC)
    order = await create_order(
        db_session,
        tenant.id,
        status="in_pos",
        confirmed_at=now,
        sent_to_pos_at=now,
        pos_acked_at=now,
        pos_ref="A-1042",
        pos_total=Decimal("15.50"),
    )
    assert (order.pos_ref, order.pos_total) == ("A-1042", Decimal("15.50"))
    assert order.confirmed_by_staff_id is None  # прототип #14 без входа персонала


@pytest.mark.parametrize("qty", [0, -1, 100])
async def test_order_item_qty_out_of_range_rejected(db_session: AsyncSession, qty: int) -> None:
    tenant = await create_tenant(db_session)
    order = await create_order(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    await expect_insert_violation(
        db_session, "ck_order_items_qty", build_order_item(tenant.id, order.id, item.id, qty=qty)
    )


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"price_at_order": Decimal("-0.01")}, "ck_order_items_price_at_order"),
        ({"comment": "x" * 201}, "ck_order_items_comment"),
    ],
)
async def test_order_item_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    order = await create_order(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    await expect_insert_violation(db_session, constraint, build_order_item(tenant.id, order.id, item.id, **values))


async def test_order_item_unique_per_comment_and_soft_removal(db_session: AsyncSession) -> None:
    """Та же позиция с тем же комментарием — одна строка; с другим — отдельная. Удаление
    официантом — флаг ``removed_by_staff``, строка остаётся (FR-13)."""
    tenant = await create_tenant(db_session)
    order = await create_order(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    row = await add(db_session, build_order_item(tenant.id, order.id, item.id, qty=99))
    assert (row.comment, row.removed_by_staff) == ("", False)
    await expect_insert_violation(
        db_session,
        "uq_order_items_tenant_id_order_id_menu_item_id_comment",
        build_order_item(tenant.id, order.id, item.id),
    )
    await add(db_session, build_order_item(tenant.id, order.id, item.id, comment="без лука"))
    await db_session.execute(update(OrderItem).where(OrderItem.id == row.id).values(removed_by_staff=True))
    count = await db_session.scalar(select(func.count()).select_from(OrderItem).where(OrderItem.order_id == order.id))
    assert count == 2


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"type": "deleted"}, "ck_order_events_type"),
        ({"actor_type": "admin"}, "ck_order_events_actor_type"),
        ({"type": "status_changed", "from_status": "submitted"}, "ck_order_events_status_change"),
        ({"type": "status_changed", "to_status": "unknown_status"}, "ck_order_events_to_status"),
        ({"from_status": "unknown_status"}, "ck_order_events_from_status"),
        ({"payload": ["not", "object"]}, "ck_order_events_payload"),
    ],
)
async def test_order_event_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    order = await create_order(db_session, tenant.id)
    await expect_insert_violation(db_session, constraint, build_order_event(tenant.id, order.id, **values))


async def test_all_event_types_including_manual_pos_entry(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    order = await create_order(db_session, tenant.id, status="pos_failed", confirmed_at=datetime.now(UTC))
    db_session.add_all(
        [
            build_order_event(tenant.id, order.id, type="created"),
            build_order_event(
                tenant.id, order.id, type="status_changed", from_status="sent_to_pos", to_status="pos_failed"
            ),
            build_order_event(tenant.id, order.id, type="item_removed", actor_type="staff", payload={"qty_before": 1}),
            build_order_event(
                tenant.id,
                order.id,
                type="item_qty_changed",
                actor_type="staff",
                payload={"qty_before": 2, "qty_after": 1},
            ),
            build_order_event(tenant.id, order.id, type="pos_ack", actor_type="connector"),
            build_order_event(
                tenant.id, order.id, type="pos_error", actor_type="connector", payload={"error": "timeout"}
            ),
            build_order_event(tenant.id, order.id, type="pos_total_mismatch", actor_type="connector"),
            build_order_event(tenant.id, order.id, type="manual_pos_entry", actor_type="staff", actor_id=uuid.uuid4()),
        ]
    )
    await db_session.flush()
    types = (
        await db_session.scalars(select(OrderEvent.type).where(OrderEvent.order_id == order.id).order_by(OrderEvent.id))
    ).all()
    assert len(types) == 8
    assert "manual_pos_entry" in types
    # manual_pos_entry — событие, статус заказа остаётся pos_failed (открытый вопрос 12 arch).
    assert (await db_session.get(Order, order.id)).status == "pos_failed"  # type: ignore[union-attr]


async def test_append_only_blocks_bulk_update_and_delete(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    order = await create_order(db_session, tenant.id)
    await add(db_session, build_order_event(tenant.id, order.id))
    await add(db_session, build_order_event(tenant.id, order.id, type="pos_ack", actor_type="connector"))
    await _expect_append_only(db_session, text("UPDATE order_events SET payload = '{\"x\": 1}'::jsonb"))
    await _expect_append_only(
        db_session, delete(OrderEvent).where(OrderEvent.order_id == order.id, OrderEvent.type == "pos_ack")
    )
    count = await db_session.scalar(select(func.count()).select_from(OrderEvent).where(OrderEvent.order_id == order.id))
    assert count == 2


async def test_rollback_of_inserted_events_works(db_session: AsyncSession) -> None:
    """Откат транзакции не вызывает триггер: вставленные события исчезают (изоляция тестов, ADR-7.6)."""
    tenant = await create_tenant(db_session)
    order = await create_order(db_session, tenant.id)
    nested = await db_session.begin_nested()
    await add(db_session, build_order_event(tenant.id, order.id))
    await nested.rollback()
    count = await db_session.scalar(select(func.count()).select_from(OrderEvent).where(OrderEvent.order_id == order.id))
    assert count == 0


async def test_on_delete_rules(db_session: AsyncSession) -> None:
    """Заказ без событий удаляется вместе со строками (CASCADE); с событиями — нет (RESTRICT);
    визит с заказом и позицию меню в заказе удалить нельзя (RESTRICT)."""
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    draft = await create_order(db_session, tenant.id, visit.id)
    await add(db_session, build_order_item(tenant.id, draft.id, item.id))
    await db_session.execute(delete(Order).where(Order.id == draft.id))
    remaining = await db_session.scalar(
        select(func.count()).select_from(OrderItem).where(OrderItem.order_id == draft.id)
    )
    assert remaining == 0

    order = await create_order(db_session, tenant.id, visit.id)
    await add(db_session, build_order_item(tenant.id, order.id, item.id))
    await add(db_session, build_order_event(tenant.id, order.id))

    async def delete_order() -> None:
        await db_session.execute(delete(Order).where(Order.id == order.id))

    async def delete_visit() -> None:
        await db_session.execute(delete(Visit).where(Visit.id == visit.id))

    async def delete_menu_item() -> None:
        await db_session.execute(delete(MenuItem).where(MenuItem.id == item.id))

    await expect_violation(db_session, "fk_order_events_tenant_id_order_id_orders", delete_order)
    await expect_violation(db_session, "fk_orders_tenant_id_visit_id_visits", delete_visit)
    await expect_violation(db_session, "fk_order_items_tenant_id_menu_item_id_menu_items", delete_menu_item)


async def test_pending_and_pos_queue_partial_indexes(db_session: AsyncSession) -> None:
    rows = dict(
        (await db_session.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'orders'"))).all()
    )
    assert (
        "(created_at) WHERE (status = ANY (ARRAY['submitted'::text, 'edited'::text]))"
        in rows["ix_orders_pending_confirm"]
    )
    assert (
        "(tenant_id, confirmed_at, id) WHERE (status = ANY (ARRAY['confirmed'::text, 'sent_to_pos'::text]))"
        in rows["ix_orders_pos_queue"]
    )
