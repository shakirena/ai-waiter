"""XLSX → ``TabularData`` (story #65; ADR-8.2, ADR-8.7). Единственный модуль, импортирующий ``openpyxl``.

Зависимости: ``openpyxl>=3.1`` и ``defusedxml>=0.7`` (openpyxl сам использует defusedxml, если он
установлен, — защита от XML-бомб и внешних сущностей).

Безопасность до разбора (``check_xlsx_archive``, ``zipfile``, без openpyxl):

- сигнатура zip, читаемый каталог архива, наличие ``xl/workbook.xml``; ``vbaProject.bin``
  (макросы, ``.xlsm``, переименованный в ``.xlsx``) — ``unsupported_format``;
- сумма распакованных размеров ≤ ``MAX_UNCOMPRESSED_BYTES``, степень сжатия каждого члена ≤
  ``MAX_COMPRESSION_RATIO`` — иначе ``unsafe_archive`` (zip-бомба). Распаковка ``zipfile``
  не выходит за объявленный размер члена, поэтому проверка заголовков достаточна.

Разбор: ``load_workbook(BytesIO(data), read_only=True, data_only=True)`` — формулы не
вычисляются, берётся сохранённое значение. Вторая книга с ``data_only=False`` читается
параллельно построчно только затем, чтобы отличить формулу без сохранённого значения
(``formula_without_value``) от пустой ячейки. Лист — ``sheet`` из аргумента (точное имя, иначе
без учёта регистра), иначе лист ``menu`` (без учёта регистра), иначе первый. Ячейки с ошибками
Excel (``#N/A``) и длительностями — ``CellProblem`` (``invalid_cell_type``), даты — как есть
(их отвергает ``format``). Объявленные размеры листа (``<dimension>``) не используются: строки и
колонки берутся из самих ячеек. Номер строки — номер строки листа. Книги закрываются в ``finally``.

Лимиты — как в CSV: ``MAX_DATA_ROWS`` строк данных и ``MAX_COLUMNS`` колонок; ячейки без
значения правее ``MAX_COLUMNS`` (отформатированные, но пустые) отбрасываются, значение там —
``too_many_columns``.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator, Sequence
from datetime import timedelta
from pathlib import PurePosixPath
from typing import Any, Final

from openpyxl import load_workbook

from app.menu_sync.files.format import (
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    REQUIRED_COLUMNS,
    Cell,
    CellProblem,
    SheetRow,
    TabularData,
)
from app.menu_sync.report import IssueCode, SyncIssue

DEFAULT_SHEET_NAME: Final[str] = "menu"
MAX_UNCOMPRESSED_BYTES: Final[int] = 50 * 1024 * 1024
MAX_COMPRESSION_RATIO: Final[int] = 100

ZIP_SIGNATURE: Final[bytes] = b"PK\x03\x04"
WORKBOOK_PART: Final[str] = "xl/workbook.xml"
MACRO_PART_NAME: Final[str] = "vbaproject.bin"
ERROR_DATA_TYPE: Final[str] = "e"  # тип ячейки openpyxl «ошибка Excel»

NOT_XLSX_HINT: Final[str] = "файл не является книгой .xlsx или повреждён: откройте его в Excel и сохраните как .xlsx"
MACRO_HINT: Final[str] = "книга с макросами (.xlsm) не поддерживается: сохраните её как «Книга Excel (.xlsx)»"
UNREADABLE_HINT: Final[str] = "не удалось прочитать книгу .xlsx: откройте её в Excel и сохраните заново"
FORMULA_HINT: Final[str] = (
    "формула без сохранённого значения: откройте файл в Excel, дождитесь пересчёта и сохраните, "
    "или замените формулу значением"
)


def _archive_issue(code: IssueCode, message: str) -> list[SyncIssue]:
    return [SyncIssue(code, message)]


def check_xlsx_archive(data: bytes) -> list[SyncIssue]:
    """Проверки zip-контейнера до openpyxl (сигнатура, макросы, zip-бомба); ``[]`` — можно разбирать."""
    if not data.startswith(ZIP_SIGNATURE):
        return _archive_issue(IssueCode.UNSUPPORTED_FORMAT, NOT_XLSX_HINT)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError, OSError):
        return _archive_issue(IssueCode.UNSUPPORTED_FORMAT, NOT_XLSX_HINT)

    names = {member.filename for member in members}
    if any(PurePosixPath(name).name.lower() == MACRO_PART_NAME for name in names):
        return _archive_issue(IssueCode.UNSUPPORTED_FORMAT, MACRO_HINT)
    if WORKBOOK_PART not in names:
        return _archive_issue(IssueCode.UNSUPPORTED_FORMAT, NOT_XLSX_HINT)

    limit_mb = MAX_UNCOMPRESSED_BYTES // (1024 * 1024)
    if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
        return _archive_issue(IssueCode.UNSAFE_ARCHIVE, f"распакованная книга больше {limit_mb} МБ")
    for member in members:
        if member.file_size > MAX_COMPRESSION_RATIO * max(member.compress_size, 1):
            message = f"часть книги сжата больше чем в {MAX_COMPRESSION_RATIO} раз: файл похож на zip-бомбу"
            return _archive_issue(IssueCode.UNSAFE_ARCHIVE, message)
    return []


def _select_sheet(workbook: Any, sheet: str | None) -> tuple[Any | None, list[SyncIssue]]:
    """Лист по правилам модуля; ``None`` и ``sheet_not_found`` со списком листов, если его нет."""
    worksheets = list(workbook.worksheets)
    if sheet is not None:
        found = next((ws for ws in worksheets if ws.title == sheet), None)
        if found is None:
            folded = sheet.strip().casefold()
            found = next((ws for ws in worksheets if ws.title.casefold() == folded), None)
        if found is not None:
            return found, []
        available = ", ".join(ws.title for ws in worksheets) or "нет листов"
        message = f"в книге нет листа с таким именем; листы: {available}"
        return None, [SyncIssue(IssueCode.SHEET_NOT_FOUND, message, value=sheet)]
    if not worksheets:
        return None, [SyncIssue(IssueCode.SHEET_NOT_FOUND, "в книге нет листов с таблицей")]
    default = next((ws for ws in worksheets if ws.title.strip().casefold() == DEFAULT_SHEET_NAME), None)
    return default or worksheets[0], []


def _cell_value(cell: Any, formula: object) -> Cell:
    """Значение ячейки из книги ``data_only=True`` с учётом той же ячейки книги с формулами."""
    value = cell.value
    if value is None:
        # Пустая в data_only, но непустая без него — формула без сохранённого значения.
        return None if formula is None else CellProblem(IssueCode.FORMULA_WITHOUT_VALUE, FORMULA_HINT)
    if cell.data_type == ERROR_DATA_TYPE:
        return CellProblem(IssueCode.INVALID_CELL_TYPE, f"ошибка Excel {value} вместо значения")
    if isinstance(value, timedelta):
        return CellProblem(IssueCode.INVALID_CELL_TYPE, "дата или время вместо значения: проверьте формат ячейки")
    return value


def _fit_columns(cells: Sequence[Any], formulas: Sequence[object]) -> bool:
    """Помещается ли строка в ``MAX_COLUMNS``: правее лимита допустимы только ячейки без значения.

    ``count`` — без цикла Python: отформатированная пустая ячейка в колонке XFD даёт строку
    из 16 384 элементов.
    """
    tail = formulas[MAX_COLUMNS:]
    return len(cells) <= MAX_COLUMNS or tail.count(None) == len(tail)


def _is_blank(values: Sequence[Cell]) -> bool:
    return all(value is None or (isinstance(value, str) and not value.strip()) for value in values)


def _header_text(value: Cell, position: int, row: int) -> str | SyncIssue:
    if isinstance(value, CellProblem):
        return SyncIssue(value.code, value.message, row=row, column=f"колонка {position + 1}")
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _rows(worksheet: Any, formula_sheet: Any) -> Iterator[tuple[int, Sequence[Any], Sequence[object]]]:
    """Строки листа (номер с 1, ячейки ``data_only``, значения с формулами) без объявленных размеров."""
    worksheet.reset_dimensions()
    formula_sheet.reset_dimensions()
    pairs = zip(worksheet.iter_rows(), formula_sheet.iter_rows(values_only=True), strict=True)
    for number, (cells, formulas) in enumerate(pairs, start=1):
        yield number, cells, formulas


def _read_sheet(worksheet: Any, formula_sheet: Any) -> tuple[TabularData | None, list[SyncIssue]]:
    header: tuple[str, ...] | None = None
    header_row = 0
    rows: list[SheetRow] = []
    for number, cells, formulas in _rows(worksheet, formula_sheet):
        if not _fit_columns(cells, formulas):
            return None, [SyncIssue(IssueCode.TOO_MANY_COLUMNS, f"больше {MAX_COLUMNS} колонок", row=number)]
        values = tuple(
            _cell_value(cell, formula)
            for cell, formula in zip(cells[:MAX_COLUMNS], formulas[:MAX_COLUMNS], strict=True)
        )
        if _is_blank(values):
            continue
        if header is None:
            texts = [_header_text(value, position, number) for position, value in enumerate(values)]
            problems = [text for text in texts if isinstance(text, SyncIssue)]
            if problems:
                return None, problems
            header, header_row = tuple(str(text) for text in texts), number
            continue
        if len(rows) == MAX_DATA_ROWS:
            return None, [SyncIssue(IssueCode.TOO_MANY_ROWS, f"больше {MAX_DATA_ROWS} строк данных", row=number)]
        rows.append(SheetRow(number=number, values=values))

    if header is None:
        missing = ", ".join(REQUIRED_COLUMNS)
        message = f"лист пуст: нет строки заголовка с колонками {missing}"
        return None, [SyncIssue(IssueCode.EMPTY_SNAPSHOT, message, value=worksheet.title)]
    return TabularData(header=header, header_row=header_row, rows=rows), []


def read_xlsx_table(data: bytes, *, sheet: str | None = None) -> tuple[TabularData | None, list[SyncIssue]]:
    """Прочитать лист XLSX из байтов; ``None`` и проблемы уровня файла/листа/заголовка при неудаче."""
    issues = check_xlsx_archive(data)
    if issues:
        return None, issues
    workbook: Any = None
    formula_book: Any = None
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        worksheet, issues = _select_sheet(workbook, sheet)
        if worksheet is None:
            return None, issues
        formula_book = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
        return _read_sheet(worksheet, formula_book[worksheet.title])
    except Exception:  # недоверенный файл: openpyxl и XML-парсер бросают исключения разных типов
        return None, [SyncIssue(IssueCode.UNSUPPORTED_FORMAT, UNREADABLE_HINT)]
    finally:
        for book in (workbook, formula_book):
            if book is not None:
                book.close()
