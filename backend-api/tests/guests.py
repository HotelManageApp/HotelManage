"""Get a signed-in guest through the real endpoints (reception check-in + room-code login)."""

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff_auth.models import StaffRole
from tests.factories import create_staff, staff_headers


@dataclass
class Guest:
    headers: dict[str, str]
    stay_id: str
    room_number: str
    reception: dict[str, str]


async def check_in_guest(
    client: httpx.AsyncClient,
    db: AsyncSession,
    *,
    room_number: str = "101",
    lang: str = "vi",
    device: str | None = None,
) -> Guest:
    reception = staff_headers(
        await create_staff(
            db, email=f"rx-{room_number}-{lang}@hotel.test", role=StaffRole.RECEPTION
        )
    )
    room = await client.post("/api/v1/rooms", json={"number": room_number}, headers=reception)
    issued = await client.post(
        "/api/v1/stays",
        json={
            "room_id": room.json()["id"],
            "guest_name": "Tran Thi B",
            "expected_checkout_at": "2099-01-01T05:00:00Z",
            "room_charge_vnd": 1_000_000,
        },
        headers=reception,
    )
    login = await client.post(
        "/api/v1/guest/auth/room-code",
        json={
            "code": issued.json()["room_code"],
            "device_id": device or f"device-{room_number}-{lang}-0001",
            "lang": lang,
        },
    )
    assert login.status_code == 200, login.text
    return Guest(
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        stay_id=issued.json()["stay"]["id"],
        room_number=room_number,
        reception=reception,
    )
