"""Интерфейсы и общие типы ADR-1 (#38): Event, tenant_channel, TaskRegistry, PeriodicTask,
проверки enqueue, rate_key, проверки hit, ensure_json_object. Реализации single/scaled
проверяются в своих stories (#39, #40)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.events import Event, EventBus, tenant_channel
from app.core.payload import ensure_json_object
from app.core.ratelimit import RateLimiter, rate_key, validate_hit_args
from app.core.scheduler import PeriodicTask, TaskRegistry, TaskScheduler, is_valid_interval, validate_task
from tests.doubles import FakeEventBus, FakeRateLimiter, FakeTaskScheduler

# ---------------------------------------------------------------- ABC


@pytest.mark.parametrize("abc", [EventBus, TaskScheduler, RateLimiter])
def test_interfaces_cannot_be_instantiated(abc: type) -> None:
    with pytest.raises(TypeError):
        abc()


async def test_default_lifecycle_is_noop_and_ping_ok() -> None:
    class MinimalBus(EventBus):
        async def publish(self, channel: str, event: Event) -> None: ...

        def subscribe(self, channel: str) -> Any: ...

    class MinimalLimiter(RateLimiter):
        async def hit(self, key: str, *, limit: int, window: timedelta) -> Any: ...

        async def reset(self, key: str) -> None: ...

    for component in (MinimalBus(), MinimalLimiter()):
        await component.start()
        await component.stop()
        assert await component.ping() is True


# ---------------------------------------------------------------- события


def test_tenant_channel_contains_tenant() -> None:
    assert tenant_channel(1, "staff") == "tenant:1:staff"
    assert tenant_channel(12, "visit:5") == "tenant:12:visit:5"


@pytest.mark.parametrize(("tenant_id", "topic"), [(0, "staff"), (-1, "staff"), (True, "staff"), ("1", "staff")])
def test_tenant_channel_rejects_bad_tenant(tenant_id: Any, topic: str) -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        tenant_channel(tenant_id, topic)


@pytest.mark.parametrize("topic", ["", "two words", "tab\there", None])
def test_tenant_channel_rejects_bad_topic(topic: Any) -> None:
    with pytest.raises(ValueError, match="topic"):
        tenant_channel(1, topic)


def test_event_roundtrip_through_json() -> None:
    event = Event(type="order.submitted", tenant_id=3, payload={"order_id": 10, "total": "12.50"})
    restored = Event.model_validate_json(event.model_dump_json())
    assert restored == event
    assert restored.occurred_at.tzinfo is not None


@pytest.mark.parametrize(
    "payload",
    [{"total": Decimal("12.50")}, {"at": datetime.now(UTC)}, {"x": float("nan")}, {"ids": {1, 2}}, {1: "a"}],
)
def test_event_rejects_non_json_payload(payload: dict[Any, Any]) -> None:
    with pytest.raises(ValidationError, match="payload"):
        Event(type="x", tenant_id=1, payload=payload)


@pytest.mark.parametrize("tenant_id", [0, -5, True, "1"])
def test_event_requires_positive_int_tenant(tenant_id: Any) -> None:
    with pytest.raises(ValidationError):
        Event(type="x", tenant_id=tenant_id)


def test_event_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="occurred_at"):
        Event(type="x", tenant_id=1, occurred_at=datetime(2026, 1, 1))  # noqa: DTZ001 — проверяется отказ


def test_event_is_immutable() -> None:
    event = Event(type="x", tenant_id=1)
    with pytest.raises(ValidationError):
        event.type = "y"  # type: ignore[misc]


async def test_fake_bus_satisfies_contract_shape() -> None:
    bus = FakeEventBus()
    ch = tenant_channel(1, "staff")
    await bus.publish(ch, Event(type="t", tenant_id=1))
    async with bus.subscribe(ch) as events:
        assert [e.type async for e in events] == ["t"]


# ---------------------------------------------------------------- JSON payload


def test_ensure_json_object_accepts_nested_json() -> None:
    value = {"a": [1, "2", {"b": None, "c": True}], "d": 1.5}
    assert ensure_json_object(value) is value


@pytest.mark.parametrize(
    "value", [[1, 2], "x", None, {"a": {1: "nested int key"}}, {"a": [{2: "x"}]}, {"x": float("inf")}, {"o": object()}]
)
def test_ensure_json_object_rejects(value: Any) -> None:
    with pytest.raises(TypeError):
        ensure_json_object(value)


# ---------------------------------------------------------------- задачи


async def _noop(payload: dict[str, Any]) -> None:
    return None


def test_registry_task_registers_handler(registry: TaskRegistry) -> None:
    decorated = registry.task("demo.run")(_noop)
    assert decorated is _noop
    assert registry.get("demo.run") is _noop
    assert registry.handlers == {"demo.run": _noop}
    assert registry.periodic_tasks == []


def test_registry_periodic_registers_schedule(registry: TaskRegistry) -> None:
    registry.periodic("demo.sweep", every_minutes=5)(_noop)
    assert registry.get("demo.sweep") is _noop
    assert registry.periodic_tasks == [PeriodicTask(name="demo.sweep", every_minutes=5)]


def test_registry_periodic_rejects_bad_interval_at_declaration(registry: TaskRegistry) -> None:
    with pytest.raises(ValueError, match="every_minutes"):
        registry.periodic("demo.sweep", every_minutes=7)
    assert registry.handlers == {}


def test_registry_rejects_duplicates_between_task_and_periodic(registry: TaskRegistry) -> None:
    registry.task("demo")(_noop)
    with pytest.raises(ValueError, match="уже зарегистрирована"):
        registry.periodic("demo", every_minutes=1)
    registry.periodic("sweep", every_minutes=1)(_noop)
    with pytest.raises(ValueError, match="уже зарегистрирована"):
        registry.task("sweep")


@pytest.mark.parametrize("name", ["", "  ", " demo", None])
def test_registry_rejects_bad_names(registry: TaskRegistry, name: Any) -> None:
    with pytest.raises(ValueError):
        registry.task(name)


def test_registry_get_unknown_is_key_error(registry: TaskRegistry) -> None:
    with pytest.raises(KeyError, match="nope"):
        registry.get("nope")


def test_registry_collections_are_copies(registry: TaskRegistry) -> None:
    registry.task("demo")(_noop)
    registry.handlers.clear()
    registry.periodic_tasks.clear()
    assert "demo" in registry.handlers


@pytest.mark.parametrize(
    ("minutes", "valid"),
    [(2, True), (20, True), (180, True), (720, True), (59, False), (100, False), (2880, False), (True, False)],
)
def test_is_valid_interval(minutes: Any, valid: bool) -> None:
    assert is_valid_interval(minutes) is valid


def test_default_registry_is_shared_and_empty() -> None:
    from app.tasks import registry

    assert isinstance(registry, TaskRegistry)
    assert registry.handlers == {}


def test_validate_task_contract(registry: TaskRegistry) -> None:
    registry.task("demo")(_noop)
    assert validate_task(registry, "demo", None) == {}
    assert validate_task(registry, "demo", {"order_id": 1}) == {"order_id": 1}
    with pytest.raises(KeyError):
        validate_task(registry, "unknown", {})
    with pytest.raises(TypeError, match="demo"):
        validate_task(registry, "demo", {"total": Decimal("1.00")})


async def test_enqueue_contract_on_test_double(registry: TaskRegistry) -> None:
    registry.task("demo")(_noop)
    scheduler = FakeTaskScheduler(registry)
    with pytest.raises(KeyError):
        await scheduler.enqueue("unknown")
    with pytest.raises(TypeError):
        await scheduler.enqueue("demo", {"at": datetime.now(UTC)})
    with pytest.raises(ValueError, match="delay"):
        await scheduler.enqueue("demo", delay=timedelta(seconds=-1))
    job_id = await scheduler.enqueue("demo", {"x": 1}, delay=timedelta(seconds=1), job_id="order-1")
    assert job_id == "order-1"
    assert await scheduler.cancel("order-1") is True
    assert await scheduler.cancel("order-1") is False


# ---------------------------------------------------------------- rate-limit


def test_rate_key_single_scope() -> None:
    assert rate_key("login") == "login"
    assert rate_key("guest_msg", "ip", "203.0.113.7") == "guest_msg:ip:203.0.113.7"


@pytest.mark.parametrize("parts", [("",), ("a b",), (True,), (1.5,), (None,)])
def test_rate_key_rejects_bad_parts(parts: tuple[Any, ...]) -> None:
    with pytest.raises(ValueError):
        rate_key("scope", *parts)


@pytest.mark.parametrize("scope", ["", "a:b"])
def test_rate_key_rejects_bad_scope(scope: str) -> None:
    with pytest.raises(ValueError):
        rate_key(scope, 1)


def test_rate_key_ipv6_is_rejected_to_avoid_collisions() -> None:
    """IPv6 содержит ``:`` — вызывающий код обязан нормализовать адрес (например, заменить ``:`` на ``-``)."""
    with pytest.raises(ValueError):
        rate_key("guest_msg", "ip", "2001:db8::1")


@pytest.mark.parametrize(
    ("limit", "window"),
    [(0, timedelta(seconds=1)), (-1, timedelta(seconds=1)), (True, timedelta(seconds=1)), (1, timedelta(0))],
)
def test_validate_hit_args_rejects(limit: Any, window: timedelta) -> None:
    with pytest.raises(ValueError):
        validate_hit_args(limit, window)


async def test_fake_limiter_uses_shared_validation() -> None:
    limiter = FakeRateLimiter()
    result = await limiter.hit("k", limit=3, window=timedelta(seconds=10))
    assert result.allowed and result.remaining == 2 and result.retry_after == 0.0
    with pytest.raises(ValueError):
        await limiter.hit("k", limit=0, window=timedelta(seconds=10))
