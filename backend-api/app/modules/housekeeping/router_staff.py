"""Housekeeping and reception views of housekeeping requests (spec/SPEC-housekeeping.md)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from app.core.db import DbSession
from app.core.errors import NotFound
from app.modules.housekeeping import state
from app.modules.housekeeping.models import (
    OPEN_HK_STATUSES,
    HkStatus,
    HkType,
    HousekeepingRequest,
)
from app.modules.housekeeping.schemas import HousekeepingOut, request_out
from app.modules.notifications.api import EntityType
from app.modules.shared.status_history import history_of
from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.stay_access.models import Room, Stay
from app.modules.stay_access.schemas import StrictModel

Housekeeping = Annotated[Staff, Depends(require_roles(StaffRole.HOUSEKEEPING))]
Reception = Annotated[Staff, Depends(require_roles(StaffRole.RECEPTION))]
HousekeepingOrReception = Annotated[
    Staff, Depends(require_roles(StaffRole.HOUSEKEEPING, StaffRole.RECEPTION))
]

RECENT_FINISHED = timedelta(hours=12)
OVERDUE_AFTER = timedelta(minutes=15)

router = APIRouter(prefix="/housekeeping-requests", tags=["staff-housekeeping"])


class StaffHousekeepingOut(HousekeepingOut):
    room_number: str
    do_not_disturb: bool
    guest_name: str | None = None  # reception only
    assigned_to: uuid.UUID | None
    assignee_full_name: str | None
    overdue: bool


class TransitionBody(StrictModel):
    to: Literal["ASSIGNED", "IN_PROGRESS", "DONE", "REQUESTED"]
    version: int = Field(ge=0)


class CancelBody(StrictModel):
    version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=300)


def due_at(request: HousekeepingRequest) -> datetime:
    return max(request.created_at, request.preferred_time or request.created_at)


def priority(request: HousekeepingRequest, now: datetime) -> tuple:
    """Turnover first, then amenities, then cleaning that is due, then by preferred time."""
    if request.type is HkType.TURNOVER:
        group = 0
    elif request.type is HkType.AMENITY:
        group = 1
    elif request.preferred_time is None or request.preferred_time <= now:
        group = 2
    else:
        group = 3
    return (group, due_at(request), request.created_at)


Assignee = aliased(Staff)


def _query():
    return (
        select(
            HousekeepingRequest,
            Room.number,
            Stay.guest_name,
            Stay.do_not_disturb,
            Assignee.full_name,
        )
        .join(Room, Room.id == HousekeepingRequest.room_id)
        .outerjoin(Stay, Stay.id == HousekeepingRequest.stay_id)
        .outerjoin(Assignee, Assignee.id == HousekeepingRequest.assigned_to)
    )


def _view(row, staff: Staff, now: datetime) -> StaffHousekeepingOut:
    request, number, guest_name, dnd, assignee = row
    base = request_out(request, assignee_name=assignee)
    return StaffHousekeepingOut(
        **base.model_dump(),
        room_number=number,
        do_not_disturb=bool(dnd),
        guest_name=guest_name if staff.role is StaffRole.RECEPTION else None,
        assigned_to=request.assigned_to,
        assignee_full_name=assignee,
        overdue=request.status is HkStatus.REQUESTED and now - due_at(request) > OVERDUE_AFTER,
    )


@router.get("", response_model=list[StaffHousekeepingOut])
async def list_requests(
    staff: HousekeepingOrReception,
    db: DbSession,
    status_filter: Annotated[HkStatus | None, Query(alias="status")] = None,
    type_filter: Annotated[HkType | None, Query(alias="type")] = None,
    mine: Annotated[bool, Query()] = False,
) -> list[StaffHousekeepingOut]:
    now = datetime.now(UTC)
    stmt = _query()
    if status_filter is not None:
        stmt = stmt.where(HousekeepingRequest.status == status_filter)
    else:
        stmt = stmt.where(
            or_(
                HousekeepingRequest.status.in_(OPEN_HK_STATUSES),
                HousekeepingRequest.updated_at >= now - RECENT_FINISHED,
            )
        )
    if type_filter is not None:
        stmt = stmt.where(HousekeepingRequest.type == type_filter)
    if mine:
        stmt = stmt.where(HousekeepingRequest.assigned_to == staff.id)
    rows = (await db.execute(stmt.limit(300))).all()
    rows.sort(key=lambda row: priority(row[0], now))
    return [_view(row, staff, now) for row in rows]


async def _load(db: DbSession, request_id: uuid.UUID, *, for_update: bool = False):
    # populate_existing: after a commit, reload columns and items of the object already in the
    # session instead of lazily loading them later (not possible with asyncio).
    stmt = (
        _query()
        .where(HousekeepingRequest.id == request_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=HousekeepingRequest)
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise NotFound("Không tìm thấy yêu cầu")
    return row


async def _respond(db: DbSession, request_id: uuid.UUID, staff: Staff) -> StaffHousekeepingOut:
    row = await _load(db, request_id)
    view = _view(row, staff, datetime.now(UTC))
    view.history = request_out(
        row[0], history=await history_of(db, EntityType.HOUSEKEEPING.value, row[0].id)
    ).history
    return view


@router.get("/{request_id}", response_model=StaffHousekeepingOut)
async def get_request(
    request_id: uuid.UUID, staff: HousekeepingOrReception, db: DbSession
) -> StaffHousekeepingOut:
    return await _respond(db, request_id, staff)


@router.post("/{request_id}/transition", response_model=StaffHousekeepingOut)
async def transition(
    request_id: uuid.UUID, body: TransitionBody, staff: Housekeeping, db: DbSession
) -> StaffHousekeepingOut:
    request, number, *_ = await _load(db, request_id, for_update=True)
    await state.transition(
        db,
        request,
        HkStatus(body.to),
        actor=state.Actor.HOUSEKEEPING,
        actor_label=f"STAFF:{staff.id}",
        room_number=number,
        staff_id=staff.id,
        expected_version=body.version,
    )
    await db.commit()
    return await _respond(db, request_id, staff)


@router.post("/{request_id}/cancel", response_model=StaffHousekeepingOut)
async def cancel(
    request_id: uuid.UUID, body: CancelBody, staff: Reception, db: DbSession
) -> StaffHousekeepingOut:
    request, number, *_ = await _load(db, request_id, for_update=True)
    await state.transition(
        db,
        request,
        HkStatus.CANCELLED,
        actor=state.Actor.RECEPTION,
        actor_label=f"STAFF:{staff.id}",
        room_number=number,
        reason=body.reason,
        expected_version=body.version,
    )
    await db.commit()
    return await _respond(db, request_id, staff)
