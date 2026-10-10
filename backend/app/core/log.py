"""Структурированные логи (NFR-6). Расширяется в #32 (Sentry, трассировка ИИ)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from app.core.config import Settings

# Логгеры uvicorn переводятся на корневой обработчик, чтобы весь вывод процесса был в одном формате.
UVICORN_LOGGERS: tuple[str, ...] = ("uvicorn", "uvicorn.error", "uvicorn.access")

CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Метка обработчика, установленного configure_logging: повторный вызов заменяет его, а не дублирует.
_HANDLER_MARK = "_ai_waiter_handler"

# Стандартные атрибуты LogRecord; всё остальное в record.__dict__ пришло через ``extra=`` и уходит в JSON.
_RESERVED_ATTRS: frozenset[str] = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None)).keys()
    | {"message", "asctime", "taskName", "color_message"}  # color_message — копия msg uvicorn с ANSI-кодами
)

_SECRET_MASK = "*" * 10  # как str(SecretStr)


def _safe_value(value: Any) -> Any:
    """Значение для JSON: секреты маскируются, несериализуемое — строкой."""
    if isinstance(value, SecretStr):
        return _SECRET_MASK
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


class JsonFormatter(logging.Formatter):
    """Одна запись — одна строка JSON: ts (UTC, ISO 8601), level, logger, msg, поля из ``extra``, exc."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = _safe_value(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        # ensure_ascii: вывод службы Windows может идти в файл в кодировке ОС — JSON остаётся ASCII.
        return json.dumps(payload, ensure_ascii=True, default=str)


def _build_formatter(settings: Settings) -> logging.Formatter:
    if settings.log_format == "json":
        return JsonFormatter()
    return logging.Formatter(CONSOLE_FORMAT)


def configure_logging(settings: Settings) -> None:
    """stdlib logging: JSON-форматтер в одну строку (``log_format=json``) или читаемый (``console``);
    уровень ``settings.log_level``; логгеры uvicorn переводятся на тот же форматтер.
    Секреты (SecretStr) не выводятся. Повторный вызов идемпотентен."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_build_formatter(settings))
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # uvicorn (в т. ч. при запуске через CLI со своим log_config) пишет через корневой обработчик.
    for name in UVICORN_LOGGERS:
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
        uv_logger.setLevel(settings.log_level)
