from __future__ import annotations

import pytest

from app.core.events import Event, tenant_channel
from app.core.single.events import InMemoryEventBus


def test_tenant_channel_format() -> None:
    assert tenant_channel(7, "staff") == "tenant:7:staff"


async def test_subscriber_receives_published_event() -> None:
    bus = InMemoryEventBus()
    ch = tenant_channel(1, "staff")
    async with bus.subscribe(ch) as events:
        await bus.publish(ch, Event(type="test.ping", tenant_id=1))
        received = await anext(aiter(events))
    assert received.type == "test.ping"
    await bus.stop()


async def test_other_tenant_channel_is_isolated() -> None:
    pytest.skip("TODO(developer): событие tenant:2 не доходит до подписчика tenant:1")


async def test_slow_subscriber_does_not_block_publisher() -> None:
    pytest.skip("TODO(developer): при переполнении очереди старые события отбрасываются, publish не ждёт")
