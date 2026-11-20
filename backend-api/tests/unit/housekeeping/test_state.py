"""Housekeeping transitions: every (from, to, actor) pair, assignee rule, TURNOVER (C5.4)."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import Forbidden, InvalidTransition
from app.modules.housekeeping.models import HkStatus as S
from app.modules.housekeeping.models import HkType, HousekeepingRequest
from app.modules.housekeeping.router_staff import priority
from app.modules.housekeeping.state import Actor, check

EXPECTED: dict[tuple[S, S], set[Actor]] = {
    (S.REQUESTED, S.ASSIGNED): {Actor.HOUSEKEEPING},
    (S.ASSIGNED, S.IN_PROGRESS): {Actor.HOUSEKEEPING},
    (S.IN_PROGRESS, S.DONE): {Actor.HOUSEKEEPING},
    (S.ASSIGNED, S.REQUESTED): {Actor.HOUSEKEEPING},
    (S.REQUESTED, S.CANCELLED): {Actor.GUEST, Actor.RECEPTION, Actor.SYSTEM},
    (S.ASSIGNED, S.CANCELLED): {Actor.SYSTEM},
}
ME = uuid.uuid4()


@pytest.mark.parametrize(
    ("from_status", "to_status", "actor"), list(itertools.product(S, S, Actor))
)
def test_matrix(from_status: S, to_status: S, actor: Actor) -> None:
    allowed = EXPECTED.get((from_status, to_status))
    kwargs = {"staff_id": ME, "assigned_to": ME}
    if allowed is None:
        with pytest.raises(InvalidTransition):
            check(from_status, to_status, actor, **kwargs)
    elif actor not in allowed:
        with pytest.raises(Forbidden):
            check(from_status, to_status, actor, **kwargs)
    else:
        check(from_status, to_status, actor, **kwargs)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [(S.ASSIGNED, S.IN_PROGRESS), (S.IN_PROGRESS, S.DONE), (S.ASSIGNED, S.REQUESTED)],
)
def test_only_the_assignee(from_status: S, to_status: S) -> None:
    with pytest.raises(Forbidden):
        check(from_status, to_status, Actor.HOUSEKEEPING, staff_id=uuid.uuid4(), assigned_to=ME)


def test_guest_never_touches_turnover() -> None:
    with pytest.raises(Forbidden):
        check(S.REQUESTED, S.CANCELLED, Actor.GUEST, request_type=HkType.TURNOVER)


def _request(
    kind: HkType, created_minutes_ago: int, preferred_in: int | None = None
) -> HousekeepingRequest:
    now = datetime.now(UTC)
    return HousekeepingRequest(
        type=kind,
        created_at=now - timedelta(minutes=created_minutes_ago),
        preferred_time=None if preferred_in is None else now + timedelta(minutes=preferred_in),
    )


def test_priority_order() -> None:
    now = datetime.now(UTC)
    later_cleaning = _request(HkType.CLEANING, 30, preferred_in=120)
    due_cleaning = _request(HkType.CLEANING, 5)
    old_cleaning = _request(HkType.CLEANING, 40)
    amenity = _request(HkType.AMENITY, 1)
    turnover = _request(HkType.TURNOVER, 0)
    ordered = sorted(
        [later_cleaning, due_cleaning, amenity, old_cleaning, turnover],
        key=lambda r: priority(r, now),
    )
    assert ordered == [turnover, amenity, old_cleaning, due_cleaning, later_cleaning]
