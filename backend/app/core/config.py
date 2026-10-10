"""Конфигурация приложения — только переменные окружения (ADR-2).

Порядок источников (первый выигрывает): переменные окружения процесса →
``.env`` в текущем каталоге → ``../.env`` (корень репозитория при запуске из backend/).
Каждая новая настройка добавляется одновременно сюда и в ``.env.example``.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py → корень репозитория (без абсолютных путей в коде).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Адреса, на которых допустимо слушать в режиме single (ТЗ 9.1: снаружи — только через туннель).
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


class AppMode(StrEnum):
    """Режим запуска (ТЗ, раздел 8)."""

    SINGLE = "single"
    SCALED = "scaled"


class AppEnv(StrEnum):
    """Окружение: в prod по умолчанию выключена документация OpenAPI и обязателен PUBLIC_BASE_URL."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),  # позже в кортеже — выше приоритет
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # «ПЕРЕМЕННАЯ=» без значения — как не заданная
        extra="ignore",
        case_sensitive=False,
    )

    # --- режим и окружение
    app_mode: AppMode = AppMode.SINGLE
    app_env: AppEnv = AppEnv.DEV

    # --- сервер (python -m app). single слушает только 127.0.0.1 (ТЗ 9.1)
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    api_workers: int = Field(default=1, ge=1)

    # --- хранилища. DATABASE_URL станет обязательным в #7 (модель данных); в каркасе к БД
    # никто не подключается, поэтому локальный запуск возможен без PostgreSQL (AC-9).
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None

    # --- внешний адрес: всегда домен
    public_base_url: AnyHttpUrl | None = None

    # --- фронтенд и файлы (ADR-3)
    serve_frontend: bool = True
    frontend_dist_dir: Path | None = None
    media_dir: Path = Path("media")

    # --- документация OpenAPI; None → включена вне prod
    docs_enabled: bool | None = None

    # --- логи (NFR-6)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- ИИ (используется с #11). Модель — только из конфигурации.
    anthropic_api_key: SecretStr | None = None
    ai_model: str | None = None

    # --- наблюдаемость (#32)
    sentry_dsn: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL должен использовать схему postgresql+asyncpg:// (ADR-5)")
        return value

    @field_validator("public_base_url")
    @classmethod
    def _check_public_base_url_is_domain(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is None:
            return value
        host = (value.host or "").strip("[]")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return value
        raise ValueError("PUBLIC_BASE_URL должен содержать доменное имя, а не IP-адрес")

    @model_validator(mode="after")
    def _check_mode_consistency(self) -> Self:
        if self.app_mode is AppMode.SCALED and self.redis_url is None:
            raise ValueError("REDIS_URL обязателен при APP_MODE=scaled")
        if self.app_mode is AppMode.SINGLE and self.api_workers != 1:
            raise ValueError(
                "APP_MODE=single работает только в одном процессе (EventBus/RateLimiter в памяти): "
                "задайте API_WORKERS=1 или переключитесь на APP_MODE=scaled"
            )
        if self.app_mode is AppMode.SINGLE and self.host not in LOOPBACK_HOSTS:
            raise ValueError(
                "APP_MODE=single слушает только loopback (HOST=127.0.0.1), снаружи — через туннель (ТЗ 9.1)"
            )
        if self.app_env is AppEnv.PROD and self.public_base_url is None:
            raise ValueError("PUBLIC_BASE_URL обязателен при APP_ENV=prod")
        return self

    @property
    def is_docs_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return self.app_env is not AppEnv.PROD

    @property
    def frontend_dist_path(self) -> Path:
        """Каталог сборки Vite; по умолчанию ``<repo>/frontend/dist``."""
        return self.frontend_dist_dir or (_REPO_ROOT / "frontend" / "dist")


class ConfigError(RuntimeError):
    """Ошибка конфигурации: понятный текст со списком переменных окружения, без значений секретов."""


_ERROR_TEXTS: dict[str, str] = {
    "missing": "обязательная переменная не задана",
    "enum": "недопустимое значение; допустимо: {expected}",
    "literal_error": "недопустимое значение; допустимо: {expected}",
    "int_parsing": "ожидается целое число",
    "bool_parsing": "ожидается true или false",
    "greater_than_equal": "значение должно быть не меньше {ge}",
    "less_than_equal": "значение должно быть не больше {le}",
    "url_parsing": "некорректный URL",
    "url_scheme": "недопустимая схема URL; допустимо: {expected_schemes}",
}

_VALUE_ERROR_PREFIX = "Value error, "


def _localize_choices(value: Any) -> Any:
    """``"'single' or 'scaled'"`` (текст pydantic) → ``"single, scaled"``."""
    if not isinstance(value, str):
        return value
    return value.replace(" or ", ", ").replace("'", "")


def _describe_error(error: Any) -> str:
    """Одна строка ошибки: имя переменной окружения и пояснение. Введённое значение не выводится —
    в нём может быть секрет."""
    loc = error.get("loc") or ()
    variable = str(loc[0]).upper() if loc else ""
    template = _ERROR_TEXTS.get(error.get("type", ""))
    if template is not None:
        try:
            ctx = {key: _localize_choices(value) for key, value in (error.get("ctx") or {}).items()}
            text = template.format(**ctx)
        except (KeyError, IndexError):
            text = str(error.get("msg", ""))
    else:
        text = str(error.get("msg", "")).removeprefix(_VALUE_ERROR_PREFIX)
    return f"{variable}: {text}" if variable else text


def format_validation_error(exc: ValidationError) -> str:
    """Текст для оператора: что исправить в переменных окружения или .env."""
    lines = [_describe_error(err) for err in exc.errors(include_input=False, include_url=False)]
    return "Ошибка конфигурации (переменные окружения или .env):\n" + "\n".join(f"  - {line}" for line in lines)


@lru_cache
def get_settings() -> Settings:
    """Настройки процесса. Вызывается только в create_app()/__main__; остальной код — через Container.

    Некорректная конфигурация → ``ConfigError`` с понятным текстом: приложение не стартует."""
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError(format_validation_error(exc)) from None
