"""Структурированные логи (NFR-6). Расширяется в #32 (Sentry, трассировка ИИ)."""

from __future__ import annotations

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """stdlib logging: JSON-форматтер в одну строку (``log_format=json``) или читаемый (``console``);
    уровень ``settings.log_level``; логгеры uvicorn переводятся на тот же форматтер.
    Секреты (SecretStr) не выводятся."""
    raise NotImplementedError
