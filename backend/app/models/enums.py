"""Значения статусов и справочных полей — единый источник для CHECK-ограничений (ADR-7.2),
Pydantic-схем и TS-типов.

Статусы хранятся как ``text`` + ``CHECK (col IN (...))``; список значений в CHECK строится
из этих перечислений. Новое значение = правка перечисления + миграция с пересозданием CHECK
(``alembic check`` CHECK не сравнивает — это делает ``ENUM_CHECKS`` в ``tests/db/test_migrations.py``, DEC-009).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class OrderStatus(StrEnum):
    """ТЗ 4.6."""

    SUBMITTED = "submitted"
    EDITED = "edited"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    SENT_TO_POS = "sent_to_pos"
    IN_POS = "in_pos"
    POS_FAILED = "pos_failed"


# Допустимые переходы (ТЗ 4.6). Проверяет сервис заказов; каждый переход пишет order_events.
# Дополнение к ТЗ, утверждённое пользователем: escalated → edited (FR-13: правка перед подтверждением).
# Терминальные: rejected, in_pos, pos_failed (ручной ввод в кассу — событие manual_pos_entry, не статус).
# Правка уже отредактированного заказа (edited → edited) — не переход: статус тот же, пишется событие.
ORDER_TRANSITIONS: Final[dict[OrderStatus, frozenset[OrderStatus]]] = {
    OrderStatus.SUBMITTED: frozenset(
        {OrderStatus.EDITED, OrderStatus.CONFIRMED, OrderStatus.REJECTED, OrderStatus.ESCALATED}
    ),
    OrderStatus.EDITED: frozenset({OrderStatus.CONFIRMED, OrderStatus.REJECTED, OrderStatus.ESCALATED}),
    OrderStatus.ESCALATED: frozenset({OrderStatus.EDITED, OrderStatus.CONFIRMED, OrderStatus.REJECTED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.SENT_TO_POS, OrderStatus.IN_POS, OrderStatus.POS_FAILED}),
    OrderStatus.SENT_TO_POS: frozenset({OrderStatus.IN_POS, OrderStatus.POS_FAILED}),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.IN_POS: frozenset(),
    OrderStatus.POS_FAILED: frozenset(),
}

# Статусы, в которых заказ уже подтверждён официантом: confirmed_at обязателен (CHECK).
CONFIRMED_STATUSES: Final[frozenset[OrderStatus]] = frozenset(
    {OrderStatus.CONFIRMED, OrderStatus.SENT_TO_POS, OrderStatus.IN_POS, OrderStatus.POS_FAILED}
)


def can_transition(current: OrderStatus | str, target: OrderStatus | str) -> bool:
    """``True``, если из статуса ``current`` можно перейти в ``target`` (``ORDER_TRANSITIONS``).

    Принимает и строки из БД: неизвестное значение — ``ValueError`` (ошибка данных, а не «нельзя»).
    """
    return OrderStatus(target) in ORDER_TRANSITIONS[OrderStatus(current)]


class OrderEventType(StrEnum):
    """Тип записи журнала ``order_events`` (append-only, ADR-7.6)."""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    ITEM_REMOVED = "item_removed"
    ITEM_QTY_CHANGED = "item_qty_changed"
    POS_ACK = "pos_ack"
    POS_ERROR = "pos_error"
    POS_TOTAL_MISMATCH = "pos_total_mismatch"
    MANUAL_POS_ENTRY = "manual_pos_entry"


class ActorType(StrEnum):
    """Кто совершил действие в ``order_events``; ``actor_id`` — мягкая ссылка без FK."""

    GUEST = "guest"
    STAFF = "staff"
    CONNECTOR = "connector"
    SYSTEM = "system"


class VisitStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class VisitClosedBy(StrEnum):
    """ТЗ 7: официант / касса / таймаут (FR-14a, ``visit_idle_close_hours``)."""

    STAFF = "staff"
    POS = "pos"
    TIMEOUT = "timeout"


class TableType(StrEnum):
    """Стол или кабинет (FR-15)."""

    TABLE = "table"
    CABIN = "cabin"


class WeightUnit(StrEnum):
    """Единица веса/объёма порции (``menu_item_meta.weight_unit``); на AZ/RU локализуется при показе."""

    G = "g"
    ML = "ml"
    PCS = "pcs"


class MessageRole(StrEnum):
    """Роль сообщения в терминах Claude API: ``user`` — гость или tool_result, ``assistant`` — бот."""

    USER = "user"
    ASSISTANT = "assistant"


class Lang(StrEnum):
    """Языки гостя (FR-2, AI-6)."""

    AZ = "az"
    RU = "ru"


DEFAULT_PRICE_TIER: Final[str] = "default"
# CHECK для price_tier: строчные латинские буквы, цифры, «_»; до 32 символов.
PRICE_TIER_PATTERN: Final[str] = r"^[a-z][a-z0-9_]{0,31}$"
# CHECK для валюты: ISO 4217.
CURRENCY_PATTERN: Final[str] = r"^[A-Z]{3}$"
# CHECK для qr_token: base64url, не короче 22 символов (≥ 128 бит, FR-1).
QR_TOKEN_PATTERN: Final[str] = r"^[A-Za-z0-9_-]{22,64}$"  # noqa: S105 — шаблон, не секрет
# CHECK для кода аллергена (gluten, milk, ...): как тариф — строчные латинские буквы, цифры, «_».
ALLERGEN_CODE_PATTERN: Final[str] = r"^[a-z][a-z0-9_]{0,31}$"
# CHECK для относительного ключа фото в хранилище медиа: не начинается с «/», «\» или буквы диска.
ABSOLUTE_PATH_PATTERN: Final[str] = r"^([/\\]|[A-Za-z]:)"
