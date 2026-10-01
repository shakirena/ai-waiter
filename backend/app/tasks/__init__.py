"""Единый реестр фоновых задач (ADR-1).

Задачи регистрируются здесь (или в модулях, импортируемых отсюда) и выполняются
одинаково в single (APScheduler) и scaled (arq worker)::

    @registry.task("escalations.sweep")
    async def sweep(payload: dict[str, Any]) -> None: ...

В каркасе задач нет — они появятся в #23 и далее.
"""

from app.core.scheduler import TaskRegistry

registry = TaskRegistry()

__all__ = ["registry"]
