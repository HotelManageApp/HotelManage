"""Every (from, to) pair × every actor of the checkout state machine (SPEC: 16 pairs × 4 actors)."""

import itertools

import pytest

from app.core.errors import Conflict, Forbidden, InvalidTransition
from app.modules.express_checkout.models import CheckoutStatus
from app.modules.express_checkout.state import TRANSITIONS, Actor, check

S = CheckoutStatus
ALLOWED = {
    (S.CHECKOUT_REQUESTED, S.BILLING_VERIFIED),
    (S.CHECKOUT_REQUESTED, S.REJECTED),
    (S.BILLING_VERIFIED, S.COMPLETED),
    (S.BILLING_VERIFIED, S.REJECTED),
}


@pytest.mark.parametrize(
    ("from_status", "to_status", "actor"),
    list(itertools.product(CheckoutStatus, CheckoutStatus, Actor)),
)
def test_every_pair_and_actor(
    from_status: CheckoutStatus, to_status: CheckoutStatus, actor: Actor
) -> None:
    if (from_status, to_status) not in ALLOWED:
        with pytest.raises(InvalidTransition):
            check(from_status, to_status, actor)
    elif actor is not Actor.RECEPTION:
        with pytest.raises(Forbidden):
            check(from_status, to_status, actor)
    else:
        check(from_status, to_status, actor)


def test_the_table_is_exactly_the_documented_one() -> None:
    assert set(TRANSITIONS) == ALLOWED
    assert all(actors == {Actor.RECEPTION} for actors in TRANSITIONS.values())


def test_a_stale_version_is_a_conflict() -> None:
    with pytest.raises(Conflict) as caught:
        check(
            S.CHECKOUT_REQUESTED, S.BILLING_VERIFIED, Actor.RECEPTION, version=2, expected_version=1
        )
    assert caught.value.code == "CONFLICT"
    check(S.CHECKOUT_REQUESTED, S.BILLING_VERIFIED, Actor.RECEPTION, version=2, expected_version=2)
