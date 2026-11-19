"""Role matrix (CONSTRAINTS C5.3): each role reaches only its own endpoints."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import jwt
import pytest
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole
from tests.conftest import TEST_STAFF_JWT_SECRET
from tests.factories import DEFAULT_PASSWORD, create_staff

ROLES = list(StaffRole)


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    """Test-only endpoints, one per role, plus one shared by two roles."""
    router = APIRouter(prefix="/api/v1/_rbac")
    for role in ROLES:

        def make(r: StaffRole):  # bind role per endpoint
            async def endpoint(
                staff: Annotated[Staff, Depends(require_roles(r))],
            ) -> dict[str, str]:
                return {"role": staff.role.value}

            return endpoint

        router.add_api_route(f"/{role.value.lower()}", make(role), methods=["GET"])

    @router.get("/reception-or-kitchen")
    async def shared(
        staff: Annotated[Staff, Depends(require_roles(StaffRole.RECEPTION, StaffRole.KITCHEN))],
    ) -> dict[str, str]:
        return {"role": staff.role.value}

    app.include_router(router)
    return app


async def _token(client: httpx.AsyncClient, db: AsyncSession, role: StaffRole) -> str:
    email = f"{role.value.lower()}@hotel.test"
    await create_staff(db, email=email, role=role)
    response = await client.post(
        "/api/v1/staff/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    return response.json()["access_token"]


@pytest.mark.parametrize("caller", ROLES, ids=lambda r: r.value)
@pytest.mark.parametrize("target", ROLES, ids=lambda r: r.value)
async def test_role_matrix(
    client: httpx.AsyncClient, db: AsyncSession, caller: StaffRole, target: StaffRole
) -> None:
    token = await _token(client, db, caller)
    response = await client.get(
        f"/api/v1/_rbac/{target.value.lower()}", headers={"Authorization": f"Bearer {token}"}
    )
    if caller is target:
        assert response.status_code == 200
        assert response.json() == {"role": caller.value}
    else:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("caller", "expected"),
    [(StaffRole.RECEPTION, 200), (StaffRole.KITCHEN, 200), (StaffRole.HOUSEKEEPING, 403)],
    ids=lambda v: getattr(v, "value", str(v)),
)
async def test_endpoint_with_several_roles(
    client: httpx.AsyncClient, db: AsyncSession, caller: StaffRole, expected: int
) -> None:
    token = await _token(client, db, caller)
    response = await client.get(
        "/api/v1/_rbac/reception-or-kitchen", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == expected


async def test_no_token_is_401(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/_rbac/kitchen")).status_code == 401


async def test_guest_token_is_401(client: httpx.AsyncClient, db: AsyncSession) -> None:
    """A token of type `stay` must never pass as staff, even if signed with the staff secret."""
    staff = await create_staff(db, role=StaffRole.KITCHEN)
    now = datetime.now(UTC)
    guest_like = jwt.encode(
        {
            "sub": str(staff.id),
            "role": "KITCHEN",
            "typ": "stay",
            "ver": 0,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": uuid.uuid4().hex,
        },
        TEST_STAFF_JWT_SECRET,
        algorithm="HS256",
    )
    response = await client.get(
        "/api/v1/_rbac/kitchen", headers={"Authorization": f"Bearer {guest_like}"}
    )
    assert response.status_code == 401


def test_require_roles_needs_a_role() -> None:
    with pytest.raises(ValueError, match="at least one role"):
        require_roles()
