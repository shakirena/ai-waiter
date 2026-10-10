"""Логи (#37, NFR-6): JSON в одну строку / console, уровень, uvicorn-логгеры, секреты не выводятся."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from app.core.log import UVICORN_LOGGERS, JsonFormatter, configure_logging
from tests.conftest import make_settings


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """Вернуть корневой логгер и логгеры uvicorn в исходное состояние после теста."""
    root = logging.getLogger()
    saved_root = (list(root.handlers), root.level)
    saved_uv = {
        name: (list(logging.getLogger(name).handlers), logging.getLogger(name).propagate) for name in UVICORN_LOGGERS
    }
    yield
    root.handlers[:] = saved_root[0]
    root.setLevel(saved_root[1])
    for name, (handlers, propagate) in saved_uv.items():
        uv_logger = logging.getLogger(name)
        uv_logger.handlers[:] = handlers
        uv_logger.propagate = propagate


def _record(msg: str, *args: object, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.WARNING, __file__, 1, msg, args or None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_single_line_with_fields() -> None:
    line = JsonFormatter().format(_record("Заказ %s\nпринят", 42, mode="single", count=3))
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "app.test"
    assert payload["msg"] == "Заказ 42\nпринят"
    assert payload["mode"] == "single"
    assert payload["count"] == 3
    assert payload["ts"].endswith("+00:00")


def test_json_formatter_masks_secrets_and_stringifies_objects() -> None:
    line = JsonFormatter().format(_record("x", key=SecretStr("sk-very-secret"), obj=object()))
    assert "sk-very-secret" not in line
    payload = json.loads(line)
    assert payload["key"] == "**********"
    assert payload["obj"].startswith("<object")


def test_json_formatter_drops_uvicorn_color_message() -> None:
    payload = json.loads(JsonFormatter().format(_record("старт", color_message="\x1b[36mстарт\x1b[0m")))
    assert "color_message" not in payload


def test_json_formatter_includes_exception() -> None:
    try:
        raise ValueError("сбой")
    except ValueError:
        record = logging.LogRecord("app.test", logging.ERROR, __file__, 1, "ошибка", None, sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError" in payload["exc"]


def test_configure_logging_json_level_and_idempotent() -> None:
    settings = make_settings(log_format="json", log_level="WARNING")
    configure_logging(settings)
    configure_logging(settings)
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, "_ai_waiter_handler", False)]
    assert len(ours) == 1
    assert isinstance(ours[0].formatter, JsonFormatter)
    assert root.level == logging.WARNING


def test_configure_logging_console_format() -> None:
    configure_logging(make_settings(log_format="console", log_level="DEBUG"))
    ours = [h for h in logging.getLogger().handlers if getattr(h, "_ai_waiter_handler", False)]
    assert not isinstance(ours[0].formatter, JsonFormatter)
    assert logging.getLogger().level == logging.DEBUG


def test_uvicorn_loggers_use_root_handler() -> None:
    logging.getLogger("uvicorn.access").addHandler(logging.NullHandler())
    configure_logging(make_settings(log_level="INFO"))
    for name in UVICORN_LOGGERS:
        uv_logger = logging.getLogger(name)
        assert uv_logger.handlers == []
        assert uv_logger.propagate is True
        assert uv_logger.level == logging.INFO


def test_json_output_written_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="json"))
    logging.getLogger("app.test").info("старт", extra={"mode": "single"})
    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("{")]
    assert json.loads(lines[-1])["mode"] == "single"
