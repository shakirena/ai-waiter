"""Конфигурация приложения — только переменные окружения (ADR-2).

Порядок источников (первый выигрывает): переменные окружения процесса →
``.env`` в текущем каталоге → ``../.env`` (корень репозитория при запуске из backend/).
Каждая новая настройка добавляется одновременно сюда и в ``.env.example``.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py → корень репозитория (без абсолютных путей в коде).
_REPO_ROOT = Path(__file__).resolve().parents[3]


class AppMode(StrEnum):
    """Режим запуска (ТЗ, раздел 8)."""

    SINGLE = "single"
    SCALED = "scaled"


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),  # позже в кортеже — выше приоритет
        env_file_encoding="utf-8",
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

    @model_validator(mode="after")
    def _check_mode_consistency(self) -> Self:
        if self.app_mode is AppMode.SCALED and self.redis_url is None:
            raise ValueError("REDIS_URL обязателен при APP_MODE=scaled")
        if self.app_mode is AppMode.SINGLE and self.api_workers != 1:
            raise ValueError(
                "APP_MODE=single работает только в одном процессе (EventBus/RateLimiter в памяти): "
                "задайте API_WORKERS=1 или переключитесь на APP_MODE=scaled"
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


@lru_cache
def get_settings() -> Settings:
    """Настройки процесса. Вызывается только в create_app()/__main__; остальной код — через Container."""
    return Settings()
