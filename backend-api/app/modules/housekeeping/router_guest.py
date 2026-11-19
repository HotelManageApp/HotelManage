"""Guest housekeeping requests and do-not-disturb (spec/SPEC-housekeeping.md)."""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status
from sqlalchemy import select

from app.core.db import DbSession
from app.core.errors import NotFound, ValidationFailed
from app.modules.housekeeping import service, state
from app.modules.housekeeping.models import HkStatus, HkType, HousekeepingRequest
from app.modules.housekeeping.schemas import (
    CreateHousekeepingRequest,
    DoNotDisturb,
    HousekeepingOut,
    request_out,
)
from app.modules.notifications.api import EntityType, notify_staff, staff_event_payload
from app.modules.shared.status_history import history_of
from app.modules.staff_auth.models import Staff
from app.modules.stay_access.deps import ActiveStay, CurrentStay, StayContext, ensure_same_stay
from app.modules.stay_access.models import Stay

router = APIRouter(prefix="/guest", tags=["guest-housekeeping"])

IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


async def _assignee_name(db: DbSession, request: HousekeepingRequest) -> str | None:
    if request.assigned_to is None:
        return None
    return await db.scalar(select(Staff.full_name).where(Staff.id == request.assigned_to))


async def _own(
    db: DbSession, ctx: StayContext, request_id: uuid.UUID, *, for_update: bool = False
) -> HousekeepingRequest:
    stmt = select(HousekeepingRequest).where(
        HousekeepingRequest.id == request_id, HousekeepingRequest.type != HkType.TURNOVER
    )
    if for_update:
        stmt = stmt.with_for_update()
    request = await db.scalar(stmt)
    if request is None or request.stay_id is None:
        raise NotFound("Không tìm thấy yêu cầu")
    ensure_same_stay(ctx, request.stay_id)
    return request


@router.post(
    "/housekeeping-requests", response_model=HousekeepingOut, status_code=status.HTTP_201_CREATED
)
async def create(
    body: CreateHousekeepingRequest,
    ctx: ActiveStay,
    response: Response,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> HousekeepingOut:
    if idempotency_key is not None and not re.fullmatch(IDEMPOTENCY_PATTERN, idempotency_key):
        raise ValidationFailed(
            details=[{"field": "Idempotency-Key", "issue": "8-64 [A-Za-z0-9_-]"}]
        )
    request, created = await service.create_request(db, ctx, body, idempotency_key=idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return request_out(request, assignee_name=await _assignee_name(db, request))


@router.get("/housekeeping-requests", response_model=list[HousekeepingOut])
async def mine(
    ctx: CurrentStay,
    db: DbSession,
    status_filter: Annotated[HkStatus | None, Query(alias="status")] = None,
) -> list[HousekeepingOut]:
    stmt = select(HousekeepingRequest).where(HousekeepingRequest.stay_id == ctx.stay_id)
    if status_filter is not None:
        stmt = stmt.where(HousekeepingRequest.status == status_filter)
    requests = await db.scalars(stmt.order_by(HousekeepingRequest.created_at.desc()).limit(50))
    return [request_out(r, assignee_name=await _assignee_name(db, r)) for r in requests]


@router.get("/housekeeping-requests/{request_id}", response_model=HousekeepingOut)
async def one(request_id: uuid.UUID, ctx: CurrentStay, db: DbSession) -> HousekeepingOut:
    request = await _own(db, ctx, request_id)
    return request_out(
        request,
        assignee_name=await _assignee_name(db, request),
        history=await history_of(db, EntityType.HOUSEKEEPING.value, request.id),
    )


@router.post("/housekeeping-requests/{request_id}/cancel", response_model=HousekeepingOut)
async def cancel(request_id: uuid.UUID, ctx: CurrentStay, db: DbSession) -> HousekeepingOut:
    request = await _own(db, ctx, request_id, for_update=True)
    await state.transition(
        db,
        request,
        HkStatus.CANCELLED,
        actor=state.Actor.GUEST,
        actor_label="GUEST",
        room_number=ctx.room_number,
        reason="Khách hủy",
    )
    await db.commit()
    await db.refresh(request)
    return request_out(
        request, history=await history_of(db, EntityType.HOUSEKEEPING.value, request.id)
    )


@router.put("/me/do-not-disturb", status_code=status.HTTP_204_NO_CONTENT)
async def do_not_disturb(body: DoNotDisturb, ctx: ActiveStay, db: DbSession) -> Response:
    stay = await db.get(Stay, ctx.stay_id, with_for_update=True)
    if stay is not None and stay.do_not_disturb != body.enabled:
        now = datetime.now(UTC)
        stay.do_not_disturb = body.enabled
        stay.dnd_updated_at = now
        await notify_staff(
            db,
            staff_event_payload(
                event="do_not_disturb",
                entity_type=EntityType.STAY,
                entity_id=stay.id,
                status="DND_ON" if body.enabled else "DND_OFF",
                room_number=ctx.room_number,
                actor="GUEST",
                occurred_at=now,
            ),
        )
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
