from __future__ import annotations

import asyncio
import logging

import pytest

from app.core.events import Event, tenant_channel
from app.core.single import events as single_events
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
    bus = InMemoryEventBus()
    ch1, ch2 = tenant_channel(1, "staff"), tenant_channel(2, "staff")
    async with bus.subscribe(ch1) as events:
        await bus.publish(ch2, Event(type="foreign", tenant_id=2))
        await bus.publish(ch1, Event(type="own", tenant_id=1))
        received = await asyncio.wait_for(anext(aiter(events)), timeout=1)
    assert received.type == "own"
    await bus.stop()


async def test_slow_subscriber_does_not_block_publisher(caplog: pytest.LogCaptureFixture) -> None:
    bus = InMemoryEventBus(queue_size=3)
    ch = tenant_channel(1, "staff")
    async with bus.subscribe(ch) as events:
        with caplog.at_level(logging.WARNING, logger=single_events.__name__):
            # Подписчик не читает: publish не должен ждать его.
            async with asyncio.timeout(1):
                for i in range(10):
                    await bus.publish(ch, Event(type="e", tenant_id=1, payload={"i": i}))
        iterator = aiter(events)
        received = [(await anext(iterator)).payload["i"] for _ in range(3)]
    assert received == [7, 8, 9]
    warnings = [r for r in caplog.records if "отброшено" in r.getMessage()]
    assert len(warnings) == 1  # одно предупреждение на серию отбрасываний, не на каждое событие
    assert warnings[0].channel == ch  # type: ignore[attr-defined]
    await bus.stop()


async def test_drop_warning_repeats_every_n_drops(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(single_events, "DROP_WARNING_EVERY", 2)
    bus = InMemoryEventBus(queue_size=1)
    ch = tenant_channel(1, "staff")
    async with bus.subscribe(ch):
        with caplog.at_level(logging.WARNING, logger=single_events.__name__):
            for _ in range(6):  # 5 отброшенных: предупреждения на 1-м, 3-м, 5-м
                await bus.publish(ch, Event(type="e", tenant_id=1))
    assert len([r for r in caplog.records if "отброшено" in r.getMessage()]) == 3


async def test_all_subscribers_of_channel_receive_independent_copies() -> None:
    bus = InMemoryEventBus()
    ch = tenant_channel(1, "staff")
    event = Event(type="order.submitted", tenant_id=1, payload={"order": {"id": 5, "total": "12.50"}})
    async with bus.subscribe(ch) as first, bus.subscribe(ch) as second:
        await bus.publish(ch, event)
        a = await anext(aiter(first))
        b = await anext(aiter(second))
    assert a == event and b == event
    assert a is not event and a.payload is not b.payload
    a.payload["order"]["id"] = 999
    assert b.payload["order"]["id"] == 5
    assert event.payload["order"]["id"] == 5
    await bus.stop()


async def test_events_published_before_subscribe_are_not_delivered() -> None:
    bus = InMemoryEventBus()
    ch = tenant_channel(1, "staff")
    await bus.publish(ch, Event(type="early", tenant_id=1))  # подписчиков нет — событие теряется
    async with bus.subscribe(ch) as events:
        await bus.publish(ch, Event(type="late", tenant_id=1))
        assert (await anext(aiter(events))).type == "late"
    await bus.stop()


async def test_subscriber_waits_for_event_published_later() -> None:
    bus = InMemoryEventBus()
    ch = tenant_channel(1, "staff")
    async with bus.subscribe(ch) as events:
        waiter = asyncio.create_task(anext(aiter(events)))
        await asyncio.sleep(0.01)
        assert not waiter.done()
        await bus.publish(ch, Event(type="later", tenant_id=1))
        received = await asyncio.wait_for(waiter, timeout=1)
    assert received.type == "later"
    await bus.stop()


async def test_exit_from_context_unsubscribes() -> None:
    bus = InMemoryEventBus()
    ch = tenant_channel(1, "staff")
    async with bus.subscribe(ch) as events:
        pass
    assert bus._subscribers == {}
    await bus.publish(ch, Event(type="e", tenant_id=1))  # некому доставлять — не ошибка
    with pytest.raises(StopAsyncIteration):
        await anext(aiter(events))
    await bus.stop()


async def test_one_of_two_subscriptions_unsubscribes() -> None:
    bus = InMemoryEventBus()
    ch = tenant_channel(1, "staff")
    async with bus.subscribe(ch) as staying:
        async with bus.subscribe(ch):
            assert len(bus._subscribers[ch]) == 2
        assert len(bus._subscribers[ch]) == 1
        await bus.publish(ch, Event(type="e", tenant_id=1))
        assert (await anext(aiter(staying))).type == "e"
    await bus.stop()


async def test_stop_closes_active_subscriptions_without_hanging() -> None:
    bus = InMemoryEventBus()
    ch = tenant_channel(1, "staff")
    received: list[Event] = []
    entered = asyncio.Event()

    async def listener() -> None:
        async with bus.subscribe(ch) as events:
            entered.set()
            async for event in events:
                received.append(event)

    task = asyncio.create_task(listener())
    await entered.wait()
    await bus.publish(ch, Event(type="before-stop", tenant_id=1))
    await asyncio.sleep(0)
    await bus.stop()
    await asyncio.wait_for(task, timeout=1)  # итератор завершился, задача не висит
    assert [e.type for e in received] == ["before-stop"]
    assert bus._subscribers == {}
    assert await bus.ping() is False


async def test_subscribe_after_stop_fails_and_start_reenables() -> None:
    bus = InMemoryEventBus()
    ch = tenant_channel(1, "staff")
    await bus.start()
    assert await bus.ping() is True
    await bus.stop()
    with pytest.raises(RuntimeError, match="остановлена"):
        async with bus.subscribe(ch):
            pass  # pragma: no cover
    await bus.publish(ch, Event(type="e", tenant_id=1))  # после stop publish — no-op
    await bus.start()
    async with bus.subscribe(ch) as events:
        await bus.publish(ch, Event(type="again", tenant_id=1))
        assert (await anext(aiter(events))).type == "again"
    await bus.stop()


async def test_publish_rejects_non_event() -> None:
    bus = InMemoryEventBus()
    with pytest.raises(TypeError, match="Event"):
        await bus.publish(tenant_channel(1, "staff"), {"type": "x"})  # type: ignore[arg-type]


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_queue_size_must_be_positive_int(size: object) -> None:
    with pytest.raises(ValueError, match="queue_size"):
        InMemoryEventBus(queue_size=size)  # type: ignore[arg-type]
