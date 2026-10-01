from __future__ import annotations

from typing import Any

import pytest

from app.core.scheduler import PeriodicTask, TaskRegistry


def test_registry_rejects_duplicate_names(registry: TaskRegistry) -> None:
    @registry.task("demo")
    async def first(payload: dict[str, Any]) -> None: ...

    with pytest.raises(ValueError):

        @registry.task("demo")
        async def second(payload: dict[str, Any]) -> None: ...


@pytest.mark.parametrize("minutes", [1, 5, 15, 30, 60, 120, 1440])
def test_periodic_interval_valid(minutes: int) -> None:
    PeriodicTask(name="x", every_minutes=minutes)


@pytest.mark.parametrize("minutes", [0, 7, 45, 90, 2000])
def test_periodic_interval_invalid(minutes: int) -> None:
    with pytest.raises(ValueError):
        PeriodicTask(name="x", every_minutes=minutes)


async def test_enqueue_rejects_unknown_task_and_non_json_payload() -> None:
    pytest.skip("TODO(developer): KeyError для неизвестного имени, TypeError для несериализуемого payload")


async def test_enqueue_runs_handler_in_single_mode() -> None:
    pytest.skip("TODO(developer): InProcessTaskScheduler выполняет обработчик из реестра")
