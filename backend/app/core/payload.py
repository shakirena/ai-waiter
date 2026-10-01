"""Проверка JSON-сериализуемости данных событий и задач (ADR-1).

Общая для обоих режимов: в scaled payload уходит в Redis строкой JSON, поэтому и в single
он проверяется так же — иначе single скрывал бы ошибки, которые проявятся только на VPS.
"""

from __future__ import annotations

import json
from typing import Any


def ensure_json_object(value: Any, *, what: str = "payload") -> dict[str, Any]:
    """Вернуть ``value``, если это ``dict`` со строковыми ключами, сериализуемый в строгий JSON.

    ``NaN``/``Infinity``, ``Decimal``, ``datetime``, ``set``, произвольные объекты не допускаются —
    ``TypeError`` (деньги передаются строкой ``"12.50"``, время — строкой ISO 8601).
    """
    if not isinstance(value, dict):
        raise TypeError(f"{what} должен быть словарём (dict), получен {type(value).__name__}")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{what} не сериализуется в JSON: {exc}") from None
    if not _has_only_str_keys(value):
        raise TypeError(f"{what}: ключи словарей должны быть строками")
    return value


def _has_only_str_keys(value: Any) -> bool:
    """``json.dumps`` молча превращает ключи ``1``/``None``/``True`` в строки — после круга через
    Redis словарь стал бы другим. Поэтому нестроковые ключи запрещены на любой глубине."""
    if isinstance(value, dict):
        return all(isinstance(key, str) and _has_only_str_keys(item) for key, item in value.items())
    if isinstance(value, list | tuple):
        return all(_has_only_str_keys(item) for item in value)
    return True
