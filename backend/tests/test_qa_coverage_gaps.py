"""Добивка покрытия редких веток каркаса (#37, #38, #39): запуск ``python -m app``, форматирование ошибок
конфигурации, JSON-лог со stack_info, закрытая подписка EventBus, отмена задачи без запущенного планировщика."""

from __future__ import annotations

import logging
import runpy
import sys
from typing import Any

import pytest

from app.core.config import _describe_error
from app.core.events import Event
from app.core.log import JsonFormatter
from app.core.scheduler import TaskRegistry
from app.core.single.events import InMemoryEventBus
from app.core.single.scheduler import InProcessTaskScheduler


def test_python_dash_m_app_calls_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Блок ``if __name__ == "__main__"``: ``python -m app`` запускает uvicorn с настройками из окружения."""
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setenv("APP_MODE", "single")
    monkeypatch.setenv("PORT", "8766")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        monkeypatch.delitem(sys.modules, "app.__main__", raising=False)
        runpy.run_module("app.__main__", run_name="__main__")
    finally:
        get_settings.cache_clear()
    assert len(calls) == 1
    assert calls[0][0] == ("app.main:create_app",)
    assert calls[0][1]["port"] == 8766
    assert calls[0][1]["host"] == "127.0.0.1"


def test_describe_error_falls_back_to_msg_when_template_context_is_missing() -> None:
    """Шаблон требует {expected}, а pydantic не передал ctx — вместо KeyError выводится исходное сообщение."""
    text = _describe_error({"type": "enum", "loc": ("app_mode",), "msg": "Input should be valid"})
    assert text == "APP_MODE: Input should be valid"


def test_json_formatter_includes_stack_info() -> None:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "стек", None, None)
    record.stack_info = "Stack (most recent call last):\n  File x"
    line = JsonFormatter().format(record)
    assert "\n" not in line
    assert "most recent call last" in line


async def test_push_to_closed_subscription_is_ignored() -> None:
    bus = InMemoryEventBus()
    async with bus.subscribe("t:1") as stream:
        subscription = stream
        subscription.close()  # type: ignore[attr-defined]
        subscription.push(Event(type="x", tenant_id=1))  # type: ignore[attr-defined]
        assert [e async for e in stream] == []


async def test_cancel_pending_job_without_running_apscheduler() -> None:
    """Планировщик не запущен (``_scheduler is None``): отмена ожидающей задачи всё равно успешна."""
    sched = InProcessTaskScheduler(TaskRegistry())
    sched._pending.add("job-1")
    assert await sched.cancel("job-1") is True
    assert await sched.cancel("job-1") is False
