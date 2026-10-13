"""``python -m app.seed [--database-url URL]`` — загрузить демо-данные (ADR-7.12).

Коды выхода: 0 — успех, 1 — ошибка конфигурации или БД, 2 — запрет при ``APP_ENV=prod``.

1. ``APP_ENV`` читается до остальной конфигурации (окружение процесса, затем ``.env``, как у
   приложения): при ``prod`` — отказ, даже если задан ``--database-url``.
2. Подключение — ``--database-url`` или ``DATABASE_URL`` из ``Settings``.
3. ``app.seed.loader.apply_seed`` в одной транзакции; ошибка — откат, текст без пароля.
4. Печать относительных ссылок ``/t/{token}`` для локальной проверки.

Повторный запуск не создаёт дублей и возвращает данные к эталонным значениям. Event loop —
стандартный ``asyncio.run`` (на Windows — Proactor, с ним asyncpg работает, ADR-5).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from pydantic_settings import BaseSettings

from app.core.config import AppEnv, Settings, format_validation_error
from app.db.session import Database
from app.seed.loader import SeedSummary, apply_seed

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PROD_FORBIDDEN = 2

PROD_REFUSAL = (
    "Сид-данные запрещены при APP_ENV=prod: демо-токены столов детерминированы и годятся только "
    "для разработки. Запускайте команду на базе разработки (APP_ENV=dev)."
)


class _EnvironmentProbe(BaseSettings):
    """Только ``APP_ENV`` — из тех же источников, что ``Settings`` (окружение, ``.env``)."""

    model_config = Settings.model_config

    app_env: AppEnv = AppEnv.DEV


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description="Загрузить вымышленные демо-данные (заведение «Demo Restoran») в базу разработки.",
    )
    parser.add_argument(
        "--database-url",
        help="строка подключения postgresql+asyncpg://… (по умолчанию — DATABASE_URL из окружения или .env)",
    )
    return parser.parse_args(argv)


def _load_settings(database_url: str | None) -> Settings:
    overrides: dict[str, Any] = {}
    if database_url:
        overrides["database_url"] = database_url
    return Settings(**overrides)


async def _run(database: Database) -> SeedSummary:
    try:
        async with database.session() as session, session.begin():
            return await apply_seed(session)
    finally:
        await database.stop()


def _print_summary(summary: SeedSummary) -> None:
    print(f"Демо-данные загружены (заведение {summary.tenant_id}). Ссылки гостя:")
    for table in summary.tables:
        note = "" if table.is_active else " (стол неактивен)"
        print(f"  {table.name}: /t/{table.qr_token}{note}")


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI; возвращает код выхода процесса."""
    args = _parse_args(argv)
    try:
        app_env = _EnvironmentProbe().app_env
        if app_env is AppEnv.PROD:
            print(PROD_REFUSAL, file=sys.stderr)
            return EXIT_PROD_FORBIDDEN
        settings = _load_settings(args.database_url)
    except ValidationError as exc:
        print(format_validation_error(exc), file=sys.stderr)
        return EXIT_ERROR

    database = Database(settings)
    try:
        summary = asyncio.run(_run(database))
    except Exception as exc:
        print(f"Не удалось загрузить демо-данные: {database.describe_error(exc)}", file=sys.stderr)
        print("Проверьте DATABASE_URL и примените миграции: uv run alembic upgrade head", file=sys.stderr)
        return EXIT_ERROR
    _print_summary(summary)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
