"""Снимок меню — тело ``PUT /integration/v1/menu`` (ТЗ 4.4) и результат разбора файла (ADR-8.1, ADR-8.2).

Пример (JSON)::

    {
      "categories": [{"external_id": "19", "name": "Isti yemekler", "sort_key": "19"}],
      "items": [{
        "external_id": "157", "category_external_id": "19", "name": "Dolma",
        "prices": {"default": "8.00", "vip": "10.00"}, "currency": "AZN",
        "station": "Metbex", "sort_key": "17003", "is_available": true
      }]
    }

Story #61. Модель проверяет форму элементов: длины строк, деньги (``MoneyStr``), тарифы,
обязательный ``default``, лимиты размера. ``check_snapshot`` — дубли ``external_id``, ссылки позиций
на категории снимка, валюту заведения. Сравнение с текущим меню — ``plan`` (#62); хеш — #63.

Строки обрезаются по краям (``str_strip_whitespace``); управляющие символы запрещены.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import ErrorDetails, PydanticCustomError

from app.menu_sync.report import IssueCode, Severity, SyncIssue, has_errors, issue_value
from app.models.enums import CURRENCY_PATTERN, DEFAULT_PRICE_TIER, PRICE_TIER_PATTERN
from app.schemas.money import MoneyError, MoneyErrorReason, MoneyStr

# Длины (в БД у pos_name/station/sort_key CHECK нет — ограничивает синхронизация).
EXTERNAL_ID_MAX: Final[int] = 64  # = CHECK categories/menu_items.external_id
NAME_MAX: Final[int] = 200
STATION_MAX: Final[int] = 100
SORT_KEY_MAX: Final[int] = 64
# Лимиты снимка: защита памяти и транзакции; меню пилота — сотни позиций.
MAX_CATEGORIES: Final[int] = 500
MAX_ITEMS: Final[int] = 5000
MAX_TIERS_PER_ITEM: Final[int] = 10
# Строка без управляющих символов (U+0000–U+001F, U+007F).
NO_CONTROL_CHARS_PATTERN: Final[str] = r"^[^\x00-\x1f\x7f]*$"
# Типы собственных ошибок Pydantic (``PydanticCustomError``) валидатора тарифов.
MISSING_DEFAULT_PRICE_ERROR: Final[str] = "missing_default_price"
INVALID_TIER_ERROR: Final[str] = "invalid_price_tier"

_TIER_RE: Final[re.Pattern[str]] = re.compile(PRICE_TIER_PATTERN)
_ZERO: Final[Decimal] = Decimal(0)


class _SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SnapshotCategory(_SnapshotModel):
    """Категория кассы. ``name`` → ``categories.pos_name`` (админом не редактируется, FR-16)."""

    external_id: str = Field(min_length=1, max_length=EXTERNAL_ID_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    name: str = Field(min_length=1, max_length=NAME_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    sort_key: str = Field(default="", max_length=SORT_KEY_MAX, pattern=NO_CONTROL_CHARS_PATTERN)


class SnapshotItem(_SnapshotModel):
    """Позиция кассы.

    - ``prices`` — тариф → цена; ``default`` обязателен; ключи — ``PRICE_TIER_PATTERN``;
      тарифа нет в снимке — его строка в ``menu_item_prices`` удаляется (ADR-8.3);
    - ``currency`` — ``None``: валюта заведения; иначе обязана совпасть с ней (ADR-7.4, ADR-8.3);
    - ``is_available`` — ``None``: наличие не меняется (у новой позиции — ``true``), ADR-8.3.
    """

    external_id: str = Field(min_length=1, max_length=EXTERNAL_ID_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    category_external_id: str = Field(min_length=1, max_length=EXTERNAL_ID_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    name: str = Field(min_length=1, max_length=NAME_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    prices: dict[str, MoneyStr] = Field(min_length=1, max_length=MAX_TIERS_PER_ITEM)
    currency: str | None = Field(default=None, pattern=CURRENCY_PATTERN)
    station: str | None = Field(default=None, max_length=STATION_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    sort_key: str = Field(default="", max_length=SORT_KEY_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    is_available: bool | None = None

    @field_validator("prices")
    @classmethod
    def _check_tiers(cls, prices: dict[str, Decimal]) -> dict[str, Decimal]:
        """Ключи ``prices`` соответствуют ``PRICE_TIER_PATTERN``, ``default`` присутствует.

        Валидатор поля, а не модели: ошибка получает ``loc`` ``(…, "prices")`` и попадает в отчёт
        с полем ``prices.default``/``prices``.
        """
        invalid = sorted(tier for tier in prices if not _TIER_RE.fullmatch(tier))
        if invalid:
            raise PydanticCustomError(
                INVALID_TIER_ERROR, "недопустимое имя тарифа: {tiers}", {"tiers": ", ".join(invalid)}
            )
        if DEFAULT_PRICE_TIER not in prices:
            raise PydanticCustomError(MISSING_DEFAULT_PRICE_ERROR, "нет цены тарифа default")
        return prices

    @field_validator("station")
    @classmethod
    def _empty_station_to_none(cls, station: str | None) -> str | None:
        """Пустая ``station`` (``""`` или пробелы) приводится к ``None``."""
        return station or None


class MenuSnapshot(_SnapshotModel):
    """Полный снимок меню: всё, чего в нём нет, скрывается (INT-2).

    Модель проверяет только форму каждого элемента. Межэлементные проверки (дубли, ссылки на
    категории, валюта заведения) — в ``check_snapshot``: так ошибки разных позиций собираются все
    сразу, а не обрываются на первой (AC #61).
    """

    categories: list[SnapshotCategory] = Field(max_length=MAX_CATEGORIES)
    items: list[SnapshotItem] = Field(max_length=MAX_ITEMS)


def issues_from_validation_error(exc: ValidationError, data: Mapping[str, Any]) -> list[SyncIssue]:
    """Ошибки Pydantic → ``SyncIssue``: ``external_id`` элемента берётся из ``data`` по индексу в
    ``loc`` (``("items", 2, "prices", "default")``), поле — остаток ``loc``, сообщение — на русском.

    Ошибки категорий помечаются в сообщении префиксом «категория: »: ``external_id`` категорий и позиций —
    разные пространства имён.
    """
    return [_issue_from_error(error, data) for error in exc.errors()]


_MONEY_CODES: Final[dict[MoneyErrorReason, IssueCode]] = {
    MoneyErrorReason.INVALID: IssueCode.INVALID_MONEY,
    MoneyErrorReason.FLOAT: IssueCode.INVALID_MONEY,
    MoneyErrorReason.TOO_MANY_DECIMALS: IssueCode.TOO_MANY_DECIMALS,
    MoneyErrorReason.NEGATIVE: IssueCode.NEGATIVE_PRICE,
    MoneyErrorReason.TOO_LARGE: IssueCode.PRICE_TOO_LARGE,
}
_TYPE_MESSAGES: Final[dict[str, tuple[IssueCode, str]]] = {
    "missing": (IssueCode.REQUIRED, "обязательное поле не заполнено"),
    "extra_forbidden": (IssueCode.UNKNOWN_COLUMN, "неизвестное поле"),
    "string_too_short": (IssueCode.REQUIRED, "пустое значение"),
    "string_type": (IssueCode.INVALID_CELL_TYPE, "ожидается строка"),
    "bool_type": (IssueCode.INVALID_BOOL, "ожидается true или false"),
    "bool_parsing": (IssueCode.INVALID_BOOL, "ожидается true или false"),
    "dict_type": (IssueCode.INVALID_CELL_TYPE, "ожидается объект"),
    "list_type": (IssueCode.INVALID_CELL_TYPE, "ожидается список"),
    "model_type": (IssueCode.INVALID_CELL_TYPE, "ожидается объект"),
    "model_attributes_type": (IssueCode.INVALID_CELL_TYPE, "ожидается объект"),
    MISSING_DEFAULT_PRICE_ERROR: (IssueCode.REQUIRED, "нет цены тарифа default"),
}
_COLLECTION_NOUNS: Final[dict[str, str]] = {"categories": "категорий", "items": "позиций", "prices": "тарифов"}


def _element_external_id(data: object, loc: tuple[int | str, ...]) -> str | None:
    """``external_id`` элемента ``data[loc[0]][loc[1]]`` из сырых данных, если он строка или целое."""
    if len(loc) < 2 or loc[0] not in ("categories", "items") or not isinstance(loc[1], int):
        return None
    if not isinstance(data, Mapping):
        return None
    elements = data.get(loc[0])
    if not isinstance(elements, Sequence) or isinstance(elements, str) or not 0 <= loc[1] < len(elements):
        return None
    element = elements[loc[1]]
    raw = element.get("external_id") if isinstance(element, Mapping) else None
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    return None


def _field_of(loc: tuple[int | str, ...]) -> str | None:
    """Поле ошибки: остаток ``loc`` после ``(коллекция, индекс)``; ключ словаря — без ``[key]``."""
    if len(loc) == 1:
        return str(loc[0])
    parts = [str(part) for part in loc[2:] if part != "[key]"]
    return ".".join(parts) or None


def _code_and_reason(error: ErrorDetails, field: str | None) -> tuple[IssueCode, str, str | None]:
    """Код, причина на русском и уточнённое поле для одной ошибки Pydantic."""
    kind = error["type"]
    ctx = error.get("ctx") or {}
    if kind in _TYPE_MESSAGES:
        code, reason = _TYPE_MESSAGES[kind]
        if kind == MISSING_DEFAULT_PRICE_ERROR:
            field = f"prices.{DEFAULT_PRICE_TIER}"
        return code, reason, field
    if kind == INVALID_TIER_ERROR:
        return IssueCode.INVALID_TIER, f"недопустимое имя тарифа: {ctx.get('tiers')}", field
    if kind == "string_too_long":
        return IssueCode.TOO_LONG, f"длиннее {ctx.get('max_length')} символов", field
    if kind == "string_pattern_mismatch":
        if ctx.get("pattern") == CURRENCY_PATTERN:
            return IssueCode.INVALID_CURRENCY, "валюта — три заглавные латинские буквы ISO 4217 (AZN)", field
        return IssueCode.CONTROL_CHARS, "недопустимые управляющие символы (перевод строки, табуляция)", field
    if kind == "too_long":
        noun = _COLLECTION_NOUNS.get(field or "", "элементов")
        code = IssueCode.TOO_MANY_COLUMNS if field == "prices" else IssueCode.TOO_MANY_ROWS
        return code, f"больше {ctx.get('max_length')} {noun}", field
    if kind == "too_short" and field == "prices":
        return IssueCode.REQUIRED, "нет цены тарифа default", f"prices.{DEFAULT_PRICE_TIER}"
    cause = ctx.get("error")
    if isinstance(cause, MoneyError):
        return _MONEY_CODES[cause.reason], str(cause), field
    return IssueCode.INVALID_CELL_TYPE, "недопустимое значение", field


def _issue_from_error(error: ErrorDetails, data: Mapping[str, Any]) -> SyncIssue:
    loc = tuple(error["loc"])
    code, reason, field = _code_and_reason(error, _field_of(loc))
    if len(loc) >= 2 and loc[0] == "categories":
        reason = f"категория: {reason}"
    return SyncIssue(
        code=code,
        message=reason,
        column=field,
        external_id=_element_external_id(data, loc),
        value=_issue_value_of(error),
    )


def _issue_value_of(error: ErrorDetails) -> str | None:
    """Значение для отчёта: недопустимые имена тарифов или входное значение (составные не показываются)."""
    if error["type"] == INVALID_TIER_ERROR:
        return issue_value((error.get("ctx") or {}).get("tiers"))
    return issue_value(error.get("input"))


def check_snapshot(snapshot: MenuSnapshot, tenant_currency: str) -> list[SyncIssue]:
    """Межэлементные проверки снимка (#61), все ошибки сразу:

    - пустой список позиций — ``empty_snapshot``;
    - повтор ``external_id`` среди категорий и (отдельно) среди позиций — ``duplicate_external_id``;
    - ``category_external_id`` вне категорий снимка — ``unknown_category``;
    - ``currency`` задана и ≠ ``tenant_currency`` — ``currency_mismatch`` (ADR-7.4, ADR-8.3);
    - цена 0 — предупреждение ``zero_price``.
    """
    return _cross_check(snapshot.categories, snapshot.items, tenant_currency)


def _cross_check(
    categories: Sequence[SnapshotCategory],
    items: Sequence[SnapshotItem],
    tenant_currency: str,
    *,
    extra_category_ids: frozenset[str] = frozenset(),
    check_empty: bool = True,
) -> list[SyncIssue]:
    """Межэлементные проверки над уже проверенными по форме элементами.

    ``extra_category_ids`` — id категорий, не прошедших проверку формы (``parse_snapshot``): ссылка на
    них не считается ``unknown_category``, ошибка категории уже в отчёте.
    """
    issues: list[SyncIssue] = []
    if check_empty and not items:
        issues.append(
            SyncIssue(IssueCode.EMPTY_SNAPSHOT, "снимок без позиций: пустое меню не применяется", column="items")
        )

    category_ids: set[str] = set()
    for category in categories:
        if category.external_id in category_ids:
            issues.append(
                SyncIssue(
                    IssueCode.DUPLICATE_EXTERNAL_ID,
                    "категория: external_id повторяется в снимке",
                    column="external_id",
                    external_id=category.external_id,
                )
            )
        category_ids.add(category.external_id)
    known_categories = category_ids | extra_category_ids

    item_ids: set[str] = set()
    for item in items:
        eid = item.external_id
        if eid in item_ids:
            issues.append(
                SyncIssue(
                    IssueCode.DUPLICATE_EXTERNAL_ID,
                    "external_id позиции повторяется в снимке",
                    column="external_id",
                    external_id=eid,
                )
            )
        item_ids.add(eid)
        if item.category_external_id not in known_categories:
            issues.append(
                SyncIssue(
                    IssueCode.UNKNOWN_CATEGORY,
                    "категории с таким external_id нет в снимке",
                    column="category_external_id",
                    external_id=eid,
                    value=item.category_external_id,
                )
            )
        if item.currency is not None and item.currency != tenant_currency:
            issues.append(
                SyncIssue(
                    IssueCode.CURRENCY_MISMATCH,
                    f"валюта позиции {item.currency} не совпадает с валютой заведения {tenant_currency}",
                    column="currency",
                    external_id=eid,
                    value=item.currency,
                )
            )
        for tier, price in sorted(item.prices.items()):
            if price == _ZERO:
                issues.append(
                    SyncIssue(
                        IssueCode.ZERO_PRICE,
                        "цена 0: позиция будет бесплатной",
                        severity=Severity.WARNING,
                        column=f"prices.{tier}",
                        external_id=eid,
                        value="0.00",
                    )
                )
    return issues


def _check_valid_elements(data: object, tenant_currency: str) -> list[SyncIssue]:
    """Межэлементные проверки для снимка с ошибками формы: только над элементами без ошибок.

    Так ошибки формы одних позиций и ошибки согласованности других попадают в отчёт вместе (AC #61).
    Если сама структура снимка неверна или превышены лимиты размера, проверка не выполняется.
    """
    if not isinstance(data, Mapping):
        return []
    raw_categories = data.get("categories")
    raw_items = data.get("items")
    if not isinstance(raw_categories, list) or not isinstance(raw_items, list):
        return []
    if len(raw_categories) > MAX_CATEGORIES or len(raw_items) > MAX_ITEMS:
        return []

    categories: list[SnapshotCategory] = []
    invalid_category_ids: set[str] = set()
    for raw in raw_categories:
        try:
            categories.append(SnapshotCategory.model_validate(raw))
        except ValidationError:
            raw_id = raw.get("external_id") if isinstance(raw, Mapping) else None
            if isinstance(raw_id, str):
                invalid_category_ids.add(raw_id.strip())
    items: list[SnapshotItem] = []
    for raw in raw_items:
        try:
            items.append(SnapshotItem.model_validate(raw))
        except ValidationError:
            continue
    return _cross_check(
        categories,
        items,
        tenant_currency,
        extra_category_ids=frozenset(invalid_category_ids),
        check_empty=not raw_items,
    )


def parse_snapshot(data: Mapping[str, Any], tenant_currency: str) -> tuple[MenuSnapshot | None, list[SyncIssue]]:
    """Сырые данные (тело ``PUT /menu`` в #16) → снимок или ``None`` и проблемы.

    ``model_validate`` → при ``ValidationError`` — ``issues_from_validation_error``; иначе
    ``check_snapshot``. Снимок возвращается только без ошибок (предупреждения допустимы).

    При ошибках формы межэлементные проверки всё равно выполняются над элементами без ошибок:
    в отчёте сразу все проблемы снимка.
    """
    try:
        snapshot = MenuSnapshot.model_validate(data)
    except ValidationError as exc:
        issues = issues_from_validation_error(exc, data)
        issues.extend(_check_valid_elements(data, tenant_currency))
        return None, issues
    issues = check_snapshot(snapshot, tenant_currency)
    if has_errors(issues):
        return None, issues
    return snapshot, issues


def resolve_currency(snapshot: MenuSnapshot, tenant_currency: str) -> MenuSnapshot:
    """Копия снимка, где ``currency is None`` заменено валютой заведения (до расчёта хеша и плана).

    Валюту, отличную от валюты заведения, не меняет: такой снимок отвергает ``check_snapshot``.
    """
    items = [
        item.model_copy(update={"currency": tenant_currency}) if item.currency is None else item
        for item in snapshot.items
    ]
    return snapshot.model_copy(update={"items": items})


def snapshot_hash(snapshot: MenuSnapshot) -> str:
    """SHA-256 (hex, 64 символа) канонической формы снимка (INT-1, ADR-8.5). Реализуется в #63.

    Каноническая форма: категории и позиции отсортированы по ``external_id``, тарифы — по имени,
    деньги — строкой с двумя знаками, ``None`` — явным ``null``; ``json.dumps(sort_keys=True,
    separators=(",", ":"), ensure_ascii=False)`` в UTF-8. Порядок строк в файле и формат файла
    (CSV/XLSX) на хеш не влияют. Вызывается после ``resolve_currency``.
    """
    raise NotImplementedError
