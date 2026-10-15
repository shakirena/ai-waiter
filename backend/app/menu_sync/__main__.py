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
конфигурации, БД, заведения) или неверные аргументы; 2 — ошибки в данных, ничего не записано;
3 — синхронизация меню этого заведения уже идёт.

В отличие от ``app.seed``, команда разрешена при ``APP_ENV=prod`` — это рабочая операция.
Подключение — ``--database-url`` или ``DATABASE_URL`` (тот же ``.env``, что у приложения); текст
ошибки БД — через ``Database.describe_error`` (без пароля). Человекочитаемый отчёт — в stdout,
ошибки окружения — в stderr; ``--json`` печатает отчёт в виде JSON (ASCII, ``MenuSyncReport.to_dict()``
плюс сведения о файле).

Отклонённый импорт (ошибки данных) журналируется в ``menu_sync_runs`` отдельной транзакцией;
``check`` и ``--dry-run`` не журналируются, а ``--dry-run`` с ошибками разбора файла не обращается
к БД вовсе. ``source_ref`` — только имя файла, без каталога. Проблемы, найденные при применении
(``check_snapshot``: валюта, нулевая цена), получают номер строки и колонку файла (``locate_issues``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, format_validation_error
from app.db.session import Database
from app.menu_sync.files import ParsedMenuFile, locate_issues, read_menu_file
from app.menu_sync.report import EntityCounts, MenuSyncReport, Severity, SyncIssue, limit_issues, safe_text
from app.menu_sync.service import (
    MenuSyncBusyError,
    TenantNotFoundError,
    apply_menu_snapshot,
    record_rejected_run,
)
from app.models.enums import MenuSyncSource, MenuSyncStatus
from app.models.tenant import Tenant

EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 1
EXIT_INVALID_DATA: Final[int] = 2
EXIT_BUSY: Final[int] = 3

PROG: Final[str] = "python -m app.menu_sync"
# Имя и путь файла в выводе: невидимые символы экранированы, длина ограничена.
MAX_SHOWN_PATH_CHARS: Final[int] = 300
MIGRATIONS_HINT: Final[str] = "Проверьте DATABASE_URL и примените миграции: uv run alembic upgrade head"

# Подписи статуса: (применение, пробный прогон).
_STATUS_TEXT: Final[dict[MenuSyncStatus, tuple[str, str]]] = {
    MenuSyncStatus.APPLIED: ("меню применено", "меню будет применено"),
    MenuSyncStatus.UNCHANGED: (
        "без изменений: файл совпадает с последним применённым снимком",
        "без изменений: файл совпадает с последним применённым снимком",
    ),
    MenuSyncStatus.REJECTED: ("отклонено: ошибки в данных, ничего не записано", "отклонено: ошибки в данных"),
}


class _ArgumentParser(argparse.ArgumentParser):
    """Ошибка в аргументах — код ``EXIT_ERROR`` (а не 2 argparse): код 2 означает ошибки в данных файла."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_ERROR, f"{self.prog}: ошибка в аргументах: {message}\n")


def _tenant_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(
            "ожидается UUID заведения вида 01234567-89ab-cdef-0123-456789abcdef "
            "(его печатает python -m app.seed, позже покажет админка)"
        ) from None


def build_parser() -> argparse.ArgumentParser:
    """Парсер аргументов с подкомандами ``check`` и ``import`` (``prog="python -m app.menu_sync"``)."""
    parser = _ArgumentParser(
        prog=PROG,
        description="Импорт меню заведения из файла CSV или XLSX (полный снимок меню кассы).",
        epilog="Коды выхода: 0 — успех, 1 — ошибка окружения или аргументов, 2 — ошибки в данных, "
        "3 — синхронизация меню заведения уже идёт.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="{check,import}")

    check = commands.add_parser("check", help="проверить файл без базы данных", description="Проверить формат файла.")
    check.add_argument("file", metavar="FILE", help="файл меню .csv (UTF-8) или .xlsx")
    _add_common(check)
    check.set_defaults(handler=run_check)

    imp = commands.add_parser(
        "import",
        help="применить файл как полный снимок меню заведения",
        description="Применить файл как полный снимок меню заведения: позиции, которых нет в файле, скрываются.",
    )
    imp.add_argument("file", metavar="FILE", help="файл меню .csv (UTF-8) или .xlsx")
    imp.add_argument("--tenant", required=True, type=_tenant_uuid, metavar="UUID", help="UUID заведения")
    imp.add_argument(
        "--dry-run", action="store_true", help="только проверить и посчитать изменения, ничего не записывать"
    )
    imp.add_argument("--force", action="store_true", help="применить, даже если файл совпадает с последним снимком")
    imp.add_argument(
        "--allow-mass-hide",
        action="store_true",
        help="разрешить скрыть сразу много позиций (не меньше 10 и не меньше 30 %% видимых)",
    )
    imp.add_argument(
        "--database-url",
        metavar="URL",
        help="строка подключения postgresql+asyncpg://… (по умолчанию — DATABASE_URL из окружения или .env)",
    )
    _add_common(imp)
    imp.set_defaults(handler=run_import)
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sheet", metavar="NAME", help="лист книги XLSX (по умолчанию — «menu» или первый лист)")
    parser.add_argument("--json", action="store_true", help="машиночитаемый отчёт JSON в stdout")


# ---------------------------------------------------------------- общие части


def _error(message: str) -> None:
    print(message, file=sys.stderr)


def _shown(text: str) -> str:
    """Путь или имя файла для вывода: без управляющих символов, ограниченной длины."""
    return safe_text(text, MAX_SHOWN_PATH_CHARS)


def _file_name(file_arg: str) -> str:
    """Имя файла без каталога: в отчёт и журнал путь не попадает (в нём бывает имя пользователя)."""
    return Path(file_arg).name


def _read(file_arg: str, sheet: str | None) -> ParsedMenuFile | None:
    """Разобрать файл; ошибка файловой системы — сообщение в stderr и ``None`` (код 1)."""
    path = Path(file_arg)
    if path.is_dir():
        _error(f"Указан каталог, а не файл: {_shown(file_arg)}")
        return None
    try:
        return read_menu_file(path, sheet=sheet)
    except FileNotFoundError:
        _error(f"Файл не найден: {_shown(file_arg)}")
    except OSError as exc:
        _error(f"Не удалось прочитать файл {_shown(file_arg)}: {exc.strerror or type(exc).__name__}")
    return None


def _file_info(file_arg: str, parsed: ParsedMenuFile) -> dict[str, Any]:
    return {
        "file": _shown(_file_name(file_arg)),
        "format": parsed.file_format.value if parsed.file_format is not None else None,
        "rows": parsed.rows_total,
        "has_availability": parsed.has_availability,
    }


def _print_json(data: dict[str, Any]) -> None:
    # ASCII: JSON остаётся корректным при любой кодировке консоли и файла перенаправления.
    print(json.dumps(data, ensure_ascii=True, indent=2))


def _print_file_header(file_arg: str, parsed: ParsedMenuFile) -> None:
    fmt = parsed.file_format.value.upper() if parsed.file_format is not None else "формат не распознан"
    print(f"Файл: {_shown(_file_name(file_arg))} ({fmt}, строк данных: {parsed.rows_total})")
    if parsed.snapshot is not None:
        print(f"Категорий: {len(parsed.snapshot.categories)}, позиций: {len(parsed.snapshot.items)}")
        if not parsed.has_availability:
            print("Колонки is_available нет: наличие позиций не меняется.")


def _issue_line(issue: SyncIssue) -> str:
    level = "ошибка" if issue.severity is Severity.ERROR else "предупреждение"
    place: list[str] = []
    if issue.row is not None:
        place.append(f"строка {issue.row}")
    elif issue.external_id is not None:
        place.append(f"позиция {issue.external_id}")
    if issue.column is not None:
        place.append(f"колонка {issue.column}")
    where = f" ({', '.join(place)})" if place else ""
    value = f" [значение: «{issue.value}»]" if issue.value is not None else ""
    return f"  {level}{where}: {issue.message}{value}"


def _print_issues(issues: Sequence[SyncIssue], truncated: int) -> None:
    if not issues:
        return
    errors = sum(1 for issue in issues if issue.severity is Severity.ERROR)
    hidden = f", не показано ещё {truncated}" if truncated else ""
    print(f"Проблемы: ошибок {errors}, предупреждений {len(issues) - errors}{hidden}")
    for issue in issues:
        print(_issue_line(issue))


# ---------------------------------------------------------------- check


def run_check(args: argparse.Namespace) -> int:
    """``check``: ``read_menu_file`` → отчёт формата; 0 без ошибок, 2 с ошибками, 1 — файла нет."""
    parsed = _read(args.file, args.sheet)
    if parsed is None:
        return EXIT_ERROR
    ok = not parsed.has_errors
    if args.json:
        snapshot = parsed.snapshot
        _print_json(
            {
                "command": "check",
                **_file_info(args.file, parsed),
                "ok": ok,
                "categories": len(snapshot.categories) if snapshot is not None else None,
                "items": len(snapshot.items) if snapshot is not None else None,
                "issues": [issue.to_dict() for issue in parsed.issues],
                "issues_truncated": parsed.issues_truncated,
            }
        )
    else:
        _print_file_header(args.file, parsed)
        _print_issues(parsed.issues, parsed.issues_truncated)
        if ok:
            print("Проверка пройдена: файл можно импортировать (валюту и план изменений покажет import --dry-run).")
        else:
            print("Проверка не пройдена: исправьте ошибки, файл не будет применён.")
    return EXIT_OK if ok else EXIT_INVALID_DATA


# ---------------------------------------------------------------- import


def _load_settings(database_url: str | None) -> Settings:
    overrides: dict[str, Any] = {}
    if database_url:
        overrides["database_url"] = database_url
    return Settings(**overrides)


def _parse_failure_report(parsed: ParsedMenuFile, *, dry_run: bool) -> MenuSyncReport:
    """Отчёт ``rejected`` для файла с ошибками разбора: снимка и хеша нет."""
    return MenuSyncReport(
        status=MenuSyncStatus.REJECTED,
        dry_run=dry_run,
        issues=list(parsed.issues),
        issues_truncated=parsed.issues_truncated,
    )


@dataclass(frozen=True, slots=True)
class _ImportRequest:
    tenant_id: uuid.UUID
    source_ref: str
    dry_run: bool
    force: bool
    allow_mass_hide: bool
    started_at: datetime


async def _ensure_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Заведение есть, иначе ``TenantNotFoundError`` (запись журнала сослалась бы на несуществующее)."""
    if await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is None:
        raise TenantNotFoundError("заведение не найдено")


async def _import(database: Database, parsed: ParsedMenuFile, request: _ImportRequest) -> MenuSyncReport:
    """Применение снимка в одной транзакции; отклонённый импорт — запись журнала в отдельной."""
    try:
        if parsed.snapshot is None:
            report = _parse_failure_report(parsed, dry_run=request.dry_run)
        else:
            async with database.session() as session, session.begin():
                report = await apply_menu_snapshot(
                    session,
                    tenant_id=request.tenant_id,
                    snapshot=parsed.snapshot,
                    source=MenuSyncSource.FILE,
                    source_ref=request.source_ref,
                    dry_run=request.dry_run,
                    force=request.force,
                    allow_mass_hide=request.allow_mass_hide,
                )
            # Проблемы check_snapshot (валюта, нулевая цена) — с номером строки и колонкой файла.
            report.issues, _ = limit_issues(locate_issues(report.issues, parsed.item_rows))
        if report.status is MenuSyncStatus.REJECTED and not request.dry_run:
            async with database.session() as session, session.begin():
                await _ensure_tenant(session, request.tenant_id)
                report.run_id = await record_rejected_run(
                    session,
                    tenant_id=request.tenant_id,
                    source=MenuSyncSource.FILE,
                    source_ref=request.source_ref,
                    issues=report.issues,
                    issues_truncated=report.issues_truncated,
                    snapshot_hash=report.snapshot_hash,
                    started_at=request.started_at,
                )
        return report
    finally:
        await database.stop()


def _counts_line(title: str, counts: EntityCounts) -> str:
    return (
        f"{title}: создано {counts.created}, изменено {counts.updated}, скрыто {counts.hidden}, "
        f"возвращено {counts.restored}, без изменений {counts.unchanged}"
    )


def _print_import_report(file_arg: str, parsed: ParsedMenuFile, tenant_id: uuid.UUID, report: MenuSyncReport) -> None:
    _print_file_header(file_arg, parsed)
    print(f"Заведение: {tenant_id}")
    if report.dry_run:
        print("Режим: пробный прогон (--dry-run), в базу ничего не записано")
    applied_text, dry_run_text = _STATUS_TEXT[report.status]
    print(f"Статус: {report.status.value} — {dry_run_text if report.dry_run else applied_text}")
    if report.status is MenuSyncStatus.APPLIED:
        print(_counts_line("Категории", report.categories))
        print(_counts_line("Позиции", report.items))
        prices = report.prices
        print(f"Цены: добавлено {prices.created}, изменено {prices.updated}, удалено {prices.deleted}")
        print(f"Наличие изменено у позиций: {report.availability_changed}")
    if report.snapshot_hash is not None:
        print(f"Хеш снимка: {report.snapshot_hash}")
    if report.run_id is not None:
        print(f"Запись журнала: {report.run_id}")
    _print_issues(report.issues, report.issues_truncated)


def run_import(args: argparse.Namespace) -> int:
    """``import``: разбор файла → ``apply_menu_snapshot`` в ``session.begin()`` → печать отчёта.

    Ошибки разбора или ``rejected`` → ``record_rejected_run`` (кроме ``--dry-run``) и код 2;
    ``MenuSyncBusyError`` → 3; ``TenantNotFoundError``, ошибки конфигурации и БД → 1.
    """
    request = _ImportRequest(
        tenant_id=args.tenant,
        source_ref=_file_name(args.file),
        dry_run=args.dry_run,
        force=args.force,
        allow_mass_hide=args.allow_mass_hide,
        started_at=datetime.now(UTC),
    )
    parsed = _read(args.file, args.sheet)
    if parsed is None:
        return EXIT_ERROR

    if parsed.snapshot is None and request.dry_run:
        # Пробный прогон файла с ошибками разбора: журнала нет, база не нужна.
        report = _parse_failure_report(parsed, dry_run=True)
    else:
        try:
            settings = _load_settings(args.database_url)
        except ValidationError as exc:
            _error(format_validation_error(exc))
            return EXIT_ERROR
        database = Database(settings)
        try:
            report = asyncio.run(_import(database, parsed, request))
        except MenuSyncBusyError:
            _error("Синхронизация меню этого заведения уже идёт (другой импорт или коннектор). Повторите позже.")
            return EXIT_BUSY
        except TenantNotFoundError:
            _error(f"Заведение {request.tenant_id} не найдено: проверьте --tenant и DATABASE_URL.")
            return EXIT_ERROR
        except Exception as exc:
            _error(f"Не удалось выполнить импорт меню: {database.describe_error(exc)}")
            _error(MIGRATIONS_HINT)
            return EXIT_ERROR

    if args.json:
        info = _file_info(args.file, parsed)
        _print_json({"command": "import", **info, "tenant_id": str(request.tenant_id), **report.to_dict()})
    else:
        _print_import_report(args.file, parsed, request.tenant_id, report)
    return EXIT_INVALID_DATA if report.status is MenuSyncStatus.REJECTED else EXIT_OK


# ---------------------------------------------------------------- точка входа


def _tolerant_output() -> None:
    """Символ, которого нет в кодировке консоли или файла перенаправления (cp1251, cp866), печатается
    escape-последовательностью, а не роняет команду ``UnicodeEncodeError``."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI; возвращает код выхода процесса."""
    _tolerant_output()
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # --help (0) или ошибка в аргументах (EXIT_ERROR)
        return exc.code if isinstance(exc.code, int) else EXIT_ERROR
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
