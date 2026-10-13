"""Жизненный цикл заказа (ТЗ 4.6) без БД: ``ORDER_TRANSITIONS`` и ``can_transition``.

Ожидаемая матрица записана здесь независимо от кода: каждая пара статусов (8 × 8) проверяется
явно — разрешённые и запрещённые переходы. Дополнение к ТЗ, утверждённое пользователем:
``escalated → edited`` (FR-13, открытый вопрос 11 arch).
"""

from __future__ import annotations

import itertools

import pytest

from app.models.enums import CONFIRMED_STATUSES, ORDER_TRANSITIONS, OrderStatus, can_transition

S = OrderStatus

EXPECTED_ALLOWED: dict[OrderStatus, set[OrderStatus]] = {
    S.SUBMITTED: {S.EDITED, S.CONFIRMED, S.REJECTED, S.ESCALATED},
    S.EDITED: {S.CONFIRMED, S.REJECTED, S.ESCALATED},
    S.ESCALATED: {S.EDITED, S.CONFIRMED, S.REJECTED},
    S.CONFIRMED: {S.SENT_TO_POS, S.IN_POS, S.POS_FAILED},
    S.SENT_TO_POS: {S.IN_POS, S.POS_FAILED},
    S.REJECTED: set(),
    S.IN_POS: set(),
    S.POS_FAILED: set(),
}
TERMINAL = {S.REJECTED, S.IN_POS, S.POS_FAILED}
ALL_PAIRS = list(itertools.product(OrderStatus, OrderStatus))


def test_exactly_eight_statuses_from_tz() -> None:
    assert [s.value for s in OrderStatus] == [
        "submitted",
        "edited",
        "confirmed",
        "rejected",
        "escalated",
        "sent_to_pos",
        "in_pos",
        "pos_failed",
    ]


@pytest.mark.parametrize(("current", "target"), ALL_PAIRS, ids=[f"{a}->{b}" for a, b in ALL_PAIRS])
def test_every_pair(current: OrderStatus, target: OrderStatus) -> None:
    assert can_transition(current, target) is (target in EXPECTED_ALLOWED[current])


def test_transition_table_matches_expected() -> None:
    assert set(ORDER_TRANSITIONS) == set(OrderStatus)
    assert {status: set(targets) for status, targets in ORDER_TRANSITIONS.items()} == EXPECTED_ALLOWED


def test_escalated_can_be_edited() -> None:
    """Утверждённое пользователем дополнение к ТЗ 4.6."""
    assert can_transition(S.ESCALATED, S.EDITED)
    assert can_transition(S.EDITED, S.ESCALATED)


@pytest.mark.parametrize("status", sorted(TERMINAL))
def test_no_exit_from_terminal_statuses(status: OrderStatus) -> None:
    assert not ORDER_TRANSITIONS[status]
    assert not any(can_transition(status, target) for target in OrderStatus)


def test_no_self_transitions_and_no_return_to_submitted() -> None:
    for status in OrderStatus:
        assert not can_transition(status, status)
        assert not can_transition(status, S.SUBMITTED)


def test_confirmed_statuses_are_reachable_only_after_confirmation() -> None:
    """Всё, что достижимо из ``confirmed``, тоже требует ``confirmed_at`` (CHECK ``ck_orders_confirmed_at``)."""
    reachable = {S.CONFIRMED}
    frontier = [S.CONFIRMED]
    while frontier:
        for target in ORDER_TRANSITIONS[frontier.pop()]:
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    assert reachable == set(CONFIRMED_STATUSES)
    # В подтверждённые статусы из неподтверждённых ведёт только переход в confirmed.
    for status in set(OrderStatus) - set(CONFIRMED_STATUSES):
        assert ORDER_TRANSITIONS[status] & set(CONFIRMED_STATUSES) <= {S.CONFIRMED}


def test_accepts_values_from_database() -> None:
    assert can_transition("submitted", "confirmed")
    assert not can_transition("in_pos", "confirmed")


@pytest.mark.parametrize(("current", "target"), [("unknown", "confirmed"), ("submitted", "unknown_status")])
def test_unknown_status_is_an_error(current: str, target: str) -> None:
    with pytest.raises(ValueError, match="is not a valid OrderStatus"):
        can_transition(current, target)
