"""Формат файла меню (story #64): колонки, типы значений, строки → ``MenuSnapshot`` (ADR-8.2).

Одна строка — одна позиция; категория повторяется в каждой строке своих позиций. Первая
непустая строка — заголовок; имена колонок без учёта регистра и пробелов по краям, порядок любой.
Исключение — имя тарифа в ``price_<tier>``: только строчные латинские буквы, цифры и ``_``, как
в API (``price_VIP`` — ошибка ``invalid_tier``, а не молча другой тариф); ``price_default`` — в
любом регистре.

| Колонка | Обяз. | Значение |
|---|---|---|
| ``category_external_id`` | да | id категории в кассе, текст 1–64 |
| ``category_name`` | да | название категории в кассе, 1–200 |
| ``category_sort_key`` | нет | порядок категории, ≤ 64 (по умолчанию ``""``) |
| ``external_id`` | да | id позиции в кассе, текст 1–64 (``007`` ≠ ``7``) |
| ``name`` | да | название позиции в кассе, 1–200 |
| ``price_default`` | да | цена тарифа ``default`` |
| ``price_<tier>`` | нет | цена тарифа ``<tier>`` (``price_vip``); пусто — тарифа у позиции нет |
| ``currency`` | нет | ISO 4217; пусто — валюта заведения; иная — ошибка |
| ``station`` | нет | станция кухни/бара, ≤ 100 |
| ``sort_key`` | нет | порядок позиции, ≤ 64 |
| ``is_available`` | нет | ``1/0``, ``true/false``, ``yes/no``; нет колонки — не меняется; есть — обязательно |

Колонка, имя которой начинается с ``#``, игнорируется (комментарий). Остальные неизвестные
колонки — ошибка (опечатка ``price_VIP`` или ``is_avalable`` не должна молча потеряться).
Колонка с пустым заголовком допустима, только если пуста во всех строках (Excel дописывает
пустые колонки справа); значение в ней или за последней колонкой заголовка — ошибка.

Значения (``Cell`` — то, что отдал читатель CSV/XLSX):

- текст: обрезка пробелов; пустая строка = нет значения; длина и управляющие символы
  проверяются моделью снимка (``app.menu_sync.snapshot``), ошибка переводится в строку/колонку файла;
- ``external_id``: текст как есть; число из XLSX — целое без ``.0`` (``7.0`` → ``"7"``), дробное — ошибка;
- деньги: ``Decimal``/целое/текст ``8``, ``8.5``, ``8.50``; в CSV с разделителем ``;`` допускается
  десятичная запятая ``8,50``; ``float`` из XLSX — через ``repr`` (``8.1`` → ``8.1``), шум двоичной
  дроби (|x − round(x, 2)| < 1e-9) округляется, иначе > 2 знаков — ошибка; ядро не округляет;
- булево: bool из XLSX, ``1/0``, ``true/false``, ``yes/no`` без учёта регистра.

Все ошибки собираются (не останавливаемся на первой); снимок строится только без ошибок.
Строка с ошибкой в ячейке или с повтором ``external_id`` в модель снимка не передаётся, чтобы
одна причина не давала двух сообщений.

Валюта заведения здесь неизвестна (файл разбирается без БД): ``currency_mismatch`` и
предупреждение ``zero_price`` даёт ``check_snapshot`` при применении; номер строки к таким
проблемам добавляет ``app.menu_sync.files.locate_issues`` по ``external_id``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Final

from pydantic import ValidationError

from app.menu_sync.report import IssueCode, SyncIssue, has_errors, issue_value
from app.menu_sync.snapshot import (
    MAX_TIERS_PER_ITEM,
    MenuSnapshot,
    issues_from_validation_error,
)
from app.models.enums import DEFAULT_PRICE_TIER, PRICE_TIER_PATTERN
from app.schemas.money import MoneyError, MoneyErrorReason, parse_money

CATEGORY_EXTERNAL_ID: Final[str] = "category_external_id"
CATEGORY_NAME: Final[str] = "category_name"
CATEGORY_SORT_KEY: Final[str] = "category_sort_key"
EXTERNAL_ID: Final[str] = "external_id"
NAME: Final[str] = "name"
PRICE_PREFIX: Final[str] = "price_"
PRICE_DEFAULT: Final[str] = "price_default"
CURRENCY: Final[str] = "currency"
STATION: Final[str] = "station"
SORT_KEY: Final[str] = "sort_key"
IS_AVAILABLE: Final[str] = "is_available"
COMMENT_PREFIX: Final[str] = "#"

REQUIRED_COLUMNS: Final[tuple[str, ...]] = (CATEGORY_EXTERNAL_ID, CATEGORY_NAME, EXTERNAL_ID, NAME, PRICE_DEFAULT)
OPTIONAL_COLUMNS: Final[tuple[str, ...]] = (CATEGORY_SORT_KEY, CURRENCY, STATION, SORT_KEY, IS_AVAILABLE)

MAX_DATA_ROWS: Final[int] = 5000
MAX_COLUMNS: Final[int] = 50
MAX_CELL_CHARS: Final[int] = 1000

TRUE_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes"})
FALSE_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no"})
# Шум двоичной дроби float из XLSX, который округляется до двух знаков (0.1 + 0.2).
FLOAT_NOISE: Final[float] = 1e-9


@dataclass(frozen=True, slots=True)
class CellProblem:
    """Ячейка, значение которой читатель получить не смог (XLSX: ошибка Excel ``#N/A``, формула без
    сохранённого значения, длительность). Преобразователи ``cell_to_*`` дают ``CellError`` с этим
    кодом, поэтому проблема попадает в отчёт со строкой и колонкой, а в колонке-комментарии ``#…``
    игнорируется, как любое её значение."""

    code: IssueCode
    message: str


# Значение ячейки от читателя: CSV даёт только str; XLSX — типизированные значения openpyxl.
Cell = str | int | float | Decimal | bool | datetime | date | time | CellProblem | None

_TIER_RE: Final[re.Pattern[str]] = re.compile(PRICE_TIER_PATTERN)
_MONEY_CODES: Final[dict[MoneyErrorReason, IssueCode]] = {
    MoneyErrorReason.INVALID: IssueCode.INVALID_MONEY,
    MoneyErrorReason.FLOAT: IssueCode.INVALID_MONEY,
    MoneyErrorReason.TOO_MANY_DECIMALS: IssueCode.TOO_MANY_DECIMALS,
    MoneyErrorReason.NEGATIVE: IssueCode.NEGATIVE_PRICE,
    MoneyErrorReason.TOO_LARGE: IssueCode.PRICE_TOO_LARGE,
}


class CellError(ValueError):
    """Недопустимое значение ячейки: ``args[0]`` — ``IssueCode``, ``args[1]`` — причина на русском."""

    def __init__(self, code: IssueCode, message: str) -> None:
        super().__init__(code, message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class SheetRow:
    """Строка данных; ``number`` — номер строки в файле (заголовок — 1, как в Excel)."""

    number: int
    values: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class TabularData:
    """Таблица, прочитанная из CSV или XLSX, до интерпретации колонок."""

    header: tuple[str, ...]
    header_row: int
    rows: list[SheetRow]
    decimal_comma: bool = False  # CSV с разделителем «;»: допускается «8,50»


@dataclass(frozen=True, slots=True)
class ColumnLayout:
    """Разобранный заголовок: индексы известных колонок и тарифы ``price_<tier>``."""

    index: dict[str, int]  # известная колонка (кроме price_*) → индекс
    tiers: dict[str, int]  # тариф → индекс колонки (включая default)
    ignored: frozenset[int] = field(default_factory=frozenset)  # колонки «#…»


# ---------------------------------------------------------------- ячейки


def _check_not_temporal(cell: Cell, code: IssueCode = IssueCode.INVALID_CELL_TYPE) -> None:
    """Дата/время → ``CellError(code)``; ``CellProblem`` от читателя → ``CellError`` с её кодом."""
    if isinstance(cell, CellProblem):
        raise CellError(cell.code, cell.message)
    if isinstance(cell, datetime | date | time):
        raise CellError(code, "дата или время вместо значения: проверьте формат ячейки")


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral_value() else format(value, "f")


def cell_to_text(cell: Cell) -> str | None:
    """Текстовое значение ячейки (обрезка пробелов; пусто → ``None``); дата/время → ``CellError``.

    Числа из XLSX: целое (в том числе ``7.0``) — без ``.0``, дробное — ``repr``; булево — ошибка.
    """
    if cell is None:
        return None
    _check_not_temporal(cell)
    if isinstance(cell, bool):
        raise CellError(IssueCode.INVALID_CELL_TYPE, "логическое значение вместо текста")
    if isinstance(cell, str):
        text = cell.strip()
    elif isinstance(cell, int):
        text = str(cell)
    elif isinstance(cell, float):
        if not math.isfinite(cell):
            raise CellError(IssueCode.INVALID_CELL_TYPE, "недопустимое число")
        text = str(int(cell)) if cell.is_integer() else repr(cell)
    else:
        if not cell.is_finite():
            raise CellError(IssueCode.INVALID_CELL_TYPE, "недопустимое число")
        text = _decimal_text(cell)
    return text or None


def cell_to_external_id(cell: Cell) -> str | None:
    """``external_id``: текст как есть, целое число без ``.0``; дробное число → ``CellError``."""
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise CellError(IssueCode.INVALID_ID, "логическое значение вместо id")
    _check_not_temporal(cell, IssueCode.INVALID_ID)
    if isinstance(cell, float) and not cell.is_integer():
        raise CellError(IssueCode.INVALID_ID, "дробное число вместо id: сделайте колонку id текстовой")
    if isinstance(cell, Decimal) and (not cell.is_finite() or cell != cell.to_integral_value()):
        raise CellError(IssueCode.INVALID_ID, "дробное число вместо id: сделайте колонку id текстовой")
    if isinstance(cell, float):
        return str(int(cell))
    return cell_to_text(cell)


def cell_to_money(cell: Cell, *, decimal_comma: bool) -> Decimal | None:
    """Цена по правилам модуля; пусто → ``None``; ошибки — ``CellError`` с кодом в ``args[0]``."""
    if cell is None:
        return None
    _check_not_temporal(cell)
    value: object = cell
    if isinstance(cell, str):
        text = cell.strip()
        if not text:
            return None
        if decimal_comma and text.count(",") == 1 and "." not in text:
            text = text.replace(",", ".")
        value = text
    elif isinstance(cell, float):
        value = _float_to_decimal(cell)
    try:
        return parse_money(value)
    except MoneyError as exc:
        message = str(exc)
        if exc.reason in (MoneyErrorReason.INVALID, MoneyErrorReason.FLOAT):
            example = "8.50 или 8,50" if decimal_comma else "8.50"
            message = f"ожидается сумма без знака и пробелов, например {example}"
        raise CellError(_MONEY_CODES[exc.reason], message) from exc


def _float_to_decimal(value: float) -> Decimal:
    """``float`` из XLSX → ``Decimal`` через ``repr``; шум двоичной дроби округляется до двух знаков."""
    if not math.isfinite(value):
        raise CellError(IssueCode.INVALID_MONEY, "недопустимое число")
    rounded = round(value, 2)
    if abs(value - rounded) < FLOAT_NOISE:
        value = rounded
    return Decimal(repr(value))


def cell_to_bool(cell: Cell) -> bool | None:
    """Булево по ``TRUE_VALUES``/``FALSE_VALUES``; пусто → ``None``; иное → ``CellError``."""
    if cell is None or isinstance(cell, bool):
        return cell
    _check_not_temporal(cell)
    text = cell_to_text(cell)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in TRUE_VALUES:
        return True
    if lowered in FALSE_VALUES:
        return False
    raise CellError(IssueCode.INVALID_BOOL, "ожидается 1/0, true/false или yes/no")


# ---------------------------------------------------------------- заголовок


def parse_header(header: tuple[str, ...], header_row: int) -> tuple[ColumnLayout | None, list[SyncIssue]]:
    """Проверить заголовок: обязательные колонки, дубли, неизвестные, имена тарифов (``PRICE_TIER_PATTERN``).

    Все проблемы заголовка собираются; при любой ошибке раскладка — ``None``.
    """
    issues: list[SyncIssue] = []

    def problem(code: IssueCode, message: str, column: str | None = None) -> None:
        issues.append(SyncIssue(code, message, row=header_row, column=column, value=column))

    if len(header) > MAX_COLUMNS:
        problem(IssueCode.TOO_MANY_COLUMNS, f"больше {MAX_COLUMNS} колонок")
        return None, issues

    index: dict[str, int] = {}
    tiers: dict[str, int] = {}
    ignored: set[int] = set()
    for position, raw in enumerate(header):
        name = raw.strip()
        if not name:
            continue  # пустой заголовок: допустим, если колонка пуста (rows_to_snapshot)
        if name.startswith(COMMENT_PREFIX):
            ignored.add(position)
            continue
        lowered = name.lower()
        if lowered.startswith(PRICE_PREFIX):
            tier = DEFAULT_PRICE_TIER if lowered == PRICE_DEFAULT else name[len(PRICE_PREFIX) :]
            if not _TIER_RE.fullmatch(tier):
                problem(
                    IssueCode.INVALID_TIER,
                    "недопустимое имя тарифа: после price_ — строчные латинские буквы, цифры и _ (price_vip)",
                    name,
                )
            elif tier in tiers:
                problem(IssueCode.DUPLICATE_COLUMN, "колонка повторяется", name)
            else:
                tiers[tier] = position
        elif lowered in REQUIRED_COLUMNS or lowered in OPTIONAL_COLUMNS:
            if lowered in index:
                problem(IssueCode.DUPLICATE_COLUMN, "колонка повторяется", name)
            else:
                index[lowered] = position
        else:
            problem(
                IssueCode.UNKNOWN_COLUMN,
                "неизвестная колонка; чтобы оставить её как комментарий, начните имя с #",
                name,
            )

    for column in REQUIRED_COLUMNS:
        present = DEFAULT_PRICE_TIER in tiers if column == PRICE_DEFAULT else column in index
        if not present:
            problem(IssueCode.MISSING_COLUMN, "нет обязательной колонки", column)
    if len(tiers) > MAX_TIERS_PER_ITEM:
        problem(IssueCode.TOO_MANY_COLUMNS, f"больше {MAX_TIERS_PER_ITEM} колонок цен price_<tier>")

    if has_errors(issues):
        return None, issues
    return ColumnLayout(index=index, tiers=tiers, ignored=frozenset(ignored)), issues


# ---------------------------------------------------------------- строки → снимок

_CATEGORY_COLUMNS: Final[dict[str, str]] = {
    "external_id": CATEGORY_EXTERNAL_ID,
    "name": CATEGORY_NAME,
    "sort_key": CATEGORY_SORT_KEY,
}
_PRICES_FIELD_PREFIX: Final[str] = "prices."
# Ячейка, значение которой не удалось получить (проблема уже записана).
_FAILED: Final[Any] = object()


def file_column(field_name: str | None, *, category: bool = False) -> str | None:
    """Поле снимка в отчёте (``prices.vip``, ``name`` категории) → имя колонки файла (``price_vip``,
    ``category_name``). Поля без соответствия возвращаются как есть."""
    if field_name is None:
        return None
    if category:
        return _CATEGORY_COLUMNS.get(field_name, field_name)
    if field_name.startswith(_PRICES_FIELD_PREFIX):
        return PRICE_PREFIX + field_name[len(_PRICES_FIELD_PREFIX) :]
    return field_name


def _is_blank(cell: Cell) -> bool:
    return cell is None or (isinstance(cell, str) and not cell.strip())


class _SnapshotBuilder:
    """Собирает сырые данные снимка по строкам и ведёт номера строк элементов."""

    def __init__(self, layout: ColumnLayout, *, decimal_comma: bool) -> None:
        self.layout = layout
        self.decimal_comma = decimal_comma
        self.issues: list[SyncIssue] = []
        self.item_rows: dict[str, int] = {}  # external_id → первая строка
        self.items: list[dict[str, Any]] = []
        self.item_numbers: list[int] = []  # строка каждого элемента self.items
        self.categories: dict[str, dict[str, Any]] = {}
        self.category_rows: dict[str, int] = {}  # category_external_id → первая строка
        self._known = frozenset({*layout.index.values(), *layout.tiers.values(), *layout.ignored})

    def _problem(
        self,
        row: int,
        code: IssueCode,
        message: str,
        column: str | None,
        external_id: str | None,
        value: object = None,
    ) -> None:
        self.issues.append(
            SyncIssue(code, message, row=row, column=column, external_id=external_id, value=issue_value(value))
        )

    def _money(self, cell: Cell) -> Decimal | None:
        return cell_to_money(cell, decimal_comma=self.decimal_comma)

    def _value(
        self,
        row: SheetRow,
        column: str,
        position: int,
        convert: Any,
        *,
        required: bool,
        external_id: str | None,
    ) -> Any:
        """Значение ячейки или ``_FAILED`` (проблема записана)."""
        cell = row.values[position] if position < len(row.values) else None
        if isinstance(cell, str) and len(cell) > MAX_CELL_CHARS:
            self._problem(
                row.number, IssueCode.TOO_LONG, f"длиннее {MAX_CELL_CHARS} символов", column, external_id, cell
            )
            return _FAILED
        try:
            value = convert(cell)
        except CellError as exc:
            self._problem(row.number, exc.code, exc.message, column, external_id, cell)
            return _FAILED
        if value is None and required:
            self._problem(row.number, IssueCode.REQUIRED, "обязательное значение не заполнено", column, external_id)
            return _FAILED
        return value

    def _optional(self, row: SheetRow, column: str, convert: Any, external_id: str | None) -> Any:
        position = self.layout.index.get(column)
        if position is None:
            return None
        return self._value(row, column, position, convert, required=False, external_id=external_id)

    def add_row(self, row: SheetRow) -> None:
        start = len(self.issues)
        index = self.layout.index
        for position, cell in enumerate(row.values):
            if position not in self._known and not _is_blank(cell):
                self._problem(
                    row.number,
                    IssueCode.UNKNOWN_COLUMN,
                    "значение в колонке без заголовка",
                    f"колонка {position + 1}",
                    None,
                    cell,
                )

        eid = self._value(row, EXTERNAL_ID, index[EXTERNAL_ID], cell_to_external_id, required=True, external_id=None)
        ref = eid if isinstance(eid, str) else None
        category_id = self._value(
            row, CATEGORY_EXTERNAL_ID, index[CATEGORY_EXTERNAL_ID], cell_to_external_id, required=True, external_id=ref
        )
        category_name = self._value(
            row, CATEGORY_NAME, index[CATEGORY_NAME], cell_to_text, required=True, external_id=ref
        )
        category_sort = self._optional(row, CATEGORY_SORT_KEY, cell_to_text, ref)
        name = self._value(row, NAME, index[NAME], cell_to_text, required=True, external_id=ref)
        prices: dict[str, Decimal] = {}
        for tier, position in self.layout.tiers.items():
            price = self._value(
                row,
                PRICE_PREFIX + tier,
                position,
                self._money,
                required=tier == DEFAULT_PRICE_TIER,
                external_id=ref,
            )
            if isinstance(price, Decimal):
                prices[tier] = price
        currency = self._optional(row, CURRENCY, cell_to_text, ref)
        station = self._optional(row, STATION, cell_to_text, ref)
        sort_key = self._optional(row, SORT_KEY, cell_to_text, ref)
        is_available = None
        if IS_AVAILABLE in index:
            is_available = self._value(
                row, IS_AVAILABLE, index[IS_AVAILABLE], cell_to_bool, required=True, external_id=ref
            )

        if isinstance(category_id, str) and category_name is not _FAILED and category_sort is not _FAILED:
            self._add_category(row.number, category_id, category_name, category_sort or "", ref)
        if ref is not None:
            first = self.item_rows.setdefault(ref, row.number)
            if first != row.number:
                self._problem(
                    row.number,
                    IssueCode.DUPLICATE_EXTERNAL_ID,
                    f"повтор external_id позиции (строка {first})",
                    EXTERNAL_ID,
                    ref,
                    ref,
                )
        if len(self.issues) > start:
            return  # строка с ошибкой в модель не передаётся: одна причина — одно сообщение
        self.items.append(
            {
                "external_id": eid,
                "category_external_id": category_id,
                "name": name,
                "prices": prices,
                "currency": currency,
                "station": station,
                "sort_key": sort_key or "",
                "is_available": is_available,
            }
        )
        self.item_numbers.append(row.number)

    def _add_category(self, row: int, category_id: str, name: str, sort_key: str, ref: str | None) -> None:
        known = self.categories.get(category_id)
        if known is None:
            self.categories[category_id] = {"external_id": category_id, "name": name, "sort_key": sort_key}
            self.category_rows[category_id] = row
            return
        first = self.category_rows[category_id]
        for column, key, value in ((CATEGORY_NAME, "name", name), (CATEGORY_SORT_KEY, "sort_key", sort_key)):
            if known[key] != value:
                self._problem(
                    row,
                    IssueCode.CATEGORY_CONFLICT,
                    f"категория {category_id}: значение отличается от строки {first} ({known[key]!r})",
                    column,
                    ref,
                    value,
                )

    def validate(self) -> tuple[MenuSnapshot | None, list[SyncIssue]]:
        """Модель снимка над строками без ошибок; ошибки Pydantic → строка и колонка файла."""
        data: dict[str, Any] = {"categories": list(self.categories.values()), "items": self.items}
        try:
            return MenuSnapshot.model_validate(data), []
        except ValidationError as exc:
            category_ids = list(self.categories)
            located: list[SyncIssue] = []
            for error, issue in zip(exc.errors(), issues_from_validation_error(exc, data), strict=True):
                loc = error["loc"]
                row: int | None = None
                category = False
                if len(loc) >= 2 and isinstance(loc[1], int):
                    if loc[0] == "items":
                        row = self.item_numbers[loc[1]]
                    else:  # "categories": других списков в снимке нет
                        row = self.category_rows[category_ids[loc[1]]]
                        category = True
                located.append(replace(issue, row=row, column=file_column(issue.column, category=category)))
            return None, located


def rows_to_snapshot(
    table: TabularData,
) -> tuple[MenuSnapshot | None, list[SyncIssue], dict[str, int], bool]:
    """Строки → снимок. Возвращает (снимок или ``None`` при ошибках, проблемы, external_id → строка,
    есть ли колонка ``is_available``).

    Проверяет каждую ячейку, дубли ``external_id`` позиций (обе строки в сообщении), согласованность
    категории (одинаковые ``category_name``/``category_sort_key`` во всех её строках), лимиты строк;
    пустой файл — ``empty_snapshot``. Ошибки валидации Pydantic переводит в ``SyncIssue`` с номером строки.
    Проблемы упорядочены по строке (проблемы без строки — первыми).
    """
    layout, issues = parse_header(table.header, table.header_row)
    if layout is None:
        return None, issues, {}, False
    has_availability = IS_AVAILABLE in layout.index
    if len(table.rows) > MAX_DATA_ROWS:
        issues.append(SyncIssue(IssueCode.TOO_MANY_ROWS, f"больше {MAX_DATA_ROWS} строк данных"))
        return None, issues, {}, has_availability
    if not table.rows:
        issues.append(SyncIssue(IssueCode.EMPTY_SNAPSHOT, "в файле нет строк с позициями: пустое меню не применяется"))
        return None, issues, {}, has_availability

    builder = _SnapshotBuilder(layout, decimal_comma=table.decimal_comma)
    for row in table.rows:
        builder.add_row(row)
    snapshot, model_issues = builder.validate()
    issues = sorted([*issues, *builder.issues, *model_issues], key=lambda issue: issue.row or 0)
    if has_errors(issues):
        return None, issues, builder.item_rows, has_availability
    return snapshot, issues, builder.item_rows, has_availability
