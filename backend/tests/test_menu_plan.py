"""План применения снимка ``app.menu_sync.plan`` (story #62, ADR-8.3, ADR-8.4): без БД.

Каждая строка таблицы ADR-8.3, удаление тарифа, ``is_available=None``, mass-hide на границе
10 позиций / 30 % и ``allow_mass_hide``, счётчики, ``restored`` важнее ``updated``.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.menu_sync import plan as plan_module
from app.menu_sync.plan import (
    MASS_HIDE_MIN_ITEMS,
    MASS_HIDE_RATIO,
    CategoryWrite,
    CurrentCategory,
    CurrentItem,
    CurrentMenu,
    ItemWrite,
    MenuSyncPlan,
    is_mass_hide,
    plan_menu_sync,
)
from app.menu_sync.report import EntityCounts, IssueCode, PriceCounts, Severity
from app.menu_sync.snapshot import MenuSnapshot, resolve_currency

TENANT = uuid.UUID(int=1)
CAT_ID = uuid.UUID(int=100)
NEW_IDS = [uuid.UUID(int=10_000 + n) for n in range(50)]


@pytest.fixture(autouse=True)
def fixed_ids(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[uuid.UUID]]:
    """``new_id`` выдаёт предсказуемые id: план детерминирован."""
    counter = itertools.count()
    monkeypatch.setattr(plan_module, "new_id", lambda: NEW_IDS[next(counter)])
    yield NEW_IDS


def _iid(n: int) -> uuid.UUID:
    return uuid.UUID(int=1_000 + n)


def _category(external_id: str = "19", **overrides: Any) -> CurrentCategory:
    values: dict[str, Any] = {
        "id": CAT_ID,
        "external_id": external_id,
        "pos_name": "Isti yemekler",
        "sort_key": "19",
        "is_hidden": False,
    }
    values.update(overrides)
    return CurrentCategory(**values)


def _current_item(n: int, **overrides: Any) -> CurrentItem:
    values: dict[str, Any] = {
        "id": _iid(n),
        "external_id": str(n),
        "category_id": CAT_ID,
        "pos_name": f"Блюдо {n}",
        "currency": "AZN",
        "station": None,
        "sort_key": "",
        "is_available": True,
        "is_hidden": False,
        "prices": {"default": Decimal("8.00")},
    }
    values.update(overrides)
    return CurrentItem(**values)


def _menu(*items: CurrentItem, categories: list[CurrentCategory] | None = None) -> CurrentMenu:
    if categories is None:
        categories = [_category()]
    return CurrentMenu(
        tenant_id=TENANT,
        tenant_currency="AZN",
        categories={c.external_id: c for c in categories},
        items={i.external_id: i for i in items},
    )


def _snap_item(n: int, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "external_id": str(n),
        "category_external_id": "19",
        "name": f"Блюдо {n}",
        "prices": {"default": "8.00"},
    }
    item.update(overrides)
    return item


def _snapshot(*items: dict[str, Any], categories: list[dict[str, Any]] | None = None) -> MenuSnapshot:
    if categories is None:
        categories = [{"external_id": "19", "name": "Isti yemekler", "sort_key": "19"}]
    snapshot = MenuSnapshot.model_validate({"categories": categories, "items": list(items)})
    return resolve_currency(snapshot, "AZN")


# ---------------------------------------------------------------- строки таблицы ADR-8.3


def test_new_category_and_item_are_created(fixed_ids: list[uuid.UUID]) -> None:
    snapshot = _snapshot(
        _snap_item(
            1, category_external_id="20", prices={"default": "8.00", "vip": "10.00"}, station="Metbex", sort_key="5"
        ),
        categories=[{"external_id": "20", "name": "Şorbalar", "sort_key": "2"}],
    )
    plan = plan_menu_sync(_menu(categories=[]), snapshot)

    assert plan.category_writes == [CategoryWrite(id=fixed_ids[0], external_id="20", pos_name="Şorbalar", sort_key="2")]
    assert plan.item_writes == [
        ItemWrite(
            id=fixed_ids[1],
            external_id="1",
            category_id=fixed_ids[0],
            pos_name="Блюдо 1",
            currency="AZN",
            station="Metbex",
            sort_key="5",
            is_available=None,
            prices={"default": Decimal("8.00"), "vip": Decimal("10.00")},
        )
    ]
    assert plan.categories == EntityCounts(created=1)
    assert plan.items == EntityCounts(created=1)
    assert plan.prices == PriceCounts(created=2)
    assert plan.availability_changed == 0
    assert plan.present_category_ids == [fixed_ids[0]]
    assert plan.present_item_ids == [fixed_ids[1]]
    assert plan.issues == []


def test_unchanged_rows_are_not_written() -> None:
    plan = plan_menu_sync(_menu(_current_item(1)), _snapshot(_snap_item(1, is_available=True)))

    assert plan.category_writes == []
    assert plan.item_writes == []
    assert plan.delete_prices == []
    assert plan.categories == EntityCounts(unchanged=1)
    assert plan.items == EntityCounts(unchanged=1)
    assert plan.prices == PriceCounts()
    assert plan.present_category_ids == [CAT_ID]
    assert plan.present_item_ids == [_iid(1)]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name": "Новое имя"}, "pos_name"),
        ({"station": "Bar"}, "station"),
        ({"sort_key": "9"}, "sort_key"),
    ],
)
def test_changed_item_fields_are_updated(overrides: dict[str, Any], field: str) -> None:
    plan = plan_menu_sync(_menu(_current_item(1)), _snapshot(_snap_item(1, **overrides)))

    assert plan.items == EntityCounts(updated=1)
    assert len(plan.item_writes) == 1
    write = plan.item_writes[0]
    assert write.id == _iid(1)
    assert getattr(write, field) == next(iter(overrides.values()))


def test_currency_change_counts_as_update() -> None:
    """Позиция с устаревшей валютой получает валюту заведения из снимка."""
    plan = plan_menu_sync(_menu(_current_item(1, currency="USD")), _snapshot(_snap_item(1)))

    assert plan.items == EntityCounts(updated=1)
    assert plan.item_writes[0].currency == "AZN"


def test_item_moves_to_new_category(fixed_ids: list[uuid.UUID]) -> None:
    snapshot = _snapshot(
        _snap_item(1, category_external_id="20"),
        categories=[
            {"external_id": "19", "name": "Isti yemekler", "sort_key": "19"},
            {"external_id": "20", "name": "Şorbalar"},
        ],
    )
    plan = plan_menu_sync(_menu(_current_item(1)), snapshot)

    assert plan.categories == EntityCounts(created=1, unchanged=1)
    assert plan.items == EntityCounts(updated=1)
    assert plan.item_writes[0].category_id == fixed_ids[0]


@pytest.mark.parametrize(
    ("overrides", "counts"),
    [
        ({"name": "Новое имя"}, EntityCounts(updated=1)),
        ({"sort_key": "1"}, EntityCounts(updated=1)),
    ],
)
def test_changed_category_is_updated(overrides: dict[str, Any], counts: EntityCounts) -> None:
    category = {"external_id": "19", "name": "Isti yemekler", "sort_key": "19", **overrides}
    plan = plan_menu_sync(_menu(_current_item(1)), _snapshot(_snap_item(1), categories=[category]))

    assert plan.categories == counts
    assert plan.category_writes == [
        CategoryWrite(id=CAT_ID, external_id="19", pos_name=category["name"], sort_key=category["sort_key"])
    ]


def test_hidden_rows_back_in_snapshot_are_restored_even_if_changed() -> None:
    """``restored`` важнее ``updated``: вернулась и изменилась — «возвращена», запись с новыми полями."""
    current = _menu(
        _current_item(1, is_hidden=True, pos_name="Старое"),
        _current_item(2, is_hidden=True),
        categories=[_category(is_hidden=True, pos_name="Старая")],
    )
    plan = plan_menu_sync(current, _snapshot(_snap_item(1), _snap_item(2)))

    assert plan.categories == EntityCounts(restored=1)
    assert plan.items == EntityCounts(restored=2)
    assert [w.id for w in plan.item_writes] == [_iid(1), _iid(2)]
    assert plan.item_writes[0].pos_name == "Блюдо 1"
    assert plan.category_writes[0].pos_name == "Isti yemekler"


def test_visible_rows_missing_from_snapshot_are_hidden_and_prices_kept() -> None:
    old = _category("7", id=uuid.UUID(int=7))
    current = _menu(
        _current_item(1),
        _current_item(2, prices={"default": Decimal("3.00"), "vip": Decimal("4.00")}),
        categories=[_category(), old],
    )
    plan = plan_menu_sync(current, _snapshot(_snap_item(1)))

    assert plan.hide_item_ids == [_iid(2)]
    assert plan.hide_category_ids == [uuid.UUID(int=7)]
    assert plan.items == EntityCounts(hidden=1, unchanged=1)
    assert plan.categories == EntityCounts(hidden=1, unchanged=1)
    assert plan.delete_prices == []
    assert plan.prices == PriceCounts()
    assert _iid(2) not in plan.present_item_ids


def test_already_hidden_rows_missing_from_snapshot_are_not_counted() -> None:
    current = _menu(
        _current_item(1),
        _current_item(2, is_hidden=True),
        categories=[_category(), _category("7", id=uuid.UUID(int=7), is_hidden=True)],
    )
    plan = plan_menu_sync(current, _snapshot(_snap_item(1)))

    assert plan.hide_item_ids == []
    assert plan.hide_category_ids == []
    assert plan.items == EntityCounts(unchanged=1)
    assert plan.categories == EntityCounts(unchanged=1)


# ---------------------------------------------------------------- цены


def test_prices_created_updated_and_deleted() -> None:
    """Тариф ``vip`` пропал (``price_vip`` обнулили в кассе, ТЗ A.2) — удаляется; ``happy`` — новый."""
    current = _menu(_current_item(1, prices={"default": Decimal("8.00"), "vip": Decimal("10.00")}))
    snapshot = _snapshot(_snap_item(1, prices={"default": "9.00", "happy": "7.00"}))
    plan = plan_menu_sync(current, snapshot)

    assert plan.prices == PriceCounts(created=1, updated=1, deleted=1)
    assert plan.delete_prices == [(_iid(1), "vip")]
    assert plan.items == EntityCounts(updated=1)
    assert plan.item_writes[0].prices == {"default": Decimal("9.00"), "happy": Decimal("7.00")}


def test_same_price_with_other_scale_is_unchanged() -> None:
    plan = plan_menu_sync(_menu(_current_item(1)), _snapshot(_snap_item(1, prices={"default": "8"})))

    assert plan.items == EntityCounts(unchanged=1)
    assert plan.prices == PriceCounts()


def test_only_deleted_tier_makes_item_updated() -> None:
    current = _menu(_current_item(1, prices={"default": Decimal("8.00"), "vip": Decimal("10.00")}))
    plan = plan_menu_sync(current, _snapshot(_snap_item(1)))

    assert plan.items == EntityCounts(updated=1)
    assert plan.prices == PriceCounts(deleted=1)


# ---------------------------------------------------------------- наличие


def test_is_available_none_keeps_availability() -> None:
    plan = plan_menu_sync(_menu(_current_item(1, is_available=False)), _snapshot(_snap_item(1)))

    assert plan.items == EntityCounts(unchanged=1)
    assert plan.availability_changed == 0
    assert plan.item_writes == []


def test_is_available_change_is_written_and_counted() -> None:
    plan = plan_menu_sync(_menu(_current_item(1)), _snapshot(_snap_item(1, is_available=False)))

    assert plan.availability_changed == 1
    assert plan.items == EntityCounts(updated=1)
    assert plan.item_writes[0].is_available is False


def test_new_item_availability_is_not_counted_as_change() -> None:
    plan = plan_menu_sync(_menu(), _snapshot(_snap_item(1, is_available=False)))

    assert plan.availability_changed == 0
    assert plan.item_writes[0].is_available is False


def test_restored_item_with_availability_change() -> None:
    plan = plan_menu_sync(
        _menu(_current_item(1, is_hidden=True, is_available=False)), _snapshot(_snap_item(1, is_available=True))
    )

    assert plan.items == EntityCounts(restored=1)
    assert plan.availability_changed == 1


# ---------------------------------------------------------------- массовое скрытие


def _visible(count: int) -> list[CurrentItem]:
    return [_current_item(n) for n in range(1, count + 1)]


@pytest.mark.parametrize(
    ("visible", "kept", "rejected"),
    [
        (34, 24, False),  # 10 из 34 ≈ 29,4 % — меньше 30 %
        (33, 23, True),  # 10 из 33 ≈ 30,3 %
        (10, 1, False),  # 9 позиций — меньше MASS_HIDE_MIN_ITEMS, хотя это 90 %
        (40, 30, False),  # 10 из 40 = 25 %
        (100, 70, True),  # 30 из 100 = ровно 30 %
        (100, 71, False),  # 29 из 100 = 29 %
    ],
)
def test_mass_hide_boundary(visible: int, kept: int, rejected: bool) -> None:
    hidden = visible - kept
    snapshot = _snapshot(*[_snap_item(n) for n in range(1, kept + 1)])
    plan = plan_menu_sync(_menu(*_visible(visible)), snapshot)

    assert (plan.issues != []) is rejected
    if rejected:
        assert [issue.code for issue in plan.issues] == [IssueCode.MASS_HIDE]
        issue = plan.issues[0]
        assert issue.severity is Severity.ERROR
        assert issue.value == str(hidden)
        assert f"{hidden} из {visible}" in issue.message
        assert plan.items.hidden == hidden  # счётчики остаются для отчёта
        assert plan.hide_item_ids == []
        assert plan.item_writes == []
        assert plan.present_item_ids == []
        assert plan.present_category_ids == []
    else:
        assert len(plan.hide_item_ids) == hidden


def test_mass_hide_allowed() -> None:
    plan = plan_menu_sync(_menu(*_visible(20)), _snapshot(_snap_item(1)), allow_mass_hide=True)

    assert plan.issues == []
    assert len(plan.hide_item_ids) == 19


def test_mass_hide_ignores_already_hidden_items() -> None:
    """Уже скрытые позиции не считаются ни видимыми, ни скрываемыми."""
    items = [*_visible(5), *[_current_item(n, is_hidden=True) for n in range(100, 150)]]
    plan = plan_menu_sync(_menu(*items), _snapshot(_snap_item(1)))

    assert plan.issues == []
    assert len(plan.hide_item_ids) == 4


def test_mass_hide_clears_category_and_price_writes() -> None:
    items = [*_visible(10), _current_item(11, prices={"default": Decimal("1.00"), "vip": Decimal("2.00")})]
    # позиция 11 переезжает в новую категорию, старая категория пропадает, тариф vip — тоже
    snapshot = _snapshot(
        _snap_item(11, name="Новое", category_external_id="20"),
        categories=[{"external_id": "20", "name": "Новая"}],
    )
    plan = plan_menu_sync(_menu(*items), snapshot)

    assert [issue.code for issue in plan.issues] == [IssueCode.MASS_HIDE]
    assert plan.category_writes == []
    assert plan.hide_category_ids == []
    assert plan.delete_prices == []
    assert plan.prices.deleted == 1


@pytest.mark.parametrize(
    ("hidden", "visible", "expected"),
    [(10, 33, True), (10, 34, False), (9, 9, False), (10, 10, True), (0, 0, False)],
)
def test_is_mass_hide(hidden: int, visible: int, expected: bool) -> None:
    assert is_mass_hide(hidden, visible) is expected


def test_mass_hide_constants() -> None:
    """Решение пользователя (#8): отказ при ≥ 10 позициях и ≥ 30 % видимых."""
    assert MASS_HIDE_MIN_ITEMS == 10
    assert Decimal("0.30") == MASS_HIDE_RATIO


def test_empty_plan_defaults() -> None:
    plan = MenuSyncPlan()
    assert plan.issues == []
    assert plan.categories == EntityCounts()
