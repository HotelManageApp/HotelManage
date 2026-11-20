"""Reception: a stay's bill and its extras/discounts (SPEC-express-checkout, API nhân viên)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.db import DbSession
from app.core.errors import Conflict, NotFound
from app.modules.express_checkout.billing import Bill, build_bill, ensure_bill_editable
from app.modules.express_checkout.models import StayCharge
from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.stay_access.models import Stay, StayStatus
from app.modules.stay_access.schemas import StrictModel

Reception = Annotated[Staff, Depends(require_roles(StaffRole.RECEPTION))]

router = APIRouter(tags=["express-checkout"])


class ChargeIn(StrictModel):
    kind: Literal["EXTRA", "DISCOUNT"]
    description: str = Field(min_length=1, max_length=200)
    amount_vnd: int = Field(gt=0, le=1_000_000_000)


class ChargeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    description: str
    amount_vnd: int
    created_at: datetime


async def _open_stay(db: DbSession, stay_id: uuid.UUID, *, for_update: bool = False) -> Stay:
    stmt = select(Stay).where(Stay.id == stay_id)
    if for_update:
        stmt = stmt.with_for_update()
    stay = await db.scalar(stmt)
    if stay is None:
        raise NotFound("Không tìm thấy kỳ lưu trú")
    if stay.status is StayStatus.CLOSED:
        raise Conflict("Kỳ lưu trú đã kết thúc", code="STAY_CLOSED")
    return stay


@router.get("/stays/{stay_id}/bill", response_model=Bill)
async def stay_bill(stay_id: uuid.UUID, _: Reception, db: DbSession) -> Bill:
    """Current bill of an open stay (also for check-out at the desk)."""
    await _open_stay(db, stay_id)
    return await build_bill(db, stay_id)


@router.post(
    "/stays/{stay_id}/charges", response_model=ChargeOut, status_code=status.HTTP_201_CREATED
)
async def add_charge(
    stay_id: uuid.UUID, body: ChargeIn, staff: Reception, db: DbSession
) -> StayCharge:
    await _open_stay(db, stay_id, for_update=True)  # serialises with verify (same stay row)
    await ensure_bill_editable(db, stay_id)
    charge = StayCharge(stay_id=stay_id, created_by=staff.id, **body.model_dump())
    db.add(charge)
    await db.flush()
    await build_bill(db, stay_id)  # a discount larger than the bill -> 409 NEGATIVE_TOTAL
    await db.commit()
    await db.refresh(charge)
    return charge


@router.delete("/stays/{stay_id}/charges/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_charge(
    stay_id: uuid.UUID, charge_id: uuid.UUID, _: Reception, db: DbSession
) -> Response:
    await _open_stay(db, stay_id, for_update=True)
    await ensure_bill_editable(db, stay_id)
    charge = await db.scalar(
        select(StayCharge).where(
            StayCharge.id == charge_id,
            StayCharge.stay_id == stay_id,
            StayCharge.deleted_at.is_(None),
        )
    )
    if charge is None:
        raise NotFound("Không tìm thấy khoản phụ phí")
    charge.deleted_at = datetime.now(UTC)
    await db.flush()
    await build_bill(db, stay_id)  # removing an extra can leave discounts above the bill
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
