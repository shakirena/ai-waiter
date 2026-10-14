"""Снимок меню ``app.menu_sync.snapshot`` и отчёт ``app.menu_sync.report`` (story #61): без БД.

AC #61: снимок из трёх позиций (нет ``default``, валюта USD, ссылка на категорию вне снимка) даёт
ровно три ошибки с ``external_id``, полем и причиной на русском; корректный снимок того же размера
проходит без ошибок. Хеш снимка — #63.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.menu_sync.report import (
    MAX_ISSUE_COLUMN_CHARS,
    MAX_ISSUE_EXTERNAL_ID_CHARS,
    MAX_ISSUE_MESSAGE_CHARS,
    MAX_ISSUE_VALUE_CHARS,
    MAX_REPORTED_ISSUES,
    EntityCounts,
    IssueCode,
    MenuSyncReport,
    Severity,
    SyncIssue,
    escape_invisible,
    has_errors,
    issue_value,
    limit_issues,
    safe_text,
)
from app.menu_sync.snapshot import (
    EXTERNAL_ID_MAX,
    MAX_CATEGORIES,
    MAX_ITEMS,
    MAX_TIERS_PER_ITEM,
    MenuSnapshot,
    SnapshotCategory,
    SnapshotItem,
    check_snapshot,
    issues_from_validation_error,
    parse_snapshot,
    resolve_currency,
)
from app.models.enums import MenuSyncStatus

CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)


def _item(external_id: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "external_id": external_id,
        "category_external_id": "19",
        "name": f"Блюдо {external_id}",
        "prices": {"default": "8.00"},
    }
    item.update(overrides)
    return item


def _data(*items: dict[str, Any], categories: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if categories is None:
        categories = [{"external_id": "19", "name": "Isti yemekler", "sort_key": "19"}]
    return {"categories": categories, "items": list(items)}


def _valid_data() -> dict[str, Any]:
    return _data(
        _item("101", prices={"default": "8.00", "vip": "10.00"}, currency="AZN", station="Metbex"),
        _item("102", prices={"default": "5.5"}),
        _item("103", is_available=False, sort_key="17003"),
    )


def _single_issue(data: dict[str, Any]) -> SyncIssue:
    snapshot, issues = parse_snapshot(data, "AZN")
    assert snapshot is None
    assert len(issues) == 1, issues
    return issues[0]


# ---------------------------------------------------------------- AC #61


def test_ac61_three_errors_at_once() -> None:
    data = _data(
        _item("101", prices={"vip": "10.00"}),  # нет default
        _item("102", currency="USD"),  # чужая валюта
        _item("103", category_external_id="77"),  # категории нет в снимке
    )
    snapshot, issues = parse_snapshot(data, "AZN")

    assert snapshot is None
    assert len(issues) == 3
    assert all(issue.severity is Severity.ERROR for issue in issues)
    by_id = {issue.external_id: issue for issue in issues}
    assert set(by_id) == {"101", "102", "103"}
    assert (by_id["101"].code, by_id["101"].column) == (IssueCode.REQUIRED, "prices.default")
    assert (by_id["102"].code, by_id["102"].column) == (IssueCode.CURRENCY_MISMATCH, "currency")
    assert (by_id["103"].code, by_id["103"].column) == (IssueCode.UNKNOWN_CATEGORY, "category_external_id")
    assert by_id["102"].value == "USD"
    assert by_id["103"].value == "77"
    for issue in issues:
        assert CYRILLIC.search(issue.message), issue.message


def test_ac61_valid_snapshot_of_same_size_has_no_issues() -> None:
    snapshot, issues = parse_snapshot(_valid_data(), "AZN")

    assert issues == []
    assert snapshot is not None
    assert len(snapshot.items) == 3
    first = snapshot.items[0]
    assert first.prices == {"default": Decimal("8.00"), "vip": Decimal("10.00")}
    assert snapshot.items[1].prices["default"] == Decimal("5.50")
    assert first.currency == "AZN"
    assert snapshot.items[1].currency is None
    assert snapshot.items[1].is_available is None
    assert snapshot.items[2].is_available is False
    assert check_snapshot(snapshot, "AZN") == []


def test_snapshot_json_uses_money_strings() -> None:
    snapshot, _ = parse_snapshot(_valid_data(), "AZN")
    assert snapshot is not None
    dumped = snapshot.model_dump(mode="json")
    assert dumped["items"][1]["prices"] == {"default": "5.50"}
    assert dumped["items"][0]["prices"] == {"default": "8.00", "vip": "10.00"}


# ---------------------------------------------------------------- форма элементов


@pytest.mark.parametrize(
    ("mutate", "code", "column", "external_id"),
    [
        (lambda d: d["items"][0].pop("name"), IssueCode.REQUIRED, "name", "101"),
        (lambda d: d["items"][0].update(name="   "), IssueCode.REQUIRED, "name", "101"),
        (lambda d: d["items"][0].update(name="x" * 201), IssueCode.TOO_LONG, "name", "101"),
        (lambda d: d["items"][0].update(name="Dol\nma"), IssueCode.CONTROL_CHARS, "name", "101"),
        (lambda d: d["items"][0].update(station="Bar\tA"), IssueCode.CONTROL_CHARS, "station", "101"),
        (lambda d: d["items"][0].update(external_id="1\x7f"), IssueCode.CONTROL_CHARS, "external_id", "1\\x7f"),
        (lambda d: d["items"][0].update(external_id="9" * 65), IssueCode.TOO_LONG, "external_id", "9" * 63 + "…"),
        (lambda d: d["items"][0].update(external_id=157), IssueCode.INVALID_CELL_TYPE, "external_id", "157"),
        (lambda d: d["items"][0].update(currency="azn"), IssueCode.INVALID_CURRENCY, "currency", "101"),
        (lambda d: d["items"][0].update(is_available="maybe"), IssueCode.INVALID_BOOL, "is_available", "101"),
        (lambda d: d["items"][0].update(color="red"), IssueCode.UNKNOWN_COLUMN, "color", "101"),
        (lambda d: d["items"][0].update(prices={}), IssueCode.REQUIRED, "prices.default", "101"),
        (lambda d: d["items"][0].update(prices="8.00"), IssueCode.INVALID_CELL_TYPE, "prices", "101"),
        (lambda d: d["items"][0].update(prices={"default": 8.5}), IssueCode.INVALID_MONEY, "prices.default", "101"),
        (
            lambda d: d["items"][0].update(prices={"default": "8.505"}),
            IssueCode.TOO_MANY_DECIMALS,
            "prices.default",
            "101",
        ),
        (lambda d: d["items"][0].update(prices={"default": "-1"}), IssueCode.NEGATIVE_PRICE, "prices.default", "101"),
        (
            lambda d: d["items"][0].update(prices={"default": "123456789"}),
            IssueCode.PRICE_TOO_LARGE,
            "prices.default",
            "101",
        ),
        (
            lambda d: d["items"][0].update(prices={"default": "1", "VIP": "2"}),
            IssueCode.INVALID_TIER,
            "prices",
            "101",
        ),
        (
            lambda d: d["items"][0].update(
                prices={"default": "1", **{f"t{i}": "1" for i in range(MAX_TIERS_PER_ITEM)}}
            ),
            IssueCode.TOO_MANY_COLUMNS,
            "prices",
            "101",
        ),
        (lambda d: d["items"][0].update(prices={"default": True}), IssueCode.INVALID_MONEY, "prices.default", "101"),
        (lambda d: d["categories"][0].pop("name"), IssueCode.REQUIRED, "name", "19"),
        (lambda d: d["categories"][0].update(extra="x"), IssueCode.UNKNOWN_COLUMN, "extra", "19"),
        (lambda d: d.update(version=2), IssueCode.UNKNOWN_COLUMN, "version", None),
        (lambda d: d.pop("items"), IssueCode.REQUIRED, "items", None),
        (lambda d: d.update(items={"a": 1}), IssueCode.INVALID_CELL_TYPE, "items", None),
        (lambda d: d["items"].__setitem__(0, "101"), IssueCode.INVALID_CELL_TYPE, None, None),
    ],
)
def test_shape_errors(mutate: Any, code: IssueCode, column: str | None, external_id: str | None) -> None:
    data = _data(_item("101"))
    mutate(data)
    issue = _single_issue(data)
    assert issue.code is code
    assert issue.column == column
    assert issue.external_id == external_id
    assert issue.severity is Severity.ERROR
    assert issue.row is None
    assert CYRILLIC.search(issue.message), issue.message


def test_category_error_is_marked_in_message() -> None:
    data = _data(_item("101"), categories=[{"external_id": "19", "name": ""}])
    issue = _single_issue(data)
    assert issue.message.startswith("категория: ")
    assert (issue.code, issue.column, issue.external_id) == (IssueCode.REQUIRED, "name", "19")


def test_invalid_tier_lists_all_bad_names() -> None:
    issue = _single_issue(_data(_item("101", prices={"default": "1", "VIP": "2", "1x": "3"})))
    assert issue.value == "1x, VIP"
    assert "VIP" not in issue.message  # входные данные — только в value (security review #61)


def test_float_price_value_is_shown() -> None:
    issue = _single_issue(_data(_item("101", prices={"default": 8.5})))
    assert issue.value == "8.5"


def test_strings_are_stripped_and_empty_station_is_none() -> None:
    snapshot, issues = parse_snapshot(
        _data(_item(" 101 ", name="  Dolma ", station="   ", category_external_id=" 19 ")), "AZN"
    )
    assert issues == []
    assert snapshot is not None
    item = snapshot.items[0]
    assert (item.external_id, item.name, item.station, item.category_external_id) == ("101", "Dolma", None, "19")


def test_models_are_frozen() -> None:
    category = SnapshotCategory(external_id="1", name="A")
    with pytest.raises(ValidationError):
        category.name = "B"  # type: ignore[misc]
    assert category.sort_key == ""


def test_limits_categories_and_items() -> None:
    too_many_items = _data(*[_item(str(i)) for i in range(MAX_ITEMS + 1)])
    issue = _single_issue(too_many_items)
    assert (issue.code, issue.column) == (IssueCode.TOO_MANY_ROWS, "items")
    assert str(MAX_ITEMS) in issue.message

    categories = [{"external_id": str(i), "name": "c"} for i in range(MAX_CATEGORIES + 1)]
    issue = _single_issue(_data(_item("1", category_external_id="0"), categories=categories))
    assert (issue.code, issue.column) == (IssueCode.TOO_MANY_ROWS, "categories")


def test_non_mapping_data() -> None:
    snapshot, issues = parse_snapshot([], "AZN")  # type: ignore[arg-type]
    assert snapshot is None
    assert [(i.code, i.column, i.external_id) for i in issues] == [(IssueCode.INVALID_CELL_TYPE, None, None)]


# ---------------------------------------------------------------- межэлементные проверки


def test_empty_snapshot_is_rejected() -> None:
    issue = _single_issue(_data())
    assert (issue.code, issue.column) == (IssueCode.EMPTY_SNAPSHOT, "items")


def test_duplicate_external_ids() -> None:
    data = _data(
        _item("101"),
        _item("101"),
        _item("19"),  # тот же id, что у категории, — другое пространство имён
        categories=[{"external_id": "19", "name": "A"}, {"external_id": "19", "name": "B"}],
    )
    snapshot, issues = parse_snapshot(data, "AZN")
    assert snapshot is None
    assert [(i.code, i.external_id, i.message.startswith("категория")) for i in issues] == [
        (IssueCode.DUPLICATE_EXTERNAL_ID, "19", True),
        (IssueCode.DUPLICATE_EXTERNAL_ID, "101", False),
    ]


def test_zero_price_is_warning_and_snapshot_is_returned() -> None:
    snapshot, issues = parse_snapshot(_data(_item("101", prices={"default": "0", "vip": "0.00"})), "AZN")
    assert snapshot is not None
    assert [(i.code, i.severity, i.column, i.value) for i in issues] == [
        (IssueCode.ZERO_PRICE, Severity.WARNING, "prices.default", "0.00"),
        (IssueCode.ZERO_PRICE, Severity.WARNING, "prices.vip", "0.00"),
    ]


def test_matching_currency_is_accepted() -> None:
    snapshot, issues = parse_snapshot(_data(_item("101", currency="USD")), "USD")
    assert snapshot is not None
    assert issues == []


def test_check_snapshot_on_model_built_in_code() -> None:
    snapshot = MenuSnapshot(
        categories=[SnapshotCategory(external_id="1", name="A")],
        items=[
            SnapshotItem(external_id="a", category_external_id="1", name="X", prices={"default": Decimal("1")}),
            SnapshotItem(external_id="b", category_external_id="2", name="Y", prices={"default": "2"}, currency="EUR"),
        ],
    )
    codes = [i.code for i in check_snapshot(snapshot, "AZN")]
    assert codes == [IssueCode.UNKNOWN_CATEGORY, IssueCode.CURRENCY_MISMATCH]


def test_reference_to_invalid_category_is_not_unknown() -> None:
    """Категория с ошибкой формы уже в отчёте: ссылка на неё — не ``unknown_category``."""
    data = _data(_item("101"), categories=[{"external_id": "19", "name": "x" * 300}])
    snapshot, issues = parse_snapshot(data, "AZN")
    assert snapshot is None
    assert [i.code for i in issues] == [IssueCode.TOO_LONG]


def test_shape_error_does_not_hide_cross_errors_of_other_items() -> None:
    data = _data(
        _item("101", name=""),
        _item("102", currency="EUR"),
        _item("102", currency="EUR"),
        _item("103", prices={"default": "0"}),
    )
    _, issues = parse_snapshot(data, "AZN")
    assert [(i.code, i.external_id) for i in issues] == [
        (IssueCode.REQUIRED, "101"),
        (IssueCode.CURRENCY_MISMATCH, "102"),
        (IssueCode.DUPLICATE_EXTERNAL_ID, "102"),
        (IssueCode.CURRENCY_MISMATCH, "102"),
        (IssueCode.ZERO_PRICE, "103"),
    ]


def test_all_items_invalid_is_not_reported_as_empty() -> None:
    _, issues = parse_snapshot(_data(_item("101", name="")), "AZN")
    assert [i.code for i in issues] == [IssueCode.REQUIRED]


@pytest.mark.parametrize(
    "data",
    [
        {"categories": "x", "items": [_item("1", currency="USD")]},
        {"categories": [], "items": [_item(str(i)) for i in range(MAX_ITEMS + 1)]},
    ],
)
def test_cross_checks_skipped_for_broken_structure(data: dict[str, Any]) -> None:
    _, issues = parse_snapshot(data, "AZN")
    assert IssueCode.CURRENCY_MISMATCH not in {i.code for i in issues}
    assert IssueCode.UNKNOWN_CATEGORY not in {i.code for i in issues}


def test_issues_from_validation_error_with_odd_raw_data() -> None:
    """``external_id`` берётся из сырых данных только если он строка или целое."""
    raw = _data(_item("101", name=""), _item("x", name=""))
    raw["items"][1]["external_id"] = ["x"]
    with pytest.raises(ValidationError) as info:
        MenuSnapshot.model_validate(raw)
    ids = [i.external_id for i in issues_from_validation_error(info.value, raw)]
    assert ids == ["101", None, None]  # ["x"] → ошибка типа поля и ошибка name без id
    # Данные без нужных ключей (например, уже изменённые вызывающим) — без падения.
    assert {i.external_id for i in issues_from_validation_error(info.value, {"items": "nope"})} == {None}
    assert {i.external_id for i in issues_from_validation_error(info.value, {"items": []})} == {None}


def test_unmapped_pydantic_error_gets_generic_reason() -> None:
    exc = ValidationError.from_exception_data(
        "MenuSnapshot", [{"type": "int_parsing", "loc": ("items", 0, "station"), "input": "abc"}]
    )
    (issue,) = issues_from_validation_error(exc, _data(_item("101")))
    assert (issue.code, issue.message, issue.column, issue.external_id, issue.value) == (
        IssueCode.INVALID_CELL_TYPE,
        "недопустимое значение",
        "station",
        "101",
        "abc",
    )
    # Сырые данные не словарь — ``external_id`` неизвестен, но ошибка не теряется.
    (issue,) = issues_from_validation_error(exc, "not a mapping")  # type: ignore[arg-type]
    assert issue.external_id is None


def test_invalid_category_with_non_string_id() -> None:
    """Категория с id-числом — ошибка формы; позиция со ссылкой на «19» тогда — ``unknown_category``."""
    data = _data(_item("101"), categories=[{"external_id": 19, "name": "A"}])
    _, issues = parse_snapshot(data, "AZN")
    assert [(i.code, i.external_id) for i in issues] == [
        (IssueCode.INVALID_CELL_TYPE, "19"),
        (IssueCode.UNKNOWN_CATEGORY, "101"),
    ]


# ---------------------------------------------------------------- resolve_currency


def test_resolve_currency_fills_only_missing() -> None:
    snapshot, _ = parse_snapshot(_valid_data(), "AZN")
    assert snapshot is not None
    resolved = resolve_currency(snapshot, "AZN")
    assert [item.currency for item in resolved.items] == ["AZN", "AZN", "AZN"]
    assert [item.currency for item in snapshot.items] == ["AZN", None, None]  # исходный не изменён
    assert resolved.items[0] is snapshot.items[0]
    assert resolved.categories == snapshot.categories
    assert check_snapshot(resolved, "AZN") == []


def test_parse_snapshot_does_not_mutate_input() -> None:
    data = _valid_data()
    before = copy.deepcopy(data)
    parse_snapshot(data, "AZN")
    assert data == before


# ---------------------------------------------------------------- отчёт


def test_issue_value_formatting() -> None:
    assert issue_value(None) is None
    assert issue_value({"a": 1}) is None
    assert issue_value([1]) is None
    assert issue_value(object()) is None
    assert issue_value(True) == "true"
    assert issue_value(False) == "false"
    assert issue_value(Decimal("8.50")) == "8.50"
    assert issue_value(7) == "7"
    assert issue_value("a\x00b\x1f") == "a\\x00b\\x1f"
    long_value = issue_value("я" * 100)
    assert long_value is not None
    assert len(long_value) == MAX_ISSUE_VALUE_CHARS
    assert long_value.endswith("…")


def test_sync_issue_truncates_value_and_to_dict_skips_none() -> None:
    issue = SyncIssue(IssueCode.TOO_LONG, "длинно", value="x" * 200, external_id="1")
    assert issue.value is not None
    assert len(issue.value) == MAX_ISSUE_VALUE_CHARS
    assert issue.to_dict() == {
        "code": "too_long",
        "severity": "error",
        "message": "длинно",
        "external_id": "1",
        "value": issue.value,
    }
    full = SyncIssue(IssueCode.ZERO_PRICE, "ноль", Severity.WARNING, row=3, column="price_default", value="0")
    assert full.to_dict() == {
        "code": "zero_price",
        "severity": "warning",
        "message": "ноль",
        "row": 3,
        "column": "price_default",
        "value": "0",
    }


def test_limit_issues_orders_and_truncates() -> None:
    warning = SyncIssue(IssueCode.ZERO_PRICE, "w", Severity.WARNING, row=1)
    late = SyncIssue(IssueCode.REQUIRED, "e", row=9)
    early = SyncIssue(IssueCode.REQUIRED, "e", row=2)
    file_level = SyncIssue(IssueCode.ENCODING, "f")
    kept, dropped = limit_issues([warning, late, early, file_level])
    assert kept == [file_level, early, late, warning]
    assert dropped == 0

    many = [SyncIssue(IssueCode.REQUIRED, "e", row=i) for i in range(MAX_REPORTED_ISSUES + 5, 0, -1)]
    kept, dropped = limit_issues(many)
    assert len(kept) == MAX_REPORTED_ISSUES
    assert dropped == 5
    assert kept[0].row == 1


def test_has_errors() -> None:
    assert not has_errors([])
    assert not has_errors([SyncIssue(IssueCode.ZERO_PRICE, "w", Severity.WARNING)])
    assert has_errors([SyncIssue(IssueCode.ZERO_PRICE, "w", Severity.WARNING), SyncIssue(IssueCode.REQUIRED, "e")])


def test_menu_sync_report_dicts() -> None:
    report = MenuSyncReport(status=MenuSyncStatus.REJECTED, dry_run=True)
    assert not report.has_errors
    report.items = EntityCounts(created=2, hidden=1)
    report.issues.append(SyncIssue(IssueCode.MASS_HIDE, "много"))
    report.issues_truncated = 3
    assert report.has_errors
    counts = report.counts_dict()
    assert counts["items"] == {"created": 2, "updated": 0, "hidden": 1, "restored": 0, "unchanged": 0}
    assert counts["prices"] == {"created": 0, "updated": 0, "deleted": 0}
    assert counts["availability_changed"] == 0
    assert report.to_dict() == {
        "status": "rejected",
        "dry_run": True,
        "snapshot_hash": None,
        "run_id": None,
        "counts": counts,
        "issues": [{"code": "mass_hide", "severity": "error", "message": "много"}],
        "issues_truncated": 3,
    }


def test_menu_sync_report_run_id_is_string() -> None:
    import uuid

    run_id = uuid.uuid4()
    report = MenuSyncReport(status=MenuSyncStatus.APPLIED, dry_run=False, snapshot_hash="a" * 64, run_id=run_id)
    assert report.to_dict()["run_id"] == str(run_id)


# ---------------------------------------------------------------- security review #61: текст проблем

ESC = chr(0x1B)
INVISIBLE = {"Cc", "Cf", "Zl", "Zp"}


def _has_invisible(text: str) -> bool:
    return any(unicodedata.category(ch) in INVISIBLE for ch in text)


def _assert_safe(issue: SyncIssue) -> None:
    """Ни одно текстовое поле проблемы не несёт невидимых символов и не длиннее лимита."""
    assert not _has_invisible(issue.message)
    assert len(issue.message) <= MAX_ISSUE_MESSAGE_CHARS
    if issue.column is not None:
        assert not _has_invisible(issue.column)
        assert len(issue.column) <= MAX_ISSUE_COLUMN_CHARS
    if issue.external_id is not None:
        assert not _has_invisible(issue.external_id)
        assert len(issue.external_id) <= MAX_ISSUE_EXTERNAL_ID_CHARS
    if issue.value is not None:
        assert not _has_invisible(issue.value)
        assert len(issue.value) <= MAX_ISSUE_VALUE_CHARS


def test_external_id_limit_matches_snapshot_limit() -> None:
    """Допустимый external_id (до 64 символов) в отчёте не обрезается."""
    assert MAX_ISSUE_EXTERNAL_ID_CHARS == EXTERNAL_ID_MAX
    issue = SyncIssue(IssueCode.REQUIRED, "x", external_id="9" * EXTERNAL_ID_MAX)
    assert issue.external_id == "9" * EXTERNAL_ID_MAX


def test_sync_issue_truncates_huge_external_id() -> None:
    issue = SyncIssue(IssueCode.TOO_LONG, "x", external_id="1" * 100_000)
    assert issue.external_id is not None
    assert len(issue.external_id) == MAX_ISSUE_EXTERNAL_ID_CHARS
    assert issue.external_id.endswith("…")


def test_sync_issue_escapes_terminal_sequence_in_external_id() -> None:
    issue = SyncIssue(IssueCode.REQUIRED, "x", external_id=ESC + "[2J")
    assert issue.external_id == "\\x1b[2J"


def test_sync_issue_sanitizes_message_and_column() -> None:
    issue = SyncIssue(IssueCode.UNKNOWN_COLUMN, "m" * 1000 + ESC, column=ESC + "c" * 1000)
    _assert_safe(issue)
    assert issue.column is not None
    assert issue.column.startswith("\\x1b")
    assert issue.message.endswith("…")


def test_parse_snapshot_huge_external_id_is_truncated_in_report() -> None:
    issue = _single_issue(_data(_item("1" * 100_000, name="A")))
    assert (issue.code, issue.column) == (IssueCode.TOO_LONG, "external_id")
    _assert_safe(issue)
    assert issue.external_id == "1" * (MAX_ISSUE_EXTERNAL_ID_CHARS - 1) + "…"


def test_parse_snapshot_external_id_with_escape_sequence() -> None:
    issue = _single_issue(_data(_item(ESC + "[2J", name="A")))
    assert issue.code is IssueCode.CONTROL_CHARS
    assert issue.external_id == "\\x1b[2J"
    assert issue.value == "\\x1b[2J"


def test_parse_snapshot_long_tier_names_with_escape_are_not_in_message() -> None:
    names = [f"{ESC}[31m{'x' * 1000}{i}" for i in range(MAX_TIERS_PER_ITEM)]
    issue = _single_issue(_data(_item("101", prices=dict.fromkeys(names, "1.00"))))
    assert (issue.code, issue.column, issue.external_id) == (IssueCode.INVALID_TIER, "prices", "101")
    _assert_safe(issue)
    assert "x" * 10 not in issue.message  # имена тарифов — только в value
    assert issue.value is not None
    assert issue.value.startswith("\\x1b[31m")


def test_parse_snapshot_unknown_key_with_escape_is_sanitized_in_column() -> None:
    issue = _single_issue(_data(_item("101", **{ESC + "]0;title" + "k" * 500: "x"})))
    assert issue.code is IssueCode.UNKNOWN_COLUMN
    _assert_safe(issue)
    assert issue.column is not None
    assert issue.column.startswith("\\x1b]0;title")


def test_all_issue_dicts_are_safe_for_malicious_snapshot() -> None:
    evil = ESC + "[2J" + chr(0x202E) + "z" * 5000
    data = _data(
        _item(evil, name=evil, prices={evil: evil}, currency=evil, station=evil, sort_key=evil, **{evil: 1}),
        _item("ok", category_external_id=evil),
        categories=[{"external_id": evil, "name": evil, "sort_key": evil}],
    )
    _, issues = parse_snapshot(data, "AZN")
    assert issues
    for issue in issues:
        _assert_safe(issue)


@pytest.mark.parametrize(
    "code_point",
    [0x1B, 0x85, 0x9F, 0x2028, 0x2029, 0x202A, 0x202E, 0x2066, 0x2069, 0x200B, 0x200C, 0x200D, 0xFEFF, 0xE0001],
)
def test_invisible_characters_are_rejected(code_point: int) -> None:
    issue = _single_issue(_data(_item("101", name=f"Dol{chr(code_point)}ma")))
    assert (issue.code, issue.column, issue.external_id) == (IssueCode.CONTROL_CHARS, "name", "101")
    _assert_safe(issue)


@pytest.mark.parametrize(
    "name",
    ["Plov ə ğ ş ı ö ü ç Ş İ", "Борщ «домашний» — 300 г", "Pizza 🍕", "Çay & şirniyyat (2 nəfər)"],
)
def test_visible_text_is_accepted(name: str) -> None:
    snapshot, issues = parse_snapshot(_data(_item("101", name=name)), "AZN")
    assert issues == []
    assert snapshot is not None
    assert snapshot.items[0].name == name


@pytest.mark.parametrize(
    ("code_point", "escaped"),
    [(0x1B, "\\x1b"), (0x85, "\\x85"), (0x202E, "\\u202e"), (0xFEFF, "\\ufeff"), (0xE0001, "\\U000e0001")],
)
def test_escape_invisible(code_point: int, escaped: str) -> None:
    assert escape_invisible(f"a{chr(code_point)}b") == f"a{escaped}b"
    assert escape_invisible("Ünvan ə") == "Ünvan ə"


def test_safe_text_limits_after_escaping() -> None:
    text = safe_text(ESC * 100, 10)
    assert len(text) == 10
    assert text == "\\x1b\\x1b\\…"
    assert safe_text("short", 10) == "short"
