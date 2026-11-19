"""Food-order state machine, declared once (docs/domain-rules.md §3).

    PENDING ─▶ CONFIRMED ─▶ PREPARING ─▶ DELIVERING ─▶ COMPLETED
       │           │
       └──▶ CANCELLED ◀──┘

`transition()` is the only code allowed to change `FoodOrder.status`.
"""

import enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, Conflict, Forbidden, InvalidTransition
from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.room_service.models import FoodOrder, OrderStatus
from app.modules.shared import status_history


class Actor(enum.StrEnum):
    GUEST = "GUEST"
    KITCHEN = "KITCHEN"
    RECEPTION = "RECEPTION"
    SYSTEM = "SYSTEM"


S = OrderStatus
TRANSITIONS: dict[tuple[OrderStatus, OrderStatus], frozenset[Actor]] = {
    (S.PENDING, S.CONFIRMED): frozenset({Actor.KITCHEN}),
    (S.PENDING, S.CANCELLED): frozenset(
        {Actor.GUEST, Actor.KITCHEN, Actor.RECEPTION, Actor.SYSTEM}
    ),
    (S.CONFIRMED, S.PREPARING): frozenset({Actor.KITCHEN}),
    (S.CONFIRMED, S.CANCELLED): frozenset({Actor.KITCHEN, Actor.RECEPTION, Actor.SYSTEM}),
    (S.PREPARING, S.DELIVERING): frozenset({Actor.KITCHEN}),
    (S.DELIVERING, S.COMPLETED): frozenset({Actor.KITCHEN}),
}


def check(from_status: OrderStatus, to_status: OrderStatus, actor: Actor) -> None:
    """409 for an impossible move, 403 for a move this actor may not make."""
    allowed = TRANSITIONS.get((from_status, to_status))
    if allowed is None:
        raise InvalidTransition(
            f"Không thể chuyển đơn từ {from_status.value} sang {to_status.value}"
        )
    if actor not in allowed:
        raise Forbidden()


def reason_required(from_status: OrderStatus, to_status: OrderStatus, actor: Actor) -> bool:
    return to_status is S.CANCELLED and (from_status is S.CONFIRMED or actor is not Actor.GUEST)


async def transition(
    db: AsyncSession,
    order: FoodOrder,
    to_status: OrderStatus,
    *,
    actor: Actor,
    actor_label: str,
    room_number: str,
    reason: str | None = None,
    expected_version: int | None = None,
    estimated_minutes: int | None = None,
) -> None:
    """Move `order` (already row-locked by the caller) and record it. Does not commit."""
    if expected_version is not None and expected_version != order.version:
        raise Conflict("Đơn vừa được người khác cập nhật, vui lòng tải lại", code="CONFLICT")
    from_status = order.status
    check(from_status, to_status, actor)
    reason = (reason or "").strip() or None
    if reason_required(from_status, to_status, actor) and reason is None:
        raise BadRequest(
            "Vui lòng nhập lý do hủy đơn",
            code="VALIDATION_ERROR",
            details=[{"field": "reason", "issue": "required"}],
        )

    order.status = to_status
    order.version += 1
    if to_status is S.CONFIRMED and estimated_minutes is not None:
        order.estimated_minutes = estimated_minutes
    if to_status is S.CANCELLED:
        order.cancel_reason = reason
        order.cancelled_by = actor_label
    status_history.record(
        db,
        entity_type=EntityType.FOOD_ORDER.value,
        entity_id=order.id,
        from_status=from_status.value,
        to_status=to_status.value,
        actor=actor_label,
        reason=reason,
    )
    await emit_status_changed(
        db,
        entity_type=EntityType.FOOD_ORDER,
        entity_id=order.id,
        stay_id=order.stay_id,
        status=to_status.value,
        room_number=room_number,
        actor=actor_label,
        push=actor is not Actor.GUEST,  # the guest knows what they just did
    )
