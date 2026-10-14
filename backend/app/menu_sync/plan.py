"""Чистое сравнение текущего меню заведения со снимком (ADR-8.3, ADR-8.4). Без БД и ввода-вывода.

``service`` загружает ``CurrentMenu`` одним-двумя SELECT, вызывает ``plan_menu_sync`` и
выполняет план пакетными INSERT … ON CONFLICT / UPDATE / DELETE. Пробный прогон
(``--dry-run``) — тот же план без записи, поэтому его счётчики совпадают с реальным применением.

Правила (ADR-8.3):

- категории и позиции сопоставляются по ``external_id`` в границах заведения;
- нет в БД → создать; есть → обновить изменившиеся поля (``pos_name``, ``sort_key``,
  ``category_id``, ``station``, ``currency``); была скрыта → ``is_hidden = false`` («возвращена»);
- есть в БД, нет в снимке, не скрыта → ``is_hidden = true``; уже скрытая не считается;
- цены: тарифы снимка — upsert, тарифы позиции, которых нет в снимке, — удалить; у скрываемых
  позиций цены не трогаются;
- ``is_available``: ``None`` в снимке — не менять (новая позиция — ``true``);
- ``menu_item_meta`` и ``menu_item_allergens`` не трогаются никогда (FR-16);
- ``synced_at`` ставится всем строкам, которые есть в применённом снимке.

Story #62. Ошибка уровня плана (→ снимок отклоняется целиком, ADR-8.4) одна: массовое скрытие
(``MASS_HIDE_MIN_ITEMS`` и ``MASS_HIDE_RATIO`` от видимых позиций) без ``allow_mass_hide``.
Валюта, дубли и ссылки проверены раньше — ``snapshot.check_snapshot`` (#61).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from app.db.ids import new_id
from app.menu_sync.report import EntityCounts, IssueCode, PriceCounts, SyncIssue
from app.menu_sync.snapshot import MenuSnapshot

# Отказ, если снимок скрывает не меньше MASS_HIDE_MIN_ITEMS позиций и не меньше MASS_HIDE_RATIO
# от видимых сейчас: защита от «не того файла» или пустого листа. Обход — allow_mass_hide.
MASS_HIDE_MIN_ITEMS: Final[int] = 10
MASS_HIDE_RATIO: Final[Decimal] = Decimal("0.30")


@dataclass(frozen=True, slots=True)
class CurrentCategory:
    id: uuid.UUID
    external_id: str
    pos_name: str
    sort_key: str
    is_hidden: bool


@dataclass(frozen=True, slots=True)
class CurrentItem:
    id: uuid.UUID
    external_id: str
    category_id: uuid.UUID
    pos_name: str
    currency: str
    station: str | None
    sort_key: str
    is_available: bool
    is_hidden: bool
    prices: dict[str, Decimal]  # тариф → цена


@dataclass(frozen=True, slots=True)
class CurrentMenu:
    """Синхронизируемая часть меню заведения (без ``menu_item_meta``)."""

    tenant_id: uuid.UUID
    tenant_currency: str
    categories: dict[str, CurrentCategory]  # по external_id
    items: dict[str, CurrentItem]  # по external_id


@dataclass(frozen=True, slots=True)
class CategoryWrite:
    """Категория для upsert по ``(tenant_id, external_id)``; ``id`` новой — из ``new_id()``."""

    id: uuid.UUID
    external_id: str
    pos_name: str
    sort_key: str


@dataclass(frozen=True, slots=True)
class ItemWrite:
    """Позиция для upsert; ``is_available=None`` — колонку не менять (у новой — ``true``)."""

    id: uuid.UUID
    external_id: str
    category_id: uuid.UUID
    pos_name: str
    currency: str
    station: str | None
    sort_key: str
    is_available: bool | None
    prices: dict[str, Decimal]


@dataclass(slots=True)
class MenuSyncPlan:
    """Что записать. Пустые списки при ошибках: план с ``issues``-ошибками не применяется."""

    category_writes: list[CategoryWrite] = field(default_factory=list)  # новые, изменённые, возвращённые
    item_writes: list[ItemWrite] = field(default_factory=list)
    hide_category_ids: list[uuid.UUID] = field(default_factory=list)
    hide_item_ids: list[uuid.UUID] = field(default_factory=list)
    delete_prices: list[tuple[uuid.UUID, str]] = field(default_factory=list)  # (menu_item_id, price_tier)
    present_category_ids: list[uuid.UUID] = field(default_factory=list)  # для synced_at
    present_item_ids: list[uuid.UUID] = field(default_factory=list)
    categories: EntityCounts = field(default_factory=EntityCounts)
    items: EntityCounts = field(default_factory=EntityCounts)
    prices: PriceCounts = field(default_factory=PriceCounts)
    availability_changed: int = 0
    issues: list[SyncIssue] = field(default_factory=list)


def plan_menu_sync(current: CurrentMenu, snapshot: MenuSnapshot, *, allow_mass_hide: bool = False) -> MenuSyncPlan:
    """Построить план применения снимка к текущему меню (правила — в docstring модуля).

    Снимок уже прошёл ``check_snapshot`` без ошибок и ``resolve_currency``. Детерминирован при
    фиксированном ``new_id`` (тесты подменяют генератор).

    Подсчёт: позиция или категория попадает ровно в одно поле ``EntityCounts`` (``restored`` важнее
    ``updated``); изменение только наличия или только цен — тоже ``updated``. ``availability_changed`` —
    существующие позиции, у которых снимок меняет ``is_available`` (у новых не считается).
    ``present_*_ids`` — все строки снимка, включая новые. При ошибке ``mass_hide`` счётчики остаются
    (для сообщения и проверки), а списки записи очищаются.
    """
    plan = MenuSyncPlan()
    category_ids = _plan_categories(plan, current, snapshot)
    _plan_items(plan, current, snapshot, category_ids)

    visible = sum(1 for item in current.items.values() if not item.is_hidden)
    hidden = len(plan.hide_item_ids)
    if not allow_mass_hide and is_mass_hide(hidden, visible):
        plan.issues.append(
            SyncIssue(
                IssueCode.MASS_HIDE,
                f"снимок скрыл бы {hidden} из {visible} видимых позиций; если это верно, повторите "
                "с разрешением массового скрытия (--allow-mass-hide)",
                column="items",
                value=str(hidden),
            )
        )
        _clear_writes(plan)
    return plan


def is_mass_hide(hidden: int, visible: int) -> bool:
    """Скрывается не меньше ``MASS_HIDE_MIN_ITEMS`` позиций и не меньше ``MASS_HIDE_RATIO`` от видимых."""
    return hidden >= MASS_HIDE_MIN_ITEMS and Decimal(hidden) >= MASS_HIDE_RATIO * visible


def _plan_categories(plan: MenuSyncPlan, current: CurrentMenu, snapshot: MenuSnapshot) -> dict[str, uuid.UUID]:
    """Категории снимка → записи и счётчики; возвращает ``external_id`` → ``id`` (новым — из ``new_id``)."""
    ids: dict[str, uuid.UUID] = {}
    for category in snapshot.categories:
        existing = current.categories.get(category.external_id)
        if existing is None:
            category_id = new_id()
            plan.categories.created += 1
            write = True
        else:
            category_id = existing.id
            changed = existing.pos_name != category.name or existing.sort_key != category.sort_key
            write = existing.is_hidden or changed
            if existing.is_hidden:
                plan.categories.restored += 1
            elif changed:
                plan.categories.updated += 1
            else:
                plan.categories.unchanged += 1
        ids[category.external_id] = category_id
        plan.present_category_ids.append(category_id)
        if write:
            plan.category_writes.append(
                CategoryWrite(
                    id=category_id,
                    external_id=category.external_id,
                    pos_name=category.name,
                    sort_key=category.sort_key,
                )
            )
    for external_id, existing in current.categories.items():
        if external_id not in ids and not existing.is_hidden:
            plan.hide_category_ids.append(existing.id)
            plan.categories.hidden += 1
    return ids


def _plan_items(
    plan: MenuSyncPlan, current: CurrentMenu, snapshot: MenuSnapshot, category_ids: dict[str, uuid.UUID]
) -> None:
    """Позиции и цены снимка → записи, удаления тарифов и счётчики; пропавшие видимые → скрыть."""
    seen: set[str] = set()
    for item in snapshot.items:
        seen.add(item.external_id)
        existing = current.items.get(item.external_id)
        prices = dict(item.prices)
        write = ItemWrite(
            id=existing.id if existing is not None else new_id(),
            external_id=item.external_id,
            category_id=category_ids[item.category_external_id],
            pos_name=item.name,
            currency=item.currency or current.tenant_currency,
            station=item.station,
            sort_key=item.sort_key,
            is_available=item.is_available,
            prices=prices,
        )
        plan.present_item_ids.append(write.id)
        if existing is None:
            plan.items.created += 1
            plan.prices.created += len(prices)
            plan.item_writes.append(write)
            continue

        prices_changed = _plan_prices(plan, existing, prices)
        availability_changed = item.is_available is not None and item.is_available != existing.is_available
        if availability_changed:
            plan.availability_changed += 1
        changed = (
            prices_changed
            or availability_changed
            or existing.pos_name != write.pos_name
            or existing.category_id != write.category_id
            or existing.currency != write.currency
            or existing.station != write.station
            or existing.sort_key != write.sort_key
        )
        if existing.is_hidden:
            plan.items.restored += 1
        elif changed:
            plan.items.updated += 1
        else:
            plan.items.unchanged += 1
        if existing.is_hidden or changed:
            plan.item_writes.append(write)

    for external_id, existing in current.items.items():
        if external_id not in seen and not existing.is_hidden:
            plan.hide_item_ids.append(existing.id)
            plan.items.hidden += 1


def _plan_prices(plan: MenuSyncPlan, existing: CurrentItem, prices: dict[str, Decimal]) -> bool:
    """Счётчики и удаления тарифов существующей позиции; ``True``, если цены изменились."""
    changed = False
    for tier, price in prices.items():
        old = existing.prices.get(tier)
        if old is None:
            plan.prices.created += 1
            changed = True
        elif old != price:
            plan.prices.updated += 1
            changed = True
    for tier in sorted(existing.prices):
        if tier not in prices:
            plan.delete_prices.append((existing.id, tier))
            plan.prices.deleted += 1
            changed = True
    return changed


def _clear_writes(plan: MenuSyncPlan) -> None:
    """План с ошибкой не применяется: списков записи нет, счётчики остаются для отчёта."""
    plan.category_writes.clear()
    plan.item_writes.clear()
    plan.hide_category_ids.clear()
    plan.hide_item_ids.clear()
    plan.delete_prices.clear()
    plan.present_category_ids.clear()
    plan.present_item_ids.clear()
