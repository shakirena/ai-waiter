"""Файловый коннектор: CSV/XLSX → ``MenuSnapshot`` (story #64, XLSX — #65; ADR-8.2).

Без БД — идёт в unit-тестах на Windows.

Формат описан в ``format``, в README («Формат файла меню») и в docs/arch/feature-8-menu-import.md;
пример — ``backend/tests/fixtures/menu/menu_valid.csv`` (данные вымышленные).

``read_menu_file`` читает байты (лимит ``MAX_FILE_BYTES`` проверяется через ``stat`` до чтения
содержимого и ещё раз при чтении), определяет формат по расширению и сигнатуре, вызывает
``csv_reader``/``xlsx_reader`` → ``TabularData`` → ``format.rows_to_snapshot``. Пути к файлу
приходят только из аргументов CLI или из загрузки в админке — в коде путей нет.

Политика «всё или ничего»: любая ошибка в любой строке — ``snapshot is None``. Список проблем
ограничен ``MAX_REPORTED_ISSUES`` (``limit_issues``), отброшенные считаются в ``issues_truncated``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Final

from app.menu_sync.files.csv_reader import read_csv_table
from app.menu_sync.files.format import TabularData, file_column, rows_to_snapshot
from app.menu_sync.report import IssueCode, SyncIssue, has_errors, limit_issues
from app.menu_sync.snapshot import MenuSnapshot

MAX_FILE_BYTES: Final[int] = 5 * 1024 * 1024
# Сигнатура zip (XLSX — zip-архив Office Open XML).
ZIP_SIGNATURE: Final[bytes] = b"PK\x03\x04"
UNSUPPORTED_HINT: Final[str] = "поддерживаются только .csv (UTF-8) и .xlsx; сохраните файл в одном из этих форматов"


class FileFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


@dataclass(frozen=True, slots=True)
class ParsedMenuFile:
    """Результат разбора. ``snapshot is None`` ⇔ есть ошибки (``issues`` с ``severity=error``).

    ``file_format is None`` — формат не распознан (``unsupported_format``) или файл слишком большой
    и с неизвестным расширением.
    """

    file_format: FileFormat | None
    snapshot: MenuSnapshot | None
    issues: list[SyncIssue] = field(default_factory=list)
    rows_total: int = 0  # строк данных без заголовка и пустых
    item_rows: dict[str, int] = field(default_factory=dict)  # external_id позиции → номер строки
    has_availability: bool = False  # есть ли колонка is_available (иначе наличие не меняется)
    issues_truncated: int = 0  # сколько проблем не вошло в issues (> MAX_REPORTED_ISSUES)

    @property
    def has_errors(self) -> bool:
        return has_errors(self.issues)


def _format_by_name(filename: str) -> FileFormat | None:
    suffix = PurePath(filename).suffix.lower()
    return next((fmt for fmt in FileFormat if suffix == f".{fmt.value}"), None)


def detect_format(filename: str, head: bytes) -> FileFormat | None:
    """Формат по расширению (``.csv``/``.xlsx``, без учёта регистра) с проверкой сигнатуры:
    ``.xlsx`` без ``ZIP_SIGNATURE`` или ``.csv`` с ней — ``None`` (``unsupported_format``)."""
    fmt = _format_by_name(filename)
    is_zip = head.startswith(ZIP_SIGNATURE)
    if fmt is FileFormat.CSV and not is_zip:
        return fmt
    if fmt is FileFormat.XLSX and is_zip:
        return fmt
    return None


def _result(
    file_format: FileFormat | None,
    snapshot: MenuSnapshot | None,
    issues: list[SyncIssue],
    *,
    rows_total: int = 0,
    item_rows: dict[str, int] | None = None,
    has_availability: bool = False,
) -> ParsedMenuFile:
    limited, truncated = limit_issues(issues)
    return ParsedMenuFile(
        file_format=file_format,
        snapshot=None if has_errors(issues) else snapshot,
        issues=limited,
        rows_total=rows_total,
        item_rows=item_rows or {},
        has_availability=has_availability,
        issues_truncated=truncated,
    )


def _too_large(filename: str) -> ParsedMenuFile:
    issue = SyncIssue(IssueCode.FILE_TOO_LARGE, f"файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ")
    return _result(_format_by_name(filename), None, [issue])


def _read_table(file_format: FileFormat, data: bytes, sheet: str | None) -> tuple[TabularData | None, list[SyncIssue]]:
    """Читатель по формату. XLSX подключается в #65 (``xlsx_reader.read_xlsx_table(data, sheet=sheet)``)."""
    if file_format is FileFormat.CSV:
        return read_csv_table(data)
    message = "формат .xlsx пока не поддерживается: сохраните файл как «CSV UTF-8»"
    return None, [SyncIssue(IssueCode.UNSUPPORTED_FORMAT, message, value=sheet)]


def parse_menu_bytes(data: bytes, filename: str, *, sheet: str | None = None) -> ParsedMenuFile:
    """Разобрать содержимое файла (общая точка для CLI и будущей загрузки в админке).

    ``filename`` — только для определения формата и сообщений; ``sheet`` — имя листа XLSX (для CSV
    не используется).
    """
    if len(data) > MAX_FILE_BYTES:
        return _too_large(filename)
    file_format = detect_format(filename, data[: len(ZIP_SIGNATURE)])
    if file_format is None:
        return _result(None, None, [SyncIssue(IssueCode.UNSUPPORTED_FORMAT, UNSUPPORTED_HINT)])
    table, issues = _read_table(file_format, data, sheet)
    if table is None:
        return _result(file_format, None, issues)
    snapshot, row_issues, item_rows, has_availability = rows_to_snapshot(table)
    return _result(
        file_format,
        snapshot,
        [*issues, *row_issues],
        rows_total=len(table.rows),
        item_rows=item_rows,
        has_availability=has_availability,
    )


def read_menu_file(path: Path, *, sheet: str | None = None) -> ParsedMenuFile:
    """Прочитать файл с диска (размер — ``stat`` до чтения) и вызвать ``parse_menu_bytes``.

    Ошибки файловой системы (нет файла, каталог, нет прав) — ``OSError`` вызывающему (CLI — код 1).
    """
    if path.stat().st_size > MAX_FILE_BYTES:
        return _too_large(path.name)
    with path.open("rb") as stream:
        # Файл мог вырасти после stat: читаем не больше лимита + 1 байт.
        data = stream.read(MAX_FILE_BYTES + 1)
    return parse_menu_bytes(data, path.name, sheet=sheet)


def locate_issues(issues: Iterable[SyncIssue], item_rows: Mapping[str, int]) -> list[SyncIssue]:
    """Проблемы ``check_snapshot``/плана (без строки, с ``external_id`` позиции) → со строкой и
    колонкой файла (``prices.vip`` → ``price_vip``) по ``ParsedMenuFile.item_rows``.

    Нужна CLI (#66): ``currency_mismatch`` и ``zero_price`` находит ``check_snapshot`` при применении.
    Проблемы со строкой или без известного ``external_id`` не меняются.
    """
    located: list[SyncIssue] = []
    for issue in issues:
        row = item_rows.get(issue.external_id) if issue.external_id is not None else None
        if issue.row is None and row is not None:
            issue = replace(issue, row=row, column=file_column(issue.column))
        located.append(issue)
    return located
