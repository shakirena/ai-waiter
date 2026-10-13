"""CLI файлового импорта меню (story #66, ADR-8.6): ``python -m app.menu_sync``.

Команды::

    python -m app.menu_sync check FILE [--sheet NAME] [--json]
        Проверить формат файла без БД (подходит для проверки выгрузки кассы, ADR-8.8).

    python -m app.menu_sync import FILE --tenant UUID [--dry-run] [--force] [--allow-mass-hide]
                                        [--sheet NAME] [--database-url URL] [--json]
        Применить файл как полный снимок меню заведения (одна транзакция, «всё или ничего»).
        --dry-run          проверить и посчитать изменения, ничего не записывать и не журналировать;
        --force            применить, даже если хеш совпал с последним применённым снимком;
        --allow-mass-hide  разрешить скрыть много позиций сразу (защита плана, ADR-8.4).

Коды выхода: 0 — применено / без изменений / проверка пройдена; 1 — ошибка окружения (нет файла,
конфигурации, БД, заведения); 2 — ошибки в данных, ничего не записано; 3 — синхронизация меню
этого заведения уже идёт.

В отличие от ``app.seed``, команда разрешена при ``APP_ENV=prod`` — это рабочая операция.
Подключение — ``--database-url`` или ``DATABASE_URL`` (тот же ``.env``, что у приложения); текст
ошибки БД — через ``Database.describe_error`` (без пароля). Человекочитаемый отчёт — в stdout,
ошибки окружения — в stderr; ``--json`` печатает ``MenuSyncReport.to_dict()``.

Отклонённый импорт (ошибки данных) журналируется в ``menu_sync_runs`` отдельной транзакцией;
``check`` и ``--dry-run`` не журналируются. ``source_ref`` — только имя файла, без каталога.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Final

EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 1
EXIT_INVALID_DATA: Final[int] = 2
EXIT_BUSY: Final[int] = 3


def build_parser() -> argparse.ArgumentParser:
    """Парсер аргументов с подкомандами ``check`` и ``import`` (``prog="python -m app.menu_sync"``)."""
    raise NotImplementedError


def run_check(args: argparse.Namespace) -> int:
    """``check``: ``read_menu_file`` → отчёт формата; 0 без ошибок, 2 с ошибками, 1 — файла нет."""
    raise NotImplementedError


def run_import(args: argparse.Namespace) -> int:
    """``import``: разбор файла → ``apply_menu_snapshot`` в ``session.begin()`` → печать отчёта.

    Ошибки разбора или ``rejected`` → ``record_rejected_run`` (кроме ``--dry-run``) и код 2;
    ``MenuSyncBusyError`` → 3; ``TenantNotFoundError``, ошибки конфигурации и БД → 1.
    """
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI; возвращает код выхода процесса."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
