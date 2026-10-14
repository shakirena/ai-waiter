"""CSV → ``TabularData`` (story #64, ADR-8.2). Только стандартная библиотека (``csv``).

- Кодировка — UTF-8, BOM допускается (``utf-8-sig``, так сохраняет Excel «CSV UTF-8»); иная —
  ``encoding`` с подсказкой пересохранить файл как «CSV UTF-8». cp1251 не угадывается:
  азербайджанские буквы (ə, ş, ğ) в ней не представимы.
- Разделитель — ``,`` или ``;`` (Excel с русской/азербайджанской локалью сохраняет ``;``):
  определяется по строке заголовка — тот, при котором находится больше обязательных колонок
  (при равенстве — тот, что даёт больше колонок); при ``;`` допускается десятичная запятая.
  Заголовок ищется только среди первых ``HEADER_SEARCH_RECORDS`` записей.
- Кавычки — RFC 4180 (``"`` удваивается внутри поля), переводы строк внутри кавычек допустимы;
  нарушение кавычек — ``unsupported_format`` с номером строки. Номер строки для сообщений —
  номер физической строки начала записи (заголовок — 1, если над ним нет пустых строк).
- Пустые строки пропускаются: все поля пустые или состоят только из пробелов и символов
  ``,``/``;`` (строка ``,,,,`` пуста при любом разделителе). Пропускается не больше
  ``MAX_BLANK_RECORDS`` пустых записей — файл из одних переводов строк не читается целиком.
- Лимиты ``MAX_DATA_ROWS`` и ``MAX_COLUMNS`` проверяются при чтении (чтение останавливается).
  Физическая строка длиннее ``MAX_LINE_CHARS`` отвергается до разбора ``csv``: так одна строка
  из тысяч коротких полей не строит огромный список. Длину ячейки (``MAX_CELL_CHARS``) проверяет
  ``format``; глобальный ``csv.field_size_limit`` не меняется (поле не длиннее строки).
"""

from __future__ import annotations

import csv
import io
import string
from collections.abc import Iterator
from itertools import islice
from typing import Final

from app.menu_sync.files.format import (
    MAX_CELL_CHARS,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    REQUIRED_COLUMNS,
    SheetRow,
    TabularData,
)
from app.menu_sync.report import IssueCode, SyncIssue

DELIMITERS: Final[tuple[str, ...]] = (",", ";")
DECIMAL_COMMA_DELIMITER: Final[str] = ";"
ENCODING_HINT: Final[str] = "файл не в кодировке UTF-8: сохраните его в Excel как «CSV UTF-8»"
# Заголовок — среди первых записей файла (пустые строки над ним тоже считаются).
HEADER_SEARCH_RECORDS: Final[int] = 100
# Пустых записей (в любом месте файла) не больше: Excel дописывает пустые строки, но не миллионы.
MAX_BLANK_RECORDS: Final[int] = MAX_DATA_ROWS
# Самая длинная допустимая физическая строка: все колонки по MAX_CELL_CHARS, каждая в кавычках
# и из одних удвоенных кавычек, плюс разделители и перевод строки.
MAX_LINE_CHARS: Final[int] = MAX_COLUMNS * (2 * MAX_CELL_CHARS + 3) + 2

_BLANK_CHARS: Final[str] = string.whitespace + "".join(DELIMITERS)


class _LineTooLongError(Exception):
    def __init__(self, line: int) -> None:
        super().__init__(line)
        self.line = line


def _is_blank(record: list[str]) -> bool:
    return not any(cell.strip(_BLANK_CHARS) for cell in record)


def _lines(text: str) -> Iterator[str]:
    """Физические строки (с концами строк, как требует ``csv``) с проверкой ``MAX_LINE_CHARS``."""
    for number, line in enumerate(io.StringIO(text, newline=""), start=1):
        if len(line) > MAX_LINE_CHARS:
            raise _LineTooLongError(number)
        yield line


def _first_record(text: str, delimiter: str) -> list[str]:
    """Первая непустая запись среди ``HEADER_SEARCH_RECORDS`` первых (``[]`` — нет или ошибка разбора)."""
    reader = csv.reader(_lines(text), delimiter=delimiter, strict=True)
    try:
        for record in islice(reader, HEADER_SEARCH_RECORDS):
            if not _is_blank(record):
                return record
    except (csv.Error, _LineTooLongError):
        return []
    return []


def _score(record: list[str]) -> tuple[int, int]:
    names = {cell.strip().lower() for cell in record}
    return sum(1 for column in REQUIRED_COLUMNS if column in names), len(record)


def detect_delimiter(text: str) -> str:
    """``,`` или ``;`` — по числу обязательных колонок в заголовке, затем по числу колонок."""
    comma, semicolon = (_score(_first_record(text, delimiter)) for delimiter in DELIMITERS)
    return DECIMAL_COMMA_DELIMITER if semicolon > comma else DELIMITERS[0]


def _no_header() -> list[SyncIssue]:
    missing = ", ".join(REQUIRED_COLUMNS)
    return [
        SyncIssue(
            IssueCode.EMPTY_SNAPSHOT,
            f"нет строки заголовка в первых {HEADER_SEARCH_RECORDS} строках: нужны колонки {missing}",
        )
    ]


def read_csv_table(data: bytes) -> tuple[TabularData | None, list[SyncIssue]]:
    """Прочитать CSV из байтов; ``None`` и проблемы уровня файла/заголовка при неудаче."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, [SyncIssue(IssueCode.ENCODING, f"{ENCODING_HINT} (неверный байт в позиции {exc.start})")]

    delimiter = detect_delimiter(text)
    reader = csv.reader(_lines(text), delimiter=delimiter, strict=True)
    header: tuple[str, ...] | None = None
    header_row = 0
    rows: list[SheetRow] = []
    records = blank = 0
    while True:
        start = reader.line_num + 1
        try:
            record = next(reader)
        except StopIteration:
            break
        except _LineTooLongError as exc:
            message = f"строка длиннее {MAX_LINE_CHARS} символов: файл не похож на меню"
            return None, [SyncIssue(IssueCode.TOO_LONG, message, row=exc.line)]
        except csv.Error as exc:
            message = f"нарушен формат CSV (кавычки или слишком длинное поле): {exc}"
            return None, [SyncIssue(IssueCode.UNSUPPORTED_FORMAT, message, row=start)]
        records += 1
        if header is None and records > HEADER_SEARCH_RECORDS:
            return None, _no_header()  # как в detect_delimiter: дальше заголовок не ищется
        if _is_blank(record):
            blank += 1
            if blank > MAX_BLANK_RECORDS:
                message = f"больше {MAX_BLANK_RECORDS} пустых строк"
                return None, [SyncIssue(IssueCode.TOO_MANY_ROWS, message, row=start)]
            continue
        if len(record) > MAX_COLUMNS:
            return None, [SyncIssue(IssueCode.TOO_MANY_COLUMNS, f"больше {MAX_COLUMNS} колонок", row=start)]
        if header is None:
            header, header_row = tuple(record), start
            continue
        if len(rows) == MAX_DATA_ROWS:
            return None, [SyncIssue(IssueCode.TOO_MANY_ROWS, f"больше {MAX_DATA_ROWS} строк данных", row=start)]
        rows.append(SheetRow(number=start, values=tuple(record)))

    if header is None:
        return None, _no_header()
    return TabularData(
        header=header,
        header_row=header_row,
        rows=rows,
        decimal_comma=delimiter == DECIMAL_COMMA_DELIMITER,
    ), []
