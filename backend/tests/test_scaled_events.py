"""RedisEventBus на fakeredis (#40, spec AC-4): доставка между экземплярами, at-most-once,
ограниченная очередь, ping, закрытие."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fakeredis import FakeServer
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.events import Event, tenant_channel
from app.core.scaled import events as scaled_events
from app.core.scaled.events import RedisEventBus
from tests.fake_redis import redis_factory

REDIS_URL = "redis://redis:6379/0"
CHANNEL = tenant_channel(1, "staff")


def _event(n: int = 1, tenant_id: int = 1) -> Event:
    return Event(type="order.submitted", tenant_id=tenant_id, payload={"order_id": n, "total": "12.50"})


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
async def bus_pair(server: FakeServer) -> AsyncIterator[tuple[RedisEventBus, RedisEventBus]]:
    """Два «процесса api», подключённых к одному Redis."""
    first = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    second = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    await first.start()
    await second.start()
    yield first, second
    await first.stop()
    await second.stop()


async def _next(events: AsyncIterator[Event]) -> Event:
    return await asyncio.wait_for(anext(events), 2.0)


async def test_event_delivered_to_subscriber_of_another_instance(
    bus_pair: tuple[RedisEventBus, RedisEventBus],
) -> None:
    publisher, subscriber = bus_pair
    event = _event()
    async with subscriber.subscribe(CHANNEL) as events:
        await publisher.publish(CHANNEL, event)
        received = await _next(events)
    assert received == event
    assert received.payload == {"order_id": 1, "total": "12.50"}
    assert received.occurred_at.tzinfo is not None


async def test_publish_sends_model_dump_json_to_channel(server: FakeServer) -> None:
    bus = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    await bus.start()
    raw = redis_factory(server)(REDIS_URL)
    pubsub = raw.pubsub()
    await pubsub.subscribe(CHANNEL)
    await scaled_events._wait_subscribed(pubsub)
    event = _event()
    await bus.publish(CHANNEL, event)
    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
    assert message is not None
    assert message["channel"] == CHANNEL.encode()
    assert message["data"] == event.model_dump_json().encode()
    await pubsub.aclose()
    await raw.aclose()
    await bus.stop()


async def test_tenant_channels_are_isolated(bus_pair: tuple[RedisEventBus, RedisEventBus]) -> None:
    publisher, subscriber = bus_pair
    async with subscriber.subscribe(tenant_channel(2, "staff")) as other, subscriber.subscribe(CHANNEL) as own:
        await publisher.publish(CHANNEL, _event(1))
        await publisher.publish(tenant_channel(2, "staff"), _event(2, tenant_id=2))
        assert (await _next(own)).tenant_id == 1
        assert (await _next(other)).tenant_id == 2


async def test_multiple_subscribers_each_receive_event(bus_pair: tuple[RedisEventBus, RedisEventBus]) -> None:
    publisher, subscriber = bus_pair
    async with subscriber.subscribe(CHANNEL) as a, publisher.subscribe(CHANNEL) as b:
        await publisher.publish(CHANNEL, _event())
        assert (await _next(a)).payload["order_id"] == 1
        assert (await _next(b)).payload["order_id"] == 1


async def test_at_most_once_no_history_for_late_subscriber(bus_pair: tuple[RedisEventBus, RedisEventBus]) -> None:
    publisher, subscriber = bus_pair
    await publisher.publish(CHANNEL, _event(1))
    async with subscriber.subscribe(CHANNEL) as events:
        await publisher.publish(CHANNEL, _event(2))
        assert (await _next(events)).payload["order_id"] == 2


async def test_slow_subscriber_drops_oldest_with_warning(server: FakeServer, caplog: pytest.LogCaptureFixture) -> None:
    publisher = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    subscriber = RedisEventBus(REDIS_URL, queue_size=2, client_factory=redis_factory(server))
    await publisher.start()
    await subscriber.start()
    caplog.set_level(logging.WARNING, logger=scaled_events.__name__)
    async with subscriber.subscribe(CHANNEL) as events:
        for n in range(1, 6):
            await publisher.publish(CHANNEL, _event(n))
        # Даём читателю переложить все сообщения в очередь, не забирая их.
        for _ in range(50):
            await asyncio.sleep(0.01)
            if sum("переполнена" in r.getMessage() for r in caplog.records) >= 3:
                break
        received = [(await _next(events)).payload["order_id"] for _ in range(2)]
    assert received == [4, 5]
    assert sum("переполнена" in r.getMessage() for r in caplog.records) == 3
    await publisher.stop()
    await subscriber.stop()


async def test_invalid_message_is_skipped(server: FakeServer, caplog: pytest.LogCaptureFixture) -> None:
    bus = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    await bus.start()
    raw = redis_factory(server)(REDIS_URL)
    caplog.set_level(logging.WARNING, logger=scaled_events.__name__)
    async with bus.subscribe(CHANNEL) as events:
        await raw.publish(CHANNEL, b"not json")
        await bus.publish(CHANNEL, _event(7))
        assert (await _next(events)).payload["order_id"] == 7
    assert any("некорректное событие" in r.getMessage() for r in caplog.records)
    await raw.aclose()
    await bus.stop()


async def test_leaving_context_unsubscribes(bus_pair: tuple[RedisEventBus, RedisEventBus], server: FakeServer) -> None:
    publisher, subscriber = bus_pair
    async with subscriber.subscribe(CHANNEL):
        assert await publisher._require_client().pubsub_numsub(CHANNEL) == [(CHANNEL.encode(), 1)]
        assert len(subscriber._subscriptions) == 1
    assert subscriber._subscriptions == set()
    for _ in range(50):
        if await publisher._require_client().pubsub_numsub(CHANNEL) == [(CHANNEL.encode(), 0)]:
            break
        await asyncio.sleep(0.01)
    assert await publisher._require_client().pubsub_numsub(CHANNEL) == [(CHANNEL.encode(), 0)]


async def test_stop_finishes_active_subscriptions(server: FakeServer) -> None:
    bus = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    await bus.start()
    collected: list[Event] = []
    entered = asyncio.Event()

    async def consume() -> None:
        async with bus.subscribe(CHANNEL) as events:
            entered.set()
            async for event in events:
                collected.append(event)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 2.0)
    await bus.stop()
    await asyncio.wait_for(task, 2.0)
    assert collected == []
    assert await bus.ping() is False
    await bus.stop()  # повторная остановка безопасна


async def test_connection_loss_ends_iteration(server: FakeServer, caplog: pytest.LogCaptureFixture) -> None:
    bus = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    await bus.start()
    caplog.set_level(logging.WARNING, logger=scaled_events.__name__)
    async with bus.subscribe(CHANNEL) as events:
        subscription = next(iter(bus._subscriptions))
        subscription.reader.cancel()  # type: ignore[union-attr]
        await asyncio.wait([subscription.reader])  # type: ignore[list-item]
        subscription.reader = asyncio.create_task(bus._read(subscription))
        server.connected = False
        rest = [event async for event in events]
    assert rest == []
    assert any("потеряно соединение" in r.getMessage() for r in caplog.records)
    server.connected = True
    await bus.stop()


async def test_ping(server: FakeServer) -> None:
    bus = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    assert await bus.ping() is False  # не запущен
    await bus.start()
    assert await bus.ping() is True
    server.connected = False
    with pytest.raises(RedisConnectionError):
        await bus.ping()  # /health/ready ловит исключение и отвечает "fail"
    server.connected = True
    await bus.stop()


async def test_start_does_not_connect_and_is_idempotent() -> None:
    created: list[str] = []

    def factory(url: str) -> Any:
        created.append(url)
        return MagicMock()

    bus = RedisEventBus(REDIS_URL, client_factory=factory)
    await bus.start()
    await bus.start()
    assert created == [REDIS_URL]


async def test_not_started_raises() -> None:
    bus = RedisEventBus(REDIS_URL)
    with pytest.raises(RuntimeError, match="не запущен"):
        await bus.publish(CHANNEL, _event())
    with pytest.raises(RuntimeError, match="не запущен"):
        async with bus.subscribe(CHANNEL):
            pass


def test_queue_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="queue_size"):
        RedisEventBus(REDIS_URL, queue_size=0)


async def test_subscribe_timeout_closes_pubsub(monkeypatch: pytest.MonkeyPatch) -> None:
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.get_message = AsyncMock(return_value=None)
    pubsub.aclose = AsyncMock()
    client = MagicMock()
    client.pubsub.return_value = pubsub
    monkeypatch.setattr(scaled_events, "SUBSCRIBE_TIMEOUT_SECONDS", 0.05)
    bus = RedisEventBus(REDIS_URL, client_factory=lambda url: client)
    await bus.start()
    with pytest.raises(TimeoutError):
        async with bus.subscribe(CHANNEL):
            pass
    pubsub.aclose.assert_awaited_once()
    assert bus._subscriptions == set()


async def test_close_errors_are_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.get_message = AsyncMock(return_value={"type": "subscribe"})
    pubsub.unsubscribe = AsyncMock(side_effect=RedisConnectionError("down"))
    pubsub.aclose = AsyncMock()

    async def listen() -> AsyncIterator[dict[str, Any]]:
        await asyncio.Event().wait()
        yield {}

    pubsub.listen = listen
    client = MagicMock()
    client.pubsub.return_value = pubsub
    client.aclose = AsyncMock(side_effect=OSError("down"))
    bus = RedisEventBus(REDIS_URL, client_factory=lambda url: client)
    await bus.start()
    caplog.set_level(logging.WARNING, logger=scaled_events.__name__)
    async with bus.subscribe(CHANNEL):
        pass
    pubsub.aclose.assert_awaited_once()  # соединение возвращается в пул и при ошибке UNSUBSCRIBE
    await bus.stop()
    messages = [r.getMessage() for r in caplog.records]
    assert any("закрытии подписки" in m for m in messages)
    assert any("закрытии соединения" in m for m in messages)
    assert all(REDIS_URL not in m for m in messages)


async def test_stop_with_full_queue_still_ends_iteration(server: FakeServer) -> None:
    publisher = RedisEventBus(REDIS_URL, client_factory=redis_factory(server))
    subscriber = RedisEventBus(REDIS_URL, queue_size=1, client_factory=redis_factory(server))
    await publisher.start()
    await subscriber.start()
    async with subscriber.subscribe(CHANNEL) as events:
        subscription = next(iter(subscriber._subscriptions))
        await publisher.publish(CHANNEL, _event(1))
        for _ in range(50):
            if subscription.queue.full():
                break
            await asyncio.sleep(0.01)
        assert subscription.queue.full()
        await subscriber.stop()
        assert [event async for event in events] == []
    await publisher.stop()


async def test_non_message_frames_are_ignored() -> None:
    frames = [{"type": "subscribe", "data": 1}, {"type": "message", "data": _event(3).model_dump_json().encode()}]
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    pubsub.get_message = AsyncMock(return_value={"type": "subscribe"})

    async def listen() -> AsyncIterator[dict[str, Any]]:
        for frame in frames:
            yield frame

    pubsub.listen = listen
    client = MagicMock()
    client.pubsub.return_value = pubsub
    bus = RedisEventBus(REDIS_URL, client_factory=lambda url: client)
    await bus.start()
    async with bus.subscribe(CHANNEL) as events:
        received = [event async for event in events]
    assert [event.payload["order_id"] for event in received] == [3]
