"""Authentication and role checks for staff endpoints.

Every staff endpoint declares its roles:

    @router.post("/orders/{order_id}/confirm")
    async def confirm(order_id: UUID, staff: Annotated[Staff, Depends(require_roles(KITCHEN))]): ...

`tests/integration/test_route_guards.py` fails if an /api/v1 endpoint has neither a staff nor a
guest dependency and is not on the explicit public list.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.db import DbSession
from app.core.errors import Forbidden, Unauthorized
from app.modules.staff_auth import repository
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.staff_auth.security import InvalidToken, decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def current_staff(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> Staff:
    """Valid signature, `typ=staff`, not expired, account active and token_version current."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthorized()
    secret = request.app.state.settings.staff_jwt_secret.get_secret_value()
    try:
        claims = decode_access_token(credentials.credentials, secret=secret)
    except InvalidToken:
        raise Unauthorized() from None
    staff = await repository.get_staff(db, claims.staff_id)
    if staff is None or not staff.is_active or staff.token_version != claims.token_version:
        raise Unauthorized()
    return staff


CurrentStaff = Annotated[Staff, Depends(current_staff)]


def require_roles(*roles: StaffRole) -> Callable[..., Awaitable[Staff]]:
    """Dependency factory: the authenticated staff member must hold one of `roles`."""
    if not roles:
        raise ValueError("require_roles needs at least one role")
    allowed = frozenset(roles)

    async def dependency(staff: CurrentStaff) -> Staff:
        if staff.role not in allowed:
            raise Forbidden()
        return staff

    return dependency
