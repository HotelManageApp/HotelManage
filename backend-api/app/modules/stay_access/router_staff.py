"""Reception endpoints: rooms and stays (all require RECEPTION)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.db import DbSession
from app.core.errors import NotFound
from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.stay_access import events, repository, service
from app.modules.stay_access.models import Stay, StayStatus
from app.modules.stay_access.schemas import (
    CheckInRequest,
    CheckInResponse,
    IssuedCode,
    RoomCreate,
    RoomOut,
    RoomUpdate,
    StayOut,
    StaySummary,
    StayUpdate,
)

Reception = Annotated[Staff, Depends(require_roles(StaffRole.RECEPTION))]

router = APIRouter(tags=["reception"])


def stay_out(stay: Stay, room_number: str) -> StayOut:
    fields = {name: getattr(stay, name) for name in StayOut.model_fields if name != "room_number"}
    return StayOut(**fields, room_number=room_number)


@router.get("/rooms", response_model=list[RoomOut])
async def list_rooms(_: Reception, db: DbSession) -> list[RoomOut]:
    rows = await repository.list_rooms_with_open_stay(db)
    return [
        RoomOut.model_validate(room).model_copy(
            update={"open_stay": StaySummary.model_validate(stay) if stay else None}
        )
        for room, stay in rows
    ]


@router.post("/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(body: RoomCreate, _: Reception, db: DbSession) -> RoomOut:
    return RoomOut.model_validate(await service.create_room(db, body))


@router.patch("/rooms/{room_id}", response_model=RoomOut)
async def update_room(room_id: uuid.UUID, body: RoomUpdate, _: Reception, db: DbSession) -> RoomOut:
    return RoomOut.model_validate(await service.update_room(db, room_id, body))


@router.post("/stays", response_model=CheckInResponse, status_code=status.HTTP_201_CREATED)
async def check_in(
    body: CheckInRequest, request: Request, staff: Reception, db: DbSession
) -> CheckInResponse:
    issued = await service.check_in(db, request.app.state.settings, staff, body)
    return CheckInResponse(
        stay=stay_out(issued.stay, issued.room_number),
        room_code=issued.display_code,
        qr_payload=issued.qr_payload,
    )


@router.get("/stays", response_model=list[StayOut])
async def list_stays(
    _: Reception,
    db: DbSession,
    status_filter: Annotated[StayStatus | None, Query(alias="status")] = None,
) -> list[StayOut]:
    return [
        stay_out(stay, number) for stay, number in await repository.list_stays(db, status_filter)
    ]


@router.get("/stays/{stay_id}", response_model=StayOut)
async def get_stay(stay_id: uuid.UUID, _: Reception, db: DbSession) -> StayOut:
    stay = await repository.get_stay(db, stay_id)
    if stay is None:
        raise NotFound("Không tìm thấy kỳ lưu trú")
    room = await repository.get_room(db, stay.room_id)
    return stay_out(stay, room.number if room else "")


@router.patch("/stays/{stay_id}", response_model=StayOut)
async def update_stay(stay_id: uuid.UUID, body: StayUpdate, _: Reception, db: DbSession) -> StayOut:
    stay, number = await service.update_stay(db, stay_id, body)
    return stay_out(stay, number)


@router.post("/stays/{stay_id}/reissue-code", response_model=IssuedCode)
async def reissue_code(
    stay_id: uuid.UUID, request: Request, staff: Reception, db: DbSession
) -> IssuedCode:
    issued = await service.reissue_code(db, request.app.state.settings, stay_id, staff)
    return IssuedCode(room_code=issued.display_code, qr_payload=issued.qr_payload)


@router.post("/stays/{stay_id}/checkout", response_model=StayOut)
async def checkout(stay_id: uuid.UUID, staff: Reception, db: DbSession) -> StayOut:
    await events.run_desk_checkout_guards(db, stay_id)
    stay = await service.close_stay(db, stay_id, staff)
    room = await repository.get_room(db, stay.room_id)
    return stay_out(stay, room.number if room else "")


@router.post("/rooms/{room_id}/mark-vacant", response_model=RoomOut)
async def mark_vacant(room_id: uuid.UUID, _: Reception, db: DbSession) -> RoomOut:
    return RoomOut.model_validate(await service.mark_vacant(db, room_id))
