"""Checkout request state machine (docs/domain-rules.md §5, SPEC-express-checkout).

    CHECKOUT_REQUESTED ─▶ BILLING_VERIFIED ─▶ COMPLETED
           │                     │
           └──────▶ REJECTED ◀───┘     (BILLING_VERIFIED → REJECTED: the guest disputes the bill)

Only reception moves a request; the guest creates it. Invalid pair -> 409, wrong actor -> 403,
stale version -> 409 CONFLICT.
"""

import enum

from app.core.errors import Conflict, Forbidden, InvalidTransition
from app.modules.express_checkout.models import CheckoutStatus


class Actor(enum.StrEnum):
    GUEST = "GUEST"
    RECEPTION = "RECEPTION"
    KITCHEN = "KITCHEN"
    HOUSEKEEPING = "HOUSEKEEPING"


S = CheckoutStatus
TRANSITIONS: dict[tuple[CheckoutStatus, CheckoutStatus], frozenset[Actor]] = {
    (S.CHECKOUT_REQUESTED, S.BILLING_VERIFIED): frozenset({Actor.RECEPTION}),
    (S.CHECKOUT_REQUESTED, S.REJECTED): frozenset({Actor.RECEPTION}),
    (S.BILLING_VERIFIED, S.COMPLETED): frozenset({Actor.RECEPTION}),
    (S.BILLING_VERIFIED, S.REJECTED): frozenset({Actor.RECEPTION}),
}


def check(
    from_status: CheckoutStatus,
    to_status: CheckoutStatus,
    actor: Actor,
    *,
    version: int | None = None,
    expected_version: int | None = None,
) -> None:
    allowed = TRANSITIONS.get((from_status, to_status))
    if allowed is None:
        raise InvalidTransition(
            f"Không thể chuyển yêu cầu trả phòng từ {from_status.value} sang {to_status.value}"
        )
    if actor not in allowed:
        raise Forbidden()
    if expected_version is not None and expected_version != version:
        raise Conflict("Yêu cầu vừa được người khác cập nhật, vui lòng tải lại", code="CONFLICT")
