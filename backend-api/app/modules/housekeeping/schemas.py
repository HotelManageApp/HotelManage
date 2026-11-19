import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from app.modules.housekeeping.models import AmenityCode, HkStatus, HkType, HousekeepingRequest
from app.modules.room_service.schemas import HistoryEntry
from app.modules.shared.status_history import StatusHistory
from app.modules.stay_access.schemas import StrictModel


class AmenityLine(StrictModel):
    code: AmenityCode
    quantity: int = Field(ge=1, le=5)


class CreateHousekeepingRequest(StrictModel):
    """No room, stay or assignee here: the server decides (C4.1). TURNOVER is not allowed."""

    type: Literal["CLEANING", "AMENITY"]
    amenities: list[AmenityLine] | None = Field(default=None, max_length=10)
    preferred_time: Literal["ASAP"] | AwareDatetime = "ASAP"
    note: str | None = Field(default=None, max_length=300)
    source: Literal["APP", "CHATBOT"] = "APP"


class DoNotDisturb(StrictModel):
    enabled: bool


class HousekeepingOut(BaseModel):
    id: uuid.UUID
    type: HkType
    status: HkStatus
    amenities: list[AmenityLine]
    preferred_time: datetime | None  # None = as soon as possible
    note: str | None
    source: str
    assignee: str | None  # short name shown to the guest ("Lan")
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    history: list[HistoryEntry] | None = None


def short_name(full_name: str | None) -> str | None:
    """Vietnamese names put the given name last: "Nguyen Thi Lan" -> "Lan"."""
    if not full_name:
        return None
    return full_name.split()[-1]


def request_out(
    request: HousekeepingRequest,
    *,
    assignee_name: str | None = None,
    history: list[StatusHistory] | None = None,
) -> HousekeepingOut:
    return HousekeepingOut(
        id=request.id,
        type=request.type,
        status=request.status,
        amenities=[AmenityLine(code=i.code, quantity=i.quantity) for i in request.items],
        preferred_time=request.preferred_time,
        note=request.note,
        source=request.source,
        assignee=short_name(assignee_name),
        cancel_reason=request.cancel_reason,
        created_at=request.created_at,
        updated_at=request.updated_at,
        version=request.version,
        history=None
        if history is None
        else [
            HistoryEntry(
                from_status=h.from_status,
                to_status=h.to_status,
                at=h.created_at,
                by=h.actor.split(":", 1)[0],
                reason=h.reason,
            )
            for h in history
        ],
    )
