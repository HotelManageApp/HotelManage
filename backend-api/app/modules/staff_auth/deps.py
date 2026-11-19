"""Authentication dependency for staff endpoints. Role checks (`require_roles`) arrive in T09."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.db import DbSession
from app.core.errors import Unauthorized
from app.modules.staff_auth import repository
from app.modules.staff_auth.models import Staff
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
