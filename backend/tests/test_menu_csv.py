"""Файл меню CSV → снимок (story #64, ADR-8.2): ``app.menu_sync.files``, без БД.

AC #64: CSV в UTF-8 с BOM, разделитель ``;``, цены с запятой; строка 4 — цена ``abc``, строка 7
повторяет ``external_id`` строки 3 → ошибки «строка 4, ``price_default``» и «строка 7, ``external_id``:
повтор (строка 3)», снимка нет; исправленный файл даёт ``Decimal("4.50")``.

Все данные синтетические.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

from app.menu_sync.files import (
    MAX_FILE_BYTES,
    FileFormat,
    ParsedMenuFile,
    detect_format,
    locate_issues,
    parse_menu_bytes,
    read_menu_file,
)
from app.menu_sync.files.csv_reader import detect_delimiter, read_csv_table
from app.menu_sync.files.format import (
    MAX_CELL_CHARS,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    CellError,
    SheetRow,
    TabularData,
    cell_to_bool,
    cell_to_external_id,
    cell_to_money,
    cell_to_text,
    file_column,
    parse_header,
    rows_to_snapshot,
)
from app.menu_sync.report import MAX_REPORTED_ISSUES, IssueCode, Severity, SyncIssue
from app.menu_sync.snapshot import MAX_CATEGORIES

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "menu"
VALID_CSV = FIXTURES / "menu_valid.csv"

HEADER = "category_external_id,category_name,external_id,name,price_default"
HEADER_SC = HEADER.replace(",", ";")


def csv_bytes(*lines: str, bom: bool = False) -> bytes:
    text = "\r\n".join(lines) + "\r\n"
    return text.encode("utf-8-sig" if bom else "utf-8")


def parse(*lines: str, bom: bool = False) -> ParsedMenuFile:
    return parse_menu_bytes(csv_bytes(*lines, bom=bom), "menu.csv")


def codes(result: ParsedMenuFile) -> list[IssueCode]:
    return [issue.code for issue in result.issues]


def only_issue(result: ParsedMenuFile) -> SyncIssue:
    assert result.snapshot is None
    assert len(result.issues) == 1, [issue.to_dict() for issue in result.issues]
    return result.issues[0]


# ---------------------------------------------------------------- AC #64

AC_LINES = (
    HEADER_SC,  # 1
    "10;Salatlar;001;Çoban salatı;4,50",  # 2
    "10;Salatlar;002;Paytaxt salatı;6",  # 3
    "10;Salatlar;003;Göyərti;abc",  # 4
    "20;İçkilər;201;Ayran;1,5",  # 5
    "20;İçkilər;202;Çay;3,00",  # 6
    "20;İçkilər;002;Limonad;2,80",  # 7
)


def test_ac64_errors_with_rows_and_no_snapshot() -> None:
    result = parse(*AC_LINES, bom=True)

    assert result.snapshot is None
    assert result.file_format is FileFormat.CSV
    assert result.rows_total == 6
    assert [(i.row, i.column, i.code) for i in result.issues] == [
        (4, "price_default", IssueCode.INVALID_MONEY),
        (7, "external_id", IssueCode.DUPLICATE_EXTERNAL_ID),
    ]
    price, duplicate = result.issues
    assert price.value == "abc"
    assert price.external_id == "003"
    assert "повтор" in duplicate.message
    assert "строка 3" in duplicate.message
    assert result.item_rows["002"] == 3


def test_ac64_fixed_file_gives_snapshot_with_decimal_comma() -> None:
    lines = list(AC_LINES)
    lines[3] = "10;Salatlar;003;Göyərti;3,20"
    lines[6] = "20;İçkilər;204;Limonad;2,80"
    result = parse(*lines, bom=True)

    assert result.issues == []
    assert result.snapshot is not None
    prices = {item.external_id: item.prices["default"] for item in result.snapshot.items}
    assert prices["001"] == Decimal("4.50")
    assert prices["201"] == Decimal("1.50")
    assert result.item_rows == {"001": 2, "002": 3, "003": 4, "201": 5, "202": 6, "204": 7}


# ---------------------------------------------------------------- синтетический пример


def test_valid_fixture_parses_completely() -> None:
    result = read_menu_file(VALID_CSV)

    assert result.issues == []
    assert result.issues_truncated == 0
    assert result.has_errors is False
    assert result.file_format is FileFormat.CSV
    assert result.rows_total == 9
    assert result.has_availability is True
    snapshot = result.snapshot
    assert snapshot is not None
    assert [c.external_id for c in snapshot.categories] == ["10", "20", "30"]
    assert snapshot.categories[1].name == "İsti yeməklər"
    items = {item.external_id: item for item in snapshot.items}
    assert len(items) == 9
    assert items["007"].prices == {"default": Decimal("4.50"), "vip": Decimal("5.50")}
    assert items["008"].prices["default"] == Decimal("6.00")
    assert items["008"].currency is None
    assert items["009"].name == "Qarışıq göyərti, limon"
    assert items["009"].prices == {"default": Decimal("3.20")}
    assert items["009"].is_available is False
    assert items["103"].is_available is True
    assert items["201"].is_available is True
    assert items["203"].is_available is False
    assert items["102"].station == "Manqal"
    assert items["102"].sort_key == "20002"
    assert result.item_rows["007"] == 2
    assert result.item_rows["203"] == 10


def test_comma_and_semicolon_files_give_same_snapshot() -> None:
    comma = parse(HEADER + ",price_vip", '1,A,7,"Dolma, böyük",8.50,10')
    semicolon = parse(HEADER_SC + ";price_vip", "1;A;7;Dolma, böyük;8,50;10")
    assert comma.snapshot is not None
    assert comma.snapshot == semicolon.snapshot


# ---------------------------------------------------------------- кодировка и разделитель


def test_cp1251_is_encoding_error() -> None:
    data = (HEADER + "\r\n1,Салаты,1,Оливье,4.50\r\n").encode("cp1251")
    issue = only_issue(parse_menu_bytes(data, "menu.csv"))
    assert issue.code is IssueCode.ENCODING
    assert "CSV UTF-8" in issue.message


def test_utf16_is_encoding_error() -> None:
    data = (HEADER + "\r\n1,A,1,x,4.50\r\n").encode("utf-16")
    assert codes(parse_menu_bytes(data, "menu.csv")) == [IssueCode.ENCODING]


def test_bom_is_optional() -> None:
    assert parse(HEADER, "1,A,1,x,4.50").snapshot is not None
    assert parse(HEADER, "1,A,1,x,4.50", bom=True).snapshot is not None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (HEADER, ","),
        (HEADER_SC, ";"),
        ("a;b;c\r\n", ";"),  # нет обязательных колонок: больше колонок при «;»
        ("a,b;c\r\n", ","),  # равенство — запятая
        ("", ","),
        ('"oops\r\n', ","),  # ошибка разбора первой записи
        ('\r\n\r\n"category_external_id";"name";"external_id"', ";"),
    ],
)
def test_detect_delimiter(text: str, expected: str) -> None:
    assert detect_delimiter(text) == expected


def test_decimal_comma_not_allowed_with_comma_delimiter() -> None:
    issue = only_issue(parse(HEADER, '1,A,1,x,"4,50"'))
    assert (issue.code, issue.row, issue.column) == (IssueCode.INVALID_MONEY, 2, "price_default")


def test_thousands_separator_rejected_with_semicolon() -> None:
    issue = only_issue(parse(HEADER_SC, "1;A;1;x;1.000,50"))
    assert issue.code is IssueCode.INVALID_MONEY
    assert "8,50" in issue.message


# ---------------------------------------------------------------- кавычки, переносы, номера строк


def test_quotes_and_newlines_keep_physical_row_numbers() -> None:
    result = parse(
        HEADER + ",#comment",
        '1,A,1,"Dolma ""ev""",4.50,"многострочный\r\nкомментарий"',  # строки 2–3
        "",  # 4 — пустая
        " , , , , , ",  # 5 — из пробелов
        "1,A,2,y,abc,",  # 6
    )
    issue = only_issue(result)
    assert (issue.row, issue.column) == (6, "price_default")
    assert result.rows_total == 2


def test_quoted_name_with_newline_is_control_chars_error() -> None:
    issue = only_issue(parse(HEADER, '1,A,1,"две\nстроки",4.50'))
    assert (issue.code, issue.row, issue.column) == (IssueCode.CONTROL_CHARS, 2, "name")
    assert issue.value == "две\\x0aстроки"


def test_blank_lines_before_header_shift_header_row() -> None:
    result = parse("", "", HEADER, "1,A,1,x,abc")
    assert only_issue(result).row == 4


def test_unclosed_quote_is_format_error() -> None:
    issue = only_issue(parse(HEADER, '1,A,1,"x,4.50'))
    assert issue.code is IssueCode.UNSUPPORTED_FORMAT
    assert issue.row == 2


def test_empty_file_and_header_only() -> None:
    assert codes(parse_menu_bytes(b"", "menu.csv")) == [IssueCode.EMPTY_SNAPSHOT]
    assert codes(parse_menu_bytes("﻿\r\n \r\n".encode(), "menu.csv")) == [IssueCode.EMPTY_SNAPSHOT]
    result = parse(HEADER)
    assert codes(result) == [IssueCode.EMPTY_SNAPSHOT]
    assert result.rows_total == 0


def test_control_char_nul_in_cell() -> None:
    issue = only_issue(parse(HEADER, "1,A,1,x\x00y,4.50"))
    assert issue.code is IssueCode.CONTROL_CHARS
    assert issue.value == "x\\x00y"


# ---------------------------------------------------------------- заголовок


def test_header_names_case_and_spaces_any_order() -> None:
    result = parse(" Name ,PRICE_DEFAULT,External_ID,Category_Name,CATEGORY_EXTERNAL_ID", "x,4.50,1,A,1")
    assert result.snapshot is not None
    assert result.snapshot.items[0].name == "x"


def test_comment_columns_are_ignored() -> None:
    result = parse(HEADER + ",#note,# old price", "1,A,1,x,4.50,любой текст,9.99")
    assert result.issues == []
    assert result.snapshot is not None


@pytest.mark.parametrize(
    ("header", "code", "column"),
    [
        (HEADER + ",is_avalable", IssueCode.UNKNOWN_COLUMN, "is_avalable"),
        (HEADER + ",price_VIP", IssueCode.INVALID_TIER, "price_VIP"),
        (HEADER + ",price_", IssueCode.INVALID_TIER, "price_"),
        (HEADER + ",name", IssueCode.DUPLICATE_COLUMN, "name"),
        (HEADER + ",Price_Default", IssueCode.DUPLICATE_COLUMN, "Price_Default"),
        (HEADER + ",price_vip,price_vip", IssueCode.DUPLICATE_COLUMN, "price_vip"),
        ("category_external_id,category_name,external_id,price_default", IssueCode.MISSING_COLUMN, "name"),
        ("category_external_id,category_name,external_id,name", IssueCode.MISSING_COLUMN, "price_default"),
    ],
)
def test_header_errors(header: str, code: IssueCode, column: str) -> None:
    issue = only_issue(parse(header, "1,A,1,x,4.50,1,2"))
    assert (issue.code, issue.row, issue.column) == (code, 1, column)


def test_all_header_errors_collected() -> None:
    result = parse("name,name,foo,price_X")
    assert sorted(codes(result)) == sorted(
        [
            IssueCode.DUPLICATE_COLUMN,
            IssueCode.UNKNOWN_COLUMN,
            IssueCode.INVALID_TIER,
            IssueCode.MISSING_COLUMN,
            IssueCode.MISSING_COLUMN,
            IssueCode.MISSING_COLUMN,
            IssueCode.MISSING_COLUMN,
        ]
    )


def test_too_many_tier_columns() -> None:
    tiers = ",".join(f"price_t{n}" for n in range(10))
    issue = only_issue(parse(f"{HEADER},{tiers}", "1,A,1,x,1" + ",1" * 10))
    assert issue.code is IssueCode.TOO_MANY_COLUMNS


def test_too_many_columns_in_csv() -> None:
    wide = HEADER + "," + ",".join(f"#c{n}" for n in range(MAX_COLUMNS))
    issue = only_issue(parse(wide, "1,A,1,x,4.50"))
    assert (issue.code, issue.row) == (IssueCode.TOO_MANY_COLUMNS, 1)
    issue = only_issue(parse(HEADER, "1,A,1,x,4.50" + "," * MAX_COLUMNS))
    assert (issue.code, issue.row) == (IssueCode.TOO_MANY_COLUMNS, 2)


def test_parse_header_too_many_columns_directly() -> None:
    layout, issues = parse_header(tuple(f"#c{n}" for n in range(MAX_COLUMNS + 1)), 1)
    assert layout is None
    assert [i.code for i in issues] == [IssueCode.TOO_MANY_COLUMNS]


def test_unnamed_column_allowed_only_when_empty() -> None:
    assert parse(HEADER + ",,", "1,A,1,x,4.50,,").snapshot is not None
    issue = only_issue(parse(HEADER + ",", "1,A,1,x,4.50,lost"))
    assert (issue.code, issue.row, issue.column, issue.value) == (IssueCode.UNKNOWN_COLUMN, 2, "колонка 6", "lost")
    issue = only_issue(parse(HEADER, "1,A,1,x,4.50,beyond"))
    assert (issue.code, issue.column) == (IssueCode.UNKNOWN_COLUMN, "колонка 6")


def test_short_row_missing_cells_are_empty() -> None:
    result = parse(HEADER + ",station", "1,A,1,x,4.50")
    assert result.snapshot is not None
    assert result.snapshot.items[0].station is None
    issue = only_issue(parse(HEADER, "1,A,1,x"))
    assert (issue.code, issue.column) == (IssueCode.REQUIRED, "price_default")


# ---------------------------------------------------------------- ячейки и строки


def test_leading_zeros_kept_in_external_id() -> None:
    result = parse(HEADER, "010,A,007,x,4.50", "010,A,7,y,4.50")
    assert result.snapshot is not None
    assert [i.external_id for i in result.snapshot.items] == ["007", "7"]
    assert result.snapshot.categories[0].external_id == "010"


@pytest.mark.parametrize(
    ("cell", "code"),
    [
        ("abc", IssueCode.INVALID_MONEY),
        ("-1", IssueCode.NEGATIVE_PRICE),
        ("8.505", IssueCode.TOO_MANY_DECIMALS),
        ("100000000", IssueCode.PRICE_TOO_LARGE),
        ("1e3", IssueCode.INVALID_MONEY),
        ("8 50", IssueCode.INVALID_MONEY),
        ("", IssueCode.REQUIRED),
    ],
)
def test_price_cell_errors(cell: str, code: IssueCode) -> None:
    issue = only_issue(parse(HEADER, f"1,A,1,x,{cell}"))
    assert (issue.code, issue.row, issue.column, issue.external_id) == (code, 2, "price_default", "1")


def test_optional_tier_empty_means_no_tier_and_errors_use_tier_column() -> None:
    result = parse(HEADER + ",price_vip", "1,A,1,x,4.50,", "1,A,2,y,4.50,5")
    assert result.snapshot is not None
    assert [sorted(i.prices) for i in result.snapshot.items] == [["default"], ["default", "vip"]]
    issue = only_issue(parse(HEADER + ",price_vip", "1,A,1,x,4.50,5.555"))
    assert (issue.code, issue.column) == (IssueCode.TOO_MANY_DECIMALS, "price_vip")


@pytest.mark.parametrize(
    ("line", "column", "code"),
    [
        (",A,1,x,4.50", "category_external_id", IssueCode.REQUIRED),
        ("1,,1,x,4.50", "category_name", IssueCode.REQUIRED),
        ("1,A,,x,4.50", "external_id", IssueCode.REQUIRED),
        ("1,A,1,  ,4.50", "name", IssueCode.REQUIRED),
        ("1,A,1," + "n" * 201 + ",4.50", "name", IssueCode.TOO_LONG),
        ("1,A," + "9" * 65 + ",x,4.50", "external_id", IssueCode.TOO_LONG),
        ("1,A,1," + "n" * (MAX_CELL_CHARS + 1) + ",4.50", "name", IssueCode.TOO_LONG),
    ],
)
def test_required_and_length_errors(line: str, column: str, code: IssueCode) -> None:
    issue = only_issue(parse(HEADER, line))
    assert (issue.code, issue.row, issue.column) == (code, 2, column)


def test_cell_over_limit_value_truncated_in_report() -> None:
    issue = only_issue(parse(HEADER, "1,A,1," + "n" * (MAX_CELL_CHARS + 1) + ",4.50"))
    assert issue.message == f"длиннее {MAX_CELL_CHARS} символов"
    assert issue.value is not None
    assert len(issue.value) <= 60


def test_optional_columns_validated_by_snapshot_model() -> None:
    header = HEADER + ",currency,station,sort_key,category_sort_key"
    result = parse(header, "1,A,1,x,4.50,azn," + "s" * 101 + "," + "k" * 65 + ",1")
    assert result.snapshot is None
    assert {(i.code, i.column, i.row) for i in result.issues} == {
        (IssueCode.INVALID_CURRENCY, "currency", 2),
        (IssueCode.TOO_LONG, "station", 2),
        (IssueCode.TOO_LONG, "sort_key", 2),
    }


def test_category_model_errors_point_to_first_row_and_category_column() -> None:
    long_name = "c" * 201
    result = parse(HEADER, "1,A,1,x,4.50", f"2,{long_name},2,y,4.50", f"2,{long_name},3,z,4.50")
    issue = only_issue(result)
    assert (issue.code, issue.row, issue.column) == (IssueCode.TOO_LONG, 3, "category_name")
    assert issue.message.startswith("категория: ")


def test_optional_columns_values() -> None:
    header = HEADER + ",currency,station,sort_key,category_sort_key"
    result = parse(header, "1,A,1,x,4.50,AZN,  ,,5", "1,A,2,y,4.50,,Bar,s2,5")
    snapshot = result.snapshot
    assert snapshot is not None
    first, second = snapshot.items
    assert (first.currency, first.station, first.sort_key) == ("AZN", None, "")
    assert (second.currency, second.station, second.sort_key) == (None, "Bar", "s2")
    assert snapshot.categories[0].sort_key == "5"


def test_duplicate_external_id_reports_both_rows_and_all_repeats() -> None:
    result = parse(HEADER, "1,A,5,x,1", "1,A,6,y,1", "1,A,5,z,1", "1,A, 5 ,w,1")
    assert [(i.row, i.code) for i in result.issues] == [
        (4, IssueCode.DUPLICATE_EXTERNAL_ID),
        (5, IssueCode.DUPLICATE_EXTERNAL_ID),
    ]
    assert all("строка 2" in i.message for i in result.issues)


def test_category_conflict_name_and_sort_key() -> None:
    header = HEADER + ",category_sort_key"
    result = parse(header, "1,Salatlar,1,x,1,10", "1,Salatlar,2,y,1,10", "1,Salads,3,z,1,20")
    assert [(i.row, i.code, i.column, i.value) for i in result.issues] == [
        (4, IssueCode.CATEGORY_CONFLICT, "category_name", "Salads"),
        (4, IssueCode.CATEGORY_CONFLICT, "category_sort_key", "20"),
    ]
    assert "строки 2" in result.issues[0].message
    assert result.snapshot is None


def test_category_without_sort_key_column_defaults_to_empty() -> None:
    result = parse(HEADER, "1,A,1,x,1")
    assert result.snapshot is not None
    assert result.snapshot.categories[0].sort_key == ""


def test_all_row_errors_collected_in_row_order() -> None:
    result = parse(HEADER, "1,A,1,x,abc", "1,A,2,,1", "1,A,3,z,-1")
    assert [(i.row, i.code) for i in result.issues] == [
        (2, IssueCode.INVALID_MONEY),
        (3, IssueCode.REQUIRED),
        (4, IssueCode.NEGATIVE_PRICE),
    ]


def test_valid_rows_are_still_validated_when_others_fail() -> None:
    result = parse(HEADER + ",currency", "1,A,1,x,abc,AZN", "1,A,2,y,1,usd")
    assert [(i.row, i.code) for i in result.issues] == [(2, IssueCode.INVALID_MONEY), (3, IssueCode.INVALID_CURRENCY)]


# ---------------------------------------------------------------- is_available


def test_without_is_available_column_availability_untouched() -> None:
    result = parse(HEADER, "1,A,1,x,1")
    assert result.has_availability is False
    assert result.snapshot is not None
    assert result.snapshot.items[0].is_available is None


@pytest.mark.parametrize(
    ("cell", "expected"),
    [("1", True), ("TRUE", True), ("Yes", True), ("0", False), ("false", False), (" NO ", False)],
)
def test_is_available_values(cell: str, expected: bool) -> None:
    result = parse(HEADER + ",is_available", f"1,A,1,x,1,{cell}")
    assert result.has_availability is True
    assert result.snapshot is not None
    assert result.snapshot.items[0].is_available is expected


@pytest.mark.parametrize(("cell", "code"), [("", IssueCode.REQUIRED), ("да", IssueCode.INVALID_BOOL)])
def test_is_available_column_present_value_required(cell: str, code: IssueCode) -> None:
    issue = only_issue(parse(HEADER + ",is_available", f"1,A,1,x,1,{cell}"))
    assert (issue.code, issue.column) == (code, "is_available")


# ---------------------------------------------------------------- лимиты строк и категорий


def test_max_data_rows_allowed_and_one_more_rejected() -> None:
    rows = [f"1,A,{n},x,1" for n in range(MAX_DATA_ROWS)]
    result = parse(HEADER, *rows)
    assert result.snapshot is not None
    assert result.rows_total == MAX_DATA_ROWS
    issue = only_issue(parse(HEADER, *rows, "1,A,extra,x,1"))
    assert (issue.code, issue.row) == (IssueCode.TOO_MANY_ROWS, MAX_DATA_ROWS + 2)


def test_rows_to_snapshot_checks_row_limit_itself() -> None:
    table = TabularData(
        header=tuple(HEADER.split(",")),
        header_row=1,
        rows=[SheetRow(n + 2, ("1", "A", str(n), "x", "1")) for n in range(MAX_DATA_ROWS + 1)],
    )
    snapshot, issues, item_rows, has_availability = rows_to_snapshot(table)
    assert snapshot is None
    assert [i.code for i in issues] == [IssueCode.TOO_MANY_ROWS]
    assert (item_rows, has_availability) == ({}, False)


def test_too_many_categories() -> None:
    rows = [f"{n},C{n},{n},x,1" for n in range(MAX_CATEGORIES + 1)]
    issue = only_issue(parse(HEADER, *rows))
    assert issue.code is IssueCode.TOO_MANY_ROWS
    assert issue.row is None


def test_issue_list_is_limited() -> None:
    rows = [f"1,A,{n},x,abc" for n in range(MAX_REPORTED_ISSUES + 5)]
    result = parse(HEADER, *rows)
    assert result.snapshot is None
    assert len(result.issues) == MAX_REPORTED_ISSUES
    assert result.issues_truncated == 5
    assert result.issues[0].row == 2


# ---------------------------------------------------------------- значения ячеек (общие для CSV и XLSX)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (None, None),
        ("  x  ", "x"),
        ("   ", None),
        (7, "7"),
        (7.0, "7"),
        (7.25, "7.25"),
        (Decimal("7.0"), "7"),
        (Decimal("7.50"), "7.50"),
    ],
)
def test_cell_to_text(cell: object, expected: str | None) -> None:
    assert cell_to_text(cell) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "cell",
    [True, datetime(2026, 1, 1, tzinfo=None), date(2026, 1, 1), time(12, 0), float("nan"), Decimal("NaN")],  # noqa: DTZ001
)
def test_cell_to_text_rejects(cell: object) -> None:
    with pytest.raises(CellError) as exc:
        cell_to_text(cell)  # type: ignore[arg-type]
    assert exc.value.args[0] is IssueCode.INVALID_CELL_TYPE


@pytest.mark.parametrize(
    ("cell", "expected"),
    [(None, None), ("007", "007"), (" 7 ", "7"), (7, "7"), (7.0, "7"), (Decimal("12"), "12"), ("", None)],
)
def test_cell_to_external_id(cell: object, expected: str | None) -> None:
    assert cell_to_external_id(cell) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("cell", [7.5, Decimal("7.5"), Decimal("Infinity"), False, date(2026, 1, 1)])
def test_cell_to_external_id_rejects(cell: object) -> None:
    with pytest.raises(CellError) as exc:
        cell_to_external_id(cell)  # type: ignore[arg-type]
    assert exc.value.code is IssueCode.INVALID_ID


@pytest.mark.parametrize(
    ("cell", "decimal_comma", "expected"),
    [
        (None, False, None),
        ("  ", False, None),
        ("8", False, Decimal("8.00")),
        ("8.5", False, Decimal("8.50")),
        ("8,5", True, Decimal("8.50")),
        (8, False, Decimal("8.00")),
        (Decimal("8.1"), False, Decimal("8.10")),
        (8.1, False, Decimal("8.10")),
        (0.1 + 0.2, False, Decimal("0.30")),  # шум двоичной дроби
        (0.0, False, Decimal("0.00")),
    ],
)
def test_cell_to_money(cell: object, decimal_comma: bool, expected: Decimal | None) -> None:
    assert cell_to_money(cell, decimal_comma=decimal_comma) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("cell", "decimal_comma", "code"),
    [
        ("8,5", False, IssueCode.INVALID_MONEY),
        ("8,5,0", True, IssueCode.INVALID_MONEY),
        (8.125, False, IssueCode.TOO_MANY_DECIMALS),
        (float("inf"), False, IssueCode.INVALID_MONEY),
        (True, False, IssueCode.INVALID_MONEY),
        (-2, False, IssueCode.NEGATIVE_PRICE),
        (datetime(2026, 1, 1), False, IssueCode.INVALID_CELL_TYPE),  # noqa: DTZ001
    ],
)
def test_cell_to_money_rejects(cell: object, decimal_comma: bool, code: IssueCode) -> None:
    with pytest.raises(CellError) as exc:
        cell_to_money(cell, decimal_comma=decimal_comma)  # type: ignore[arg-type]
    assert exc.value.code is code


@pytest.mark.parametrize(
    ("cell", "expected"),
    [(None, None), ("", None), (True, True), (False, False), (1, True), (0, False), (1.0, True), ("YES", True)],
)
def test_cell_to_bool(cell: object, expected: bool | None) -> None:
    assert cell_to_bool(cell) is expected  # type: ignore[arg-type]


@pytest.mark.parametrize(("cell", "code"), [("2", IssueCode.INVALID_BOOL), (time(1, 0), IssueCode.INVALID_CELL_TYPE)])
def test_cell_to_bool_rejects(cell: object, code: IssueCode) -> None:
    with pytest.raises(CellError) as exc:
        cell_to_bool(cell)  # type: ignore[arg-type]
    assert exc.value.code is code


def test_typed_cells_from_xlsx_like_table() -> None:
    """Типизированные ячейки (как отдаст XLSX, #65) проходят тот же путь, что и текст CSV."""
    table = TabularData(
        header=("category_external_id", "category_name", "external_id", "name", "price_default", "is_available"),
        header_row=1,
        rows=[
            SheetRow(2, (10, "Salatlar", 7.0, "x", 8.1, True)),
            SheetRow(3, (10, "Salatlar", "007", "y", Decimal("4.5"), 0)),
            SheetRow(5, (10, "Salatlar", 9, "z", date(2026, 1, 1), 1)),
        ],
    )
    snapshot, issues, item_rows, has_availability = rows_to_snapshot(table)
    assert snapshot is None
    assert [(i.row, i.code, i.column) for i in issues] == [(5, IssueCode.INVALID_CELL_TYPE, "price_default")]
    assert item_rows == {"7": 2, "007": 3, "9": 5}
    assert has_availability is True
    table.rows.pop()
    snapshot, issues, _, _ = rows_to_snapshot(table)
    assert issues == []
    assert snapshot is not None
    assert [(i.external_id, i.prices["default"], i.is_available) for i in snapshot.items] == [
        ("7", Decimal("8.10"), True),
        ("007", Decimal("4.50"), False),
    ]


def test_header_error_from_rows_to_snapshot() -> None:
    table = TabularData(header=("name",), header_row=3, rows=[])
    snapshot, issues, item_rows, has_availability = rows_to_snapshot(table)
    assert snapshot is None
    assert {i.row for i in issues} == {3}
    assert (item_rows, has_availability) == ({}, False)


def test_zero_price_is_not_reported_by_file_parser() -> None:
    """Предупреждение ``zero_price`` и валюту заведения проверяет ``check_snapshot`` при применении."""
    result = parse(HEADER, "1,A,1,x,0")
    assert result.issues == []
    assert result.snapshot is not None


# ---------------------------------------------------------------- формат файла и чтение с диска


@pytest.mark.parametrize(
    ("filename", "head", "expected"),
    [
        ("menu.csv", b"cate", FileFormat.CSV),
        ("MENU.CSV", b"", FileFormat.CSV),
        ("menu.xlsx", b"PK\x03\x04", FileFormat.XLSX),
        ("Menu.XLSX", b"PK\x03\x04rest", FileFormat.XLSX),
        ("menu.csv", b"PK\x03\x04", None),
        ("menu.xlsx", b"cate", None),
        ("menu.xls", b"\xd0\xcf\x11\xe0", None),
        ("menu.xlsm", b"PK\x03\x04", None),
        ("menu.txt", b"cate", None),
        ("menu", b"cate", None),
    ],
)
def test_detect_format(filename: str, head: bytes, expected: FileFormat | None) -> None:
    assert detect_format(filename, head) is expected


def test_unsupported_format() -> None:
    result = parse_menu_bytes(b"category_external_id", "menu.xls")
    assert result.file_format is None
    assert codes(result) == [IssueCode.UNSUPPORTED_FORMAT]
    assert ".xlsx" in result.issues[0].message


def test_xlsx_not_supported_yet() -> None:
    result = parse_menu_bytes(b"PK\x03\x04data", "menu.xlsx", sheet="Menu")
    assert result.file_format is FileFormat.XLSX
    assert codes(result) == [IssueCode.UNSUPPORTED_FORMAT]


def test_parse_bytes_over_limit() -> None:
    result = parse_menu_bytes(b"x" * (MAX_FILE_BYTES + 1), "menu.csv")
    assert result.file_format is FileFormat.CSV
    assert codes(result) == [IssueCode.FILE_TOO_LARGE]
    assert "5 МБ" in result.issues[0].message


def test_read_menu_file_checks_size_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    big = tmp_path / "big.csv"
    with big.open("wb") as stream:
        stream.truncate(MAX_FILE_BYTES + 1)  # разреженный файл: размер есть, содержимого нет

    def fail_open(*args: object, **kwargs: object) -> None:
        raise AssertionError("файл сверх лимита не должен открываться")

    monkeypatch.setattr(Path, "open", fail_open)
    result = read_menu_file(big)
    assert codes(result) == [IssueCode.FILE_TOO_LARGE]
    assert result.snapshot is None


def test_read_menu_file_exactly_at_limit_is_read(tmp_path: Path) -> None:
    path = tmp_path / "menu.csv"
    body = csv_bytes(HEADER, "1,A,1,x,1")
    padding = MAX_FILE_BYTES - len(body)
    blank_line = b" " * 999 + b"\n"  # строки из пробелов пропускаются
    lines, rest = divmod(padding, len(blank_line))
    path.write_bytes(body + blank_line * lines + b"\n" * rest)
    assert path.stat().st_size == MAX_FILE_BYTES
    result = read_menu_file(path)
    assert result.snapshot is not None


def test_read_menu_file_grown_after_stat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Файл, выросший между ``stat`` и чтением, всё равно не читается сверх лимита."""
    path = tmp_path / "menu.csv"
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 10))
    real_stat = Path.stat

    def small_stat(self: Path, **kwargs: object) -> object:
        result = real_stat(self)

        class _Stat:
            st_size = 10
            st_mode = result.st_mode

        return _Stat()

    monkeypatch.setattr(Path, "stat", small_stat)
    assert codes(read_menu_file(path)) == [IssueCode.FILE_TOO_LARGE]


def test_read_menu_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_menu_file(tmp_path / "nope.csv")


def test_read_csv_table_returns_typed_table() -> None:
    table, issues = read_csv_table(csv_bytes(HEADER_SC, "1;A;1;x;4,50"))
    assert issues == []
    assert table is not None
    assert table.decimal_comma is True
    assert table.header_row == 1
    assert table.rows == [SheetRow(2, ("1", "A", "1", "x", "4,50"))]


# ---------------------------------------------------------------- проблемы применения → строки файла


def test_file_column_mapping() -> None:
    assert file_column(None) is None
    assert file_column("prices.vip") == "price_vip"
    assert file_column("currency") == "currency"
    assert file_column("name", category=True) == "category_name"
    assert file_column("external_id", category=True) == "category_external_id"
    assert file_column("categories", category=True) == "categories"


def test_locate_issues_adds_rows_by_external_id() -> None:
    issues = [
        SyncIssue(IssueCode.CURRENCY_MISMATCH, "валюта", column="currency", external_id="102"),
        SyncIssue(IssueCode.ZERO_PRICE, "0", severity=Severity.WARNING, column="prices.vip", external_id="007"),
        SyncIssue(IssueCode.MASS_HIDE, "много"),
        SyncIssue(IssueCode.ZERO_PRICE, "0", column="prices.default", external_id="missing"),
        SyncIssue(IssueCode.INVALID_MONEY, "x", row=9, column="price_default", external_id="007"),
    ]
    located = locate_issues(issues, {"102": 6, "007": 2})
    assert [(i.row, i.column) for i in located] == [
        (6, "currency"),
        (2, "price_vip"),
        (None, None),
        (None, "prices.default"),
        (9, "price_default"),
    ]
    assert located[1].severity is Severity.WARNING
