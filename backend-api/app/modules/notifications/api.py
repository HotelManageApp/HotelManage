"""The only notifications entry point for business modules.

    await emit_status_changed(db, entity_type=EntityType.FOOD_ORDER, entity_id=order.id,
                              stay_id=order.stay_id, status="PREPARING", room_number="101",
                              actor=f"STAFF:{staff.id}")

Call it inside the transaction that changes the status. It adds an outbox row (guest push) and a
`pg_notify('staff_events', ...)` (web SSE). PostgreSQL delivers NOTIFY only on COMMIT, and the
outbox row only exists after COMMIT, so a rolled-back change produces no notification at all.
"""

import enum
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import NotificationOutbox

STAFF_EVENTS_CHANNEL = "staff_events"


class EntityType(enum.StrEnum):
    FOOD_ORDER = "FOOD_ORDER"
    HOUSEKEEPING = "HOUSEKEEPING"
    CHECKOUT = "CHECKOUT"
    STAY = "STAY"


def staff_event_payload(
    *,
    entity_type: EntityType,
    entity_id: uuid.UUID,
    status: str,
    room_number: str,
    actor: str,
    occurred_at: datetime,
    event: str = "status_changed",
) -> dict[str, Any]:
    return {
        "event": event,
        "entity_type": entity_type.value,
        "entity_id": str(entity_id),
        "status": status,
        "room_number": room_number,
        "actor": actor,
        "occurred_at": occurred_at.isoformat(),
    }


async def notify_staff(db: AsyncSession, payload: dict[str, Any]) -> None:
    """Queue a staff SSE event; delivered when the surrounding transaction commits."""
    await db.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": STAFF_EVENTS_CHANNEL, "payload": json.dumps(payload)},
    )


async def emit_status_changed(
    db: AsyncSession,
    *,
    entity_type: EntityType,
    entity_id: uuid.UUID,
    stay_id: uuid.UUID,
    status: str,
    room_number: str,
    actor: str,
    push: bool = True,
    target_tokens: list[dict[str, str]] | None = None,
) -> None:
    """Record a status change for the guest (push) and for staff screens (SSE).

    `push=False` skips the guest push (e.g. the guest made the change themselves, or there is
    no guest any more). `target_tokens` fixes the recipients (used when the stay closes).
    """
    now = datetime.now(UTC)
    if push:
        db.add(
            NotificationOutbox(
                stay_id=stay_id,
                entity_type=entity_type.value,
                entity_id=entity_id,
                status=status,
                target_tokens=target_tokens,
            )
        )
    await notify_staff(
        db,
        staff_event_payload(
            entity_type=entity_type,
            entity_id=entity_id,
            status=status,
            room_number=room_number,
            actor=actor,
            occurred_at=now,
        ),
    )
