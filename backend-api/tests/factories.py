"""Test data builders. Keep them small; each test states what matters to it."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.staff_auth.security import hash_password

DEFAULT_PASSWORD = "correct-horse-battery"


async def create_staff(
    db: AsyncSession,
    *,
    email: str = "le.tan@hotel.test",
    role: StaffRole = StaffRole.RECEPTION,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Nguyen Van A",
    is_active: bool = True,
) -> Staff:
    staff = Staff(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(staff)
    await db.commit()
    await db.refresh(staff)
    return staff
