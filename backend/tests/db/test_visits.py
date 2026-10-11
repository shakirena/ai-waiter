"""AC-4 (#51): визиты, диалог и корзина на настоящем PostgreSQL — один открытый визит на стол,
уникальность строки корзины, CHECK, обезличивание сообщений, ON DELETE. Межарендные ссылки —
``test_tenant_isolation.py``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import MenuItem, MenuItemPrice
from app.models.tenant import Table
from app.models.visit import CartItem, Message, Visit
from tests.db.factories import (
    add,
    build_cart_item,
    build_message,
    build_visit,
    create_menu_item,
    create_table,
    create_tenant,
    create_visit,
    expect_insert_violation,
    expect_violation,
)

pytestmark = pytest.mark.db


async def _close(session: AsyncSession, visit_id: uuid.UUID, closed_by: str = "staff") -> None:
    await session.execute(
        update(Visit)
        .where(Visit.id == visit_id)
        .values(status="closed", closed_at=datetime.now(UTC), closed_by=closed_by)
    )


async def _count(session: AsyncSession, model: type, visit_id: uuid.UUID) -> int:
    column = model.visit_id  # type: ignore[attr-defined]
    return int(await session.scalar(select(func.count()).select_from(model).where(column == visit_id)) or 0)


async def test_ac4_scenario(db_session: AsyncSession) -> None:
    """AC-4 целиком: второй открытый визит и дубль строки корзины отклоняются, другой комментарий
    принимается, цена на момент добавления хранится, после закрытия визита открывается новый."""
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    await add(
        db_session,
        MenuItemPrice(tenant_id=tenant.id, menu_item_id=item.id, price_tier="default", price=Decimal("12.50")),
    )

    visit = await create_visit(db_session, tenant.id, table.id)
    assert visit.status == "open"
    assert visit.id.version == 7
    assert visit.opened_at.tzinfo is not None
    assert visit.last_activity_at.tzinfo is not None
    assert (visit.closed_at, visit.closed_by, visit.closed_by_staff_id) == (None, None, None)

    await expect_insert_violation(db_session, "uq_visits_open_table", build_visit(tenant.id, table.id, lang="az"))

    plain = await add(db_session, build_cart_item(tenant.id, visit.id, item.id, price_at_add=Decimal("12.50")))
    assert plain.comment == ""
    await expect_insert_violation(
        db_session,
        "uq_cart_items_tenant_id_visit_id_menu_item_id_comment",
        build_cart_item(tenant.id, visit.id, item.id, qty=2),
    )
    no_onion = await add(db_session, build_cart_item(tenant.id, visit.id, item.id, comment="без лука"))
    assert no_onion.comment == "без лука"

    tenant_id, table_id, visit_id = tenant.id, table.id, visit.id
    db_session.expire_all()
    prices = (await db_session.scalars(select(CartItem.price_at_add).where(CartItem.visit_id == visit_id))).all()
    assert prices == [Decimal("12.50"), Decimal("12.50")]
    assert all(isinstance(price, Decimal) for price in prices)

    await _close(db_session, visit_id)
    second = await create_visit(db_session, tenant_id, table_id, lang="az")
    assert second.status == "open"
    assert second.id != visit_id


async def test_only_open_visits_are_unique_per_table(db_session: AsyncSession) -> None:
    """Закрытых визитов у стола сколько угодно; открытые визиты разных столов не мешают друг другу."""
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    for closed_by in ("staff", "pos", "timeout"):
        visit = await create_visit(db_session, tenant.id, table.id)
        await _close(db_session, visit.id, closed_by)
    await create_visit(db_session, tenant.id, table.id)
    other_table = await create_table(db_session, tenant.id, name="Стол 2")
    await create_visit(db_session, tenant.id, other_table.id)
    total = await db_session.scalar(select(func.count()).select_from(Visit).where(Visit.table_id == table.id))
    assert total == 4


async def test_reopening_closed_visit_while_another_is_open_rejected(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    old = await create_visit(db_session, tenant.id, table.id)
    await _close(db_session, old.id)
    await create_visit(db_session, tenant.id, table.id)

    async def reopen() -> None:
        await db_session.execute(
            update(Visit).where(Visit.id == old.id).values(status="open", closed_at=None, closed_by=None)
        )

    await expect_violation(db_session, "uq_visits_open_table", reopen)


async def test_partial_unique_index_in_database(db_session: AsyncSession) -> None:
    rows = dict(
        (
            await db_session.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN ('visits', 'messages')")
            )
        ).all()
    )
    assert rows["uq_visits_open_table"].startswith("CREATE UNIQUE INDEX uq_visits_open_table")
    assert "(table_id) WHERE (status = 'open'::text)" in rows["uq_visits_open_table"]
    assert "(last_activity_at) WHERE (status = 'open'::text)" in rows["ix_visits_open_last_activity"]
    assert "(created_at) WHERE (redacted_at IS NULL)" in rows["ix_messages_retention"]
    assert "(tenant_id, created_at)" in rows["ix_messages_tenant_id_created_at"]


@pytest.mark.parametrize("qty", [0, -1, 100])
async def test_cart_qty_out_of_range_rejected(db_session: AsyncSession, qty: int) -> None:
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    await expect_insert_violation(
        db_session, "ck_cart_items_qty", build_cart_item(tenant.id, visit.id, item.id, qty=qty)
    )


@pytest.mark.parametrize("qty", [1, 99])
async def test_cart_qty_bounds_accepted(db_session: AsyncSession, qty: int) -> None:
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    row = await add(db_session, build_cart_item(tenant.id, visit.id, item.id, qty=qty))
    assert row.qty == qty


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"comment": "x" * 201}, "ck_cart_items_comment"),
        ({"price_tier": "VIP"}, "ck_cart_items_price_tier"),
        ({"price_at_add": Decimal("-0.01")}, "ck_cart_items_price_at_add"),
    ],
)
async def test_cart_item_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    await expect_insert_violation(db_session, constraint, build_cart_item(tenant.id, visit.id, item.id, **values))


async def test_cart_item_vip_tier_snapshot(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id, price_tier="vip")
    visit = await create_visit(db_session, tenant.id, table.id)
    item = await create_menu_item(db_session, tenant.id)
    row = await add(
        db_session,
        build_cart_item(tenant.id, visit.id, item.id, price_tier=table.price_tier, price_at_add=Decimal("15.00")),
    )
    assert (row.price_tier, row.price_at_add) == ("vip", Decimal("15.00"))


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"lang": "en"}, "ck_visits_lang"),
        # Недопустимый статус нарушает и ck_visits_closed_state; PostgreSQL проверяет CHECK по имени.
        ({"status": "archived"}, "ck_visits_closed_state"),
        ({"status": "closed"}, "ck_visits_closed_state"),
        ({"status": "closed", "closed_by": "staff"}, "ck_visits_closed_state"),
        ({"status": "closed", "closed_at": datetime.now(UTC)}, "ck_visits_closed_state"),
        ({"closed_at": datetime.now(UTC), "closed_by": "staff"}, "ck_visits_closed_state"),
        ({"closed_by": "staff"}, "ck_visits_closed_state"),
        ({"status": "closed", "closed_at": datetime.now(UTC), "closed_by": "waiter"}, "ck_visits_closed_by"),
    ],
)
async def test_visit_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    await expect_insert_violation(db_session, constraint, build_visit(tenant.id, table.id, **values))


async def test_unknown_visit_status_rejected_by_status_check(db_session: AsyncSession) -> None:
    """``ck_visits_status`` сам по себе отвергает значение вне перечисления (без ck_visits_closed_state)."""
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    visit = await create_visit(db_session, tenant.id, table.id)
    await db_session.execute(text("ALTER TABLE visits DROP CONSTRAINT ck_visits_closed_state"))

    async def set_status() -> None:
        await db_session.execute(update(Visit).where(Visit.id == visit.id).values(status="archived"))

    await expect_violation(db_session, "ck_visits_status", set_status)


@pytest.mark.parametrize("closed_by", ["staff", "pos", "timeout"])
async def test_closed_visit_accepted(db_session: AsyncSession, closed_by: str) -> None:
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    staff_id = uuid.uuid4() if closed_by == "staff" else None
    visit = await add(
        db_session,
        build_visit(
            tenant.id,
            table.id,
            status="closed",
            closed_at=datetime.now(UTC),
            closed_by=closed_by,
            closed_by_staff_id=staff_id,
        ),
    )
    # closed_by_staff_id — UUID без FK (ADR-7.7): произвольное значение принимается до #19.
    assert (visit.closed_by, visit.closed_by_staff_id) == (closed_by, staff_id)


async def test_message_defaults_and_cost_precision(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    question = await add(db_session, build_message(tenant.id, visit.id))
    assert (question.input_tokens, question.output_tokens) == (0, 0)
    assert (question.cache_read_tokens, question.cache_creation_tokens) == (0, 0)
    assert question.cost_usd == Decimal("0")
    assert question.created_at.tzinfo is not None
    answer = await add(
        db_session,
        build_message(
            tenant.id,
            visit.id,
            role="assistant",
            text=None,
            content=[{"type": "tool_use", "id": "t1", "name": "search_menu", "input": {"query": "суп"}}],
            model="model-from-config",
            input_tokens=1200,
            output_tokens=80,
            cache_read_tokens=1000,
            cache_creation_tokens=0,
            cost_usd=Decimal("0.001234"),
            latency_ms=850,
        ),
    )
    answer_id = answer.id
    db_session.expire_all()
    stored = await db_session.get(Message, answer_id)
    assert stored is not None
    assert stored.cost_usd == Decimal("0.001234")
    assert isinstance(stored.cost_usd, Decimal)
    assert stored.content == [{"type": "tool_use", "id": "t1", "name": "search_menu", "input": {"query": "суп"}}]


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"role": "system"}, "ck_messages_role"),
        ({"role": "tool"}, "ck_messages_role"),
        ({"content": {"type": "text"}}, "ck_messages_content"),
        ({"content": None}, "ck_messages_content_or_redacted"),
        ({"text": "x" * 8001}, "ck_messages_text"),
        ({"input_tokens": -1}, "ck_messages_input_tokens"),
        ({"output_tokens": -1}, "ck_messages_output_tokens"),
        ({"cache_read_tokens": -1}, "ck_messages_cache_read_tokens"),
        ({"cache_creation_tokens": -1}, "ck_messages_cache_creation_tokens"),
        ({"cost_usd": Decimal("-0.000001")}, "ck_messages_cost_usd"),
        ({"latency_ms": -1}, "ck_messages_latency_ms"),
        ({"redacted_at": datetime.now(UTC)}, "ck_messages_redacted_empty"),
    ],
)
async def test_message_checks(db_session: AsyncSession, values: dict[str, object], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    await expect_insert_violation(db_session, constraint, build_message(tenant.id, visit.id, **values))


async def test_message_redaction_keeps_tokens_and_cost(db_session: AsyncSession) -> None:
    """Обезличивание по dialog_retention_days (NFR-5): текст и блоки → NULL, метрики остаются."""
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    message = await add(
        db_session, build_message(tenant.id, visit.id, input_tokens=10, output_tokens=5, cost_usd=Decimal("0.000150"))
    )
    message_id = message.id

    async def redact_text_only() -> None:
        await db_session.execute(
            update(Message).where(Message.id == message_id).values(text=None, redacted_at=datetime.now(UTC))
        )

    await expect_violation(db_session, "ck_messages_redacted_empty", redact_text_only)

    pending = await db_session.scalar(
        select(func.count()).select_from(Message).where(Message.visit_id == visit.id, Message.redacted_at.is_(None))
    )
    assert pending == 1
    await db_session.execute(
        update(Message).where(Message.id == message_id).values(text=None, content=None, redacted_at=datetime.now(UTC))
    )
    db_session.expire_all()
    redacted = await db_session.get(Message, message_id)
    assert redacted is not None
    assert (redacted.text, redacted.content) == (None, None)
    assert redacted.redacted_at is not None
    assert (redacted.input_tokens, redacted.output_tokens, redacted.cost_usd) == (10, 5, Decimal("0.000150"))


async def test_deleting_visit_cascades_messages_and_cart(db_session: AsyncSession) -> None:
    """ADR-7.3: сообщения и корзина принадлежат визиту (CASCADE); позиция меню остаётся."""
    tenant = await create_tenant(db_session)
    visit = await create_visit(db_session, tenant.id)
    item = await create_menu_item(db_session, tenant.id)
    await add(db_session, build_cart_item(tenant.id, visit.id, item.id))
    await add(db_session, build_message(tenant.id, visit.id))
    await db_session.execute(delete(Visit).where(Visit.id == visit.id))
    assert await _count(db_session, CartItem, visit.id) == 0
    assert await _count(db_session, Message, visit.id) == 0
    assert await db_session.get(MenuItem, item.id) is not None


async def test_restrict_on_table_and_menu_item(db_session: AsyncSession) -> None:
    """Стол с визитом и позицию меню в корзине удалить нельзя (RESTRICT)."""
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    visit = await create_visit(db_session, tenant.id, table.id)
    item = await create_menu_item(db_session, tenant.id)
    await add(db_session, build_cart_item(tenant.id, visit.id, item.id))

    async def delete_table() -> None:
        await db_session.execute(delete(Table).where(Table.id == table.id))

    async def delete_menu_item() -> None:
        await db_session.execute(delete(MenuItem).where(MenuItem.id == item.id))

    await expect_violation(db_session, "fk_visits_tenant_id_table_id_tables", delete_table)
    await expect_violation(db_session, "fk_cart_items_tenant_id_menu_item_id_menu_items", delete_menu_item)


async def test_concurrent_open_race_resolved_by_index(db_session: AsyncSession) -> None:
    """Гонка двух первых сканирований (#9): ``INSERT … ON CONFLICT DO NOTHING`` по частичному индексу."""
    tenant = await create_tenant(db_session)
    table = await create_table(db_session, tenant.id)
    first = await create_visit(db_session, tenant.id, table.id)
    result = await db_session.execute(
        text(
            "INSERT INTO visits (id, tenant_id, table_id, lang) VALUES (:id, :tenant_id, :table_id, 'az') "
            "ON CONFLICT (table_id) WHERE status = 'open' DO NOTHING RETURNING id"
        ),
        {"id": uuid.uuid4(), "tenant_id": tenant.id, "table_id": table.id},
    )
    assert result.first() is None
    open_ids = (
        await db_session.scalars(select(Visit.id).where(Visit.table_id == table.id, Visit.status == "open"))
    ).all()
    assert open_ids == [first.id]
