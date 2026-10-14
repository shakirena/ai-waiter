"""CSV → ``TabularData`` (story #64, ADR-8.2). Только стандартная библиотека (``csv``).

- Кодировка — UTF-8, BOM допускается (``utf-8-sig``, так сохраняет Excel «CSV UTF-8»); иная —
  ``encoding`` с подсказкой пересохранить файл как «CSV UTF-8». cp1251 не угадывается:
  азербайджанские буквы (ə, ş, ğ) в ней не представимы.
- Разделитель — ``,`` или ``;`` (Excel с русской/азербайджанской локалью сохраняет ``;``):
  определяется по строке заголовка — тот, при котором находится больше обязательных колонок
  (при равенстве — тот, что даёт больше колонок); при ``;`` допускается десятичная запятая.
- Кавычки — RFC 4180 (``"`` удваивается внутри поля), переводы строк внутри кавычек допустимы;
  нарушение кавычек — ``unsupported_format`` с номером строки. Номер строки для сообщений —
  номер физической строки начала записи (заголовок — 1, если над ним нет пустых строк).
- Пустые строки (все поля пустые или из пробелов) пропускаются; лимиты ``MAX_DATA_ROWS`` и
  ``MAX_COLUMNS`` проверяются при чтении (чтение останавливается). Длину ячейки
  (``MAX_CELL_CHARS``) проверяет ``format``: глобальный ``csv.field_size_limit`` не меняется,
  поле длиннее его значения по умолчанию (128 КиБ) даёт ошибку разбора CSV.
"""

from __future__ import annotations

import csv
import io
from typing import Final

from app.menu_sync.files.format import (
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


def _is_blank(record: list[str]) -> bool:
    return not any(cell.strip() for cell in record)


def _first_record(text: str, delimiter: str) -> list[str]:
    """Первая непустая запись при данном разделителе (``[]`` — нет или ошибка разбора)."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        for record in reader:
            if not _is_blank(record):
                return record
    except csv.Error:
        return []
    return []


def _score(record: list[str]) -> tuple[int, int]:
    names = {cell.strip().lower() for cell in record}
    return sum(1 for column in REQUIRED_COLUMNS if column in names), len(record)


def detect_delimiter(text: str) -> str:
    """``,`` или ``;`` — по числу обязательных колонок в заголовке, затем по числу колонок."""
    comma, semicolon = (_score(_first_record(text, delimiter)) for delimiter in DELIMITERS)
    return DECIMAL_COMMA_DELIMITER if semicolon > comma else DELIMITERS[0]


def read_csv_table(data: bytes) -> tuple[TabularData | None, list[SyncIssue]]:
    """Прочитать CSV из байтов; ``None`` и проблемы уровня файла/заголовка при неудаче."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, [SyncIssue(IssueCode.ENCODING, f"{ENCODING_HINT} (неверный байт в позиции {exc.start})")]

    delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    header: tuple[str, ...] | None = None
    header_row = 0
    rows: list[SheetRow] = []
    while True:
        start = reader.line_num + 1
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            message = f"нарушен формат CSV (кавычки или слишком длинное поле): {exc}"
            return None, [SyncIssue(IssueCode.UNSUPPORTED_FORMAT, message, row=start)]
        if _is_blank(record):
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
        missing = ", ".join(REQUIRED_COLUMNS)
        return None, [SyncIssue(IssueCode.EMPTY_SNAPSHOT, f"файл пуст: нет строки заголовка с колонками {missing}")]
    return TabularData(
        header=header,
        header_row=header_row,
        rows=rows,
        decimal_comma=delimiter == DECIMAL_COMMA_DELIMITER,
    ), []
