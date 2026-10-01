from __future__ import annotations

import sys

from app.core.config import Settings
from app.core.container import build_container
from app.core.scheduler import TaskRegistry
from app.core.single.events import InMemoryEventBus
from app.core.single.ratelimit import InMemoryRateLimiter
from app.core.single.scheduler import InProcessTaskScheduler


def test_single_mode_uses_in_memory_implementations(
    settings: Settings, registry: TaskRegistry
) -> None:
    c = build_container(settings, registry)
    assert isinstance(c.event_bus, InMemoryEventBus)
    assert isinstance(c.scheduler, InProcessTaskScheduler)
    assert isinstance(c.rate_limiter, InMemoryRateLimiter)


def test_single_mode_does_not_import_scaled_backends(
    settings: Settings, registry: TaskRegistry
) -> None:
    build_container(settings, registry)
    assert "app.core.scaled.events" not in sys.modules
    assert "app.core.scaled.scheduler" not in sys.modules
    assert "app.core.scaled.ratelimit" not in sys.modules
