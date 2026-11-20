import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.stay_access.models import RoomStatus, StayStatus


class StrictModel(BaseModel):
    """Request bodies reject unknown fields (CONSTRAINTS C4.1: no room_id/stay_id smuggling)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- rooms ----------


class RoomCreate(StrictModel):
    number: str = Field(min_length=1, max_length=20)
    floor: int | None = Field(default=None, ge=-5, le=200)
    room_type: str | None = Field(default=None, max_length=60)


class RoomUpdate(StrictModel):
    number: str | None = Field(default=None, min_length=1, max_length=20)
    floor: int | None = Field(default=None, ge=-5, le=200)
    room_type: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None


class StaySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    guest_name: str | None
    guest_count: int
    checkin_at: datetime
    expected_checkout_at: datetime
    status: StayStatus


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    floor: int | None
    room_type: str | None
    status: RoomStatus
    is_active: bool
    open_stay: StaySummary | None = None


# ---------- stays ----------


class CheckInRequest(StrictModel):
    room_id: uuid.UUID
    guest_name: str | None = Field(default=None, max_length=100)
    guest_count: int = Field(default=1, ge=1, le=20)
    expected_checkout_at: AwareDatetime
    room_charge_vnd: int = Field(ge=0, le=10_000_000_000)
    note: str | None = Field(default=None, max_length=500)


class StayUpdate(StrictModel):
    guest_name: str | None = Field(default=None, max_length=100)
    guest_count: int | None = Field(default=None, ge=1, le=20)
    expected_checkout_at: AwareDatetime | None = None
    room_charge_vnd: int | None = Field(default=None, ge=0, le=10_000_000_000)
    note: str | None = Field(default=None, max_length=500)


class StayOut(BaseModel):
    """Never contains the room code or its lookup hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    room_id: uuid.UUID
    room_number: str
    guest_name: str | None
    guest_count: int
    checkin_at: datetime
    expected_checkout_at: datetime
    room_charge_vnd: int
    note: str | None
    status: StayStatus
    code_issued_at: datetime
    closed_at: datetime | None


class IssuedCode(BaseModel):
    """The raw room code. Returned exactly once, at check-in or re-issue."""

    room_code: str  # XXXX-XXXX
    qr_payload: str


class CheckInResponse(IssuedCode):
    stay: StayOut
