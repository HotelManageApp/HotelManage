"""Every (from, to, actor) combination against docs/domain-rules.md §3 (C5.4)."""

import itertools

import pytest

from app.core.errors import Forbidden, InvalidTransition
from app.modules.room_service.models import OrderStatus as S
from app.modules.room_service.state import Actor, check, reason_required

# The table from docs/domain-rules.md §3, written out independently of state.TRANSITIONS.
EXPECTED: dict[tuple[S, S], set[Actor]] = {
    (S.PENDING, S.CONFIRMED): {Actor.KITCHEN},
    (S.PENDING, S.CANCELLED): {Actor.GUEST, Actor.KITCHEN, Actor.RECEPTION, Actor.SYSTEM},
    (S.CONFIRMED, S.PREPARING): {Actor.KITCHEN},
    (S.CONFIRMED, S.CANCELLED): {Actor.KITCHEN, Actor.RECEPTION, Actor.SYSTEM},
    (S.PREPARING, S.DELIVERING): {Actor.KITCHEN},
    (S.DELIVERING, S.COMPLETED): {Actor.KITCHEN},
}

CASES = list(itertools.product(S, S, Actor))


@pytest.mark.parametrize(("from_status", "to_status", "actor"), CASES)
def test_transition_matrix(from_status: S, to_status: S, actor: Actor) -> None:
    allowed = EXPECTED.get((from_status, to_status))
    if allowed is None:
        with pytest.raises(InvalidTransition):
            check(from_status, to_status, actor)
    elif actor not in allowed:
        with pytest.raises(Forbidden):
            check(from_status, to_status, actor)
    else:
        check(from_status, to_status, actor)


def test_matrix_size() -> None:
    assert len(CASES) == 6 * 6 * 4


@pytest.mark.parametrize(
    ("from_status", "actor", "required"),
    [
        (S.PENDING, Actor.GUEST, False),
        (S.PENDING, Actor.KITCHEN, True),
        (S.PENDING, Actor.RECEPTION, True),
        (S.CONFIRMED, Actor.KITCHEN, True),
        (S.CONFIRMED, Actor.SYSTEM, True),
    ],
)
def test_cancel_reason_rules(from_status: S, actor: Actor, required: bool) -> None:
    assert reason_required(from_status, S.CANCELLED, actor) is required
    assert reason_required(from_status, S.CONFIRMED, actor) is False
