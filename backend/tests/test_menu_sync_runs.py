"""Хеш снимка и ``source_ref`` журнала без БД (story #63, INT-1, ADR-8.5).

Хеш не зависит от порядка категорий, позиций и тарифов и от записи цены (``8.5``/``8.50``);
меняется от цены, наличия, ``null``/значения и валюты. Журнал хранит только имя файла.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from app.menu_sync.service import SOURCE_REF_MAX, journal_source_ref
from app.menu_sync.snapshot import MenuSnapshot, resolve_currency, snapshot_hash
from app.models.enums import MenuSyncSource
from app.models.menu_sync import SNAPSHOT_HASH_PATTERN


def _item(external_id: str, category: str = "19", **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "external_id": external_id,
        "category_external_id": category,
        "name": f"Блюдо {external_id}",
        "prices": {"default": "8.00", "vip": "10.00"},
    }
    item.update(overrides)
    return item


CATEGORIES = [
    {"external_id": "19", "name": "Isti yemekler", "sort_key": "19"},
    {"external_id": "20", "name": "Salatlar", "sort_key": "20"},
]
ITEMS = [_item("157", station="Metbex", is_available=True), _item("158", "20"), _item("159")]


def _hash(categories: list[dict[str, Any]] | None = None, items: list[dict[str, Any]] | None = None) -> str:
    snapshot = MenuSnapshot.model_validate(
        {"categories": CATEGORIES if categories is None else categories, "items": ITEMS if items is None else items}
    )
    return snapshot_hash(snapshot)


BASE = _hash()


def test_hash_is_sha256_hex_matching_db_check() -> None:
    assert re.fullmatch(SNAPSHOT_HASH_PATTERN, BASE)
    assert len(BASE) == hashlib.sha256().digest_size * 2


def test_hash_is_stable_between_calls() -> None:
    assert _hash() == BASE


def test_hash_does_not_depend_on_order_of_items_categories_and_tiers() -> None:
    reordered_items = [
        {**ITEMS[2], "prices": {"vip": "10.00", "default": "8.00"}},
        ITEMS[0],
        {**ITEMS[1], "prices": {"vip": "10.00", "default": "8.00"}},
    ]
    assert _hash(list(reversed(CATEGORIES)), reordered_items) == BASE


def test_hash_does_not_depend_on_money_notation() -> None:
    items = [ITEMS[0], ITEMS[1], _item("159", prices={"default": "8", "vip": "10.0"})]
    assert _hash(items=items) == BASE


@pytest.mark.parametrize(
    ("index", "change"),
    [
        (2, {"prices": {"default": "8.01", "vip": "10.00"}}),  # цена
        (2, {"prices": {"default": "8.00"}}),  # тариф пропал
        (2, {"is_available": False}),  # наличие
        (2, {"is_available": True}),  # null → значение
        (0, {"is_available": None}),  # значение → null
        (0, {"station": None}),
        (2, {"name": "Другое блюдо"}),
        (2, {"sort_key": "5"}),
        (2, {"category_external_id": "20"}),
        (2, {"currency": "AZN"}),  # валюта задана явно (до resolve_currency)
    ],
)
def test_hash_changes_with_data(index: int, change: dict[str, Any]) -> None:
    items = [dict(item) for item in ITEMS]
    items[index] = {**items[index], **change}
    assert _hash(items=items) != BASE


def test_hash_changes_with_categories_and_item_set() -> None:
    assert _hash(categories=[CATEGORIES[0], {**CATEGORIES[1], "name": "Salat"}]) != BASE
    assert _hash(items=ITEMS[:2]) != BASE


def test_hash_after_resolve_currency_equals_explicit_currency() -> None:
    """``currency: null`` и явная валюта заведения после ``resolve_currency`` дают один хеш."""
    implicit = MenuSnapshot.model_validate({"categories": CATEGORIES, "items": ITEMS})
    explicit = MenuSnapshot.model_validate(
        {"categories": CATEGORIES, "items": [{**item, "currency": "AZN"} for item in ITEMS]}
    )
    assert snapshot_hash(resolve_currency(implicit, "AZN")) == snapshot_hash(explicit)
    assert snapshot_hash(resolve_currency(implicit, "AZN")) != snapshot_hash(implicit)


def test_hash_with_duplicate_ids_does_not_depend_on_order() -> None:
    """Снимок с повтором ``external_id`` отвергается ``check_snapshot``, но хеш всё равно детерминирован."""
    first, second = _item("157", name="A"), _item("157", name="B")
    assert _hash(items=[first, second]) == _hash(items=[second, first])


@pytest.mark.parametrize(
    ("source", "value", "expected"),
    [
        (MenuSyncSource.FILE, "menu.csv", "menu.csv"),
        (MenuSyncSource.FILE, "local-data/export/menu.csv", "menu.csv"),
        (MenuSyncSource.FILE, "C:\\Users\\admin\\Desktop\\menu.xlsx", "menu.xlsx"),
        (MenuSyncSource.FILE, "  ../menu 1.csv  ", "menu 1.csv"),
        (MenuSyncSource.FILE, "export/", "export"),
        (MenuSyncSource.FILE, "/", None),
        (MenuSyncSource.FILE, "   ", None),
        (MenuSyncSource.FILE, None, None),
        (MenuSyncSource.FILE, "menu\x1b[31m.csv", "menu\\x1b[31m.csv"),
        (MenuSyncSource.CONNECTOR, "yii2/1.4.0", "yii2/1.4.0"),
        (MenuSyncSource.CONNECTOR, "", None),
    ],
)
def test_journal_source_ref_keeps_only_file_name(source: MenuSyncSource, value: str | None, expected: str) -> None:
    assert journal_source_ref(source, value) == expected


def test_journal_source_ref_is_truncated_to_db_limit() -> None:
    value = journal_source_ref(MenuSyncSource.FILE, "a" * 1000 + ".csv")
    assert value is not None
    assert len(value) == SOURCE_REF_MAX
    assert value.endswith("…")
