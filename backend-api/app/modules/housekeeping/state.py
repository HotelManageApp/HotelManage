"""Housekeeping state machine (docs/domain-rules.md §4, plus "hand back" from SPEC-housekeeping).

    REQUESTED ─▶ ASSIGNED ─▶ IN_PROGRESS ─▶ DONE
        ▲            │
        └────────────┘ (hand back, assignee only)
    REQUESTED ─▶ CANCELLED (guest, reception, system); ASSIGNED ─▶ CANCELLED (system)
    TURNOVER ─▶ DONE sets the room from CLEANING to VACANT.

Only the staff member a request is assigned to may start, finish or hand it back.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, Conflict, Forbidden, InvalidTransition
from app.modules.housekeeping.models import HkStatus, HkType, HousekeepingRequest
from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.shared import status_history
from app.modules.stay_access.models import Room, RoomStatus


class Actor(enum.StrEnum):
    GUEST = "GUEST"
    HOUSEKEEPING = "HOUSEKEEPING"
    RECEPTION = "RECEPTION"
    SYSTEM = "SYSTEM"


S = HkStatus
TRANSITIONS: dict[tuple[HkStatus, HkStatus], frozenset[Actor]] = {
    (S.REQUESTED, S.ASSIGNED): frozenset({Actor.HOUSEKEEPING}),
    (S.ASSIGNED, S.IN_PROGRESS): frozenset({Actor.HOUSEKEEPING}),
    (S.IN_PROGRESS, S.DONE): frozenset({Actor.HOUSEKEEPING}),
    (S.ASSIGNED, S.REQUESTED): frozenset({Actor.HOUSEKEEPING}),
    (S.REQUESTED, S.CANCELLED): frozenset({Actor.GUEST, Actor.RECEPTION, Actor.SYSTEM}),
    # Claimed but not started when the stay closes or the room is marked vacant.
    (S.ASSIGNED, S.CANCELLED): frozenset({Actor.SYSTEM}),
}
ASSIGNEE_ONLY = {(S.ASSIGNED, S.IN_PROGRESS), (S.IN_PROGRESS, S.DONE), (S.ASSIGNED, S.REQUESTED)}


def check(
    from_status: HkStatus,
    to_status: HkStatus,
    actor: Actor,
    *,
    request_type: HkType = HkType.CLEANING,
    staff_id: uuid.UUID | None = None,
    assigned_to: uuid.UUID | None = None,
) -> None:
    allowed = TRANSITIONS.get((from_status, to_status))
    if allowed is None:
        raise InvalidTransition(
            f"Không thể chuyển yêu cầu từ {from_status.value} sang {to_status.value}"
        )
    if actor not in allowed:
        raise Forbidden()
    if request_type is HkType.TURNOVER and actor is Actor.GUEST:
        raise Forbidden()
    if (from_status, to_status) in ASSIGNEE_ONLY and (staff_id is None or staff_id != assigned_to):
        raise Forbidden("Việc này đang do nhân viên khác phụ trách")


async def transition(
    db: AsyncSession,
    request: HousekeepingRequest,
    to_status: HkStatus,
    *,
    actor: Actor,
    actor_label: str,
    room_number: str,
    staff_id: uuid.UUID | None = None,
    reason: str | None = None,
    expected_version: int | None = None,
    push: bool | None = None,
) -> None:
    """Move `request` (already row-locked) and record it. Does not commit."""
    if expected_version is not None and expected_version != request.version:
        raise Conflict("Yêu cầu vừa được người khác cập nhật, vui lòng tải lại", code="CONFLICT")
    from_status = request.status
    check(
        from_status,
        to_status,
        actor,
        request_type=request.type,
        staff_id=staff_id,
        assigned_to=request.assigned_to,
    )
    reason = (reason or "").strip() or None
    if to_status is S.CANCELLED and actor is Actor.RECEPTION and reason is None:
        raise BadRequest(
            "Vui lòng nhập lý do hủy",
            code="VALIDATION_ERROR",
            details=[{"field": "reason", "issue": "required"}],
        )

    now = datetime.now(UTC)
    request.status = to_status
    request.version += 1
    if to_status is S.ASSIGNED:
        request.assigned_to = staff_id
        request.assigned_at = now
    elif to_status is S.REQUESTED:  # handed back
        request.assigned_to = None
        request.assigned_at = None
    elif to_status is S.IN_PROGRESS:
        request.started_at = now
    elif to_status is S.DONE:
        request.done_at = now
        if request.type is HkType.TURNOVER:
            room = await db.get(Room, request.room_id, with_for_update=True)
            if room is not None and room.status is RoomStatus.CLEANING:
                room.status = RoomStatus.VACANT
    elif to_status is S.CANCELLED:
        request.cancel_reason = reason
        request.cancelled_by = actor_label

    status_history.record(
        db,
        entity_type=EntityType.HOUSEKEEPING.value,
        entity_id=request.id,
        from_status=from_status.value,
        to_status=to_status.value,
        actor=actor_label,
        reason=reason,
    )
    guest_push = (
        request.stay_id is not None  # TURNOVER has no guest
        and actor is not Actor.GUEST
        and to_status is not S.REQUESTED  # a hand-back is internal
    )
    await emit_status_changed(
        db,
        entity_type=EntityType.HOUSEKEEPING,
        entity_id=request.id,
        stay_id=request.stay_id or uuid.UUID(int=0),
        status=to_status.value,
        room_number=room_number,
        actor=actor_label,
        push=guest_push if push is None else (push and request.stay_id is not None),
    )
