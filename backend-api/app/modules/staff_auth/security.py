"""Password hashing and staff token primitives. No database access here.

- Passwords: Argon2id (argon2-cffi defaults).
- Access token: JWT HS256 signed with STAFF_JWT_SECRET, `typ="staff"`,
  carries `ver` (token_version).
- Refresh token: 256-bit random string; only its sha256 is stored.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.modules.staff_auth.models import StaffRole

STAFF_TYP = "staff"
_ALGORITHM = "HS256"
_REQUIRED_CLAIMS = ["sub", "role", "typ", "ver", "iat", "exp", "jti"]

_hasher = PasswordHasher()
# A real hash computed once, so that "unknown email" costs the same time as "wrong password".
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class InvalidToken(Exception):
    """The token is malformed, expired, wrongly signed or of the wrong type."""


@dataclass(frozen=True)
class AccessClaims:
    staff_id: uuid.UUID
    role: StaffRole
    token_version: int
    jti: str
    expires_at: datetime


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-ish time check. Pass None for an unknown account to still pay the hashing cost."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def encode_access_token(
    *,
    staff_id: uuid.UUID,
    role: StaffRole,
    token_version: int,
    secret: str,
    ttl: timedelta,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + ttl
    payload = {
        "sub": str(staff_id),
        "role": role.value,
        "typ": STAFF_TYP,
        "ver": token_version,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM), expires_at


def decode_access_token(token: str, *, secret: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token, secret, algorithms=[_ALGORITHM], options={"require": _REQUIRED_CLAIMS}
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(type(exc).__name__) from None
    if payload.get("typ") != STAFF_TYP:
        raise InvalidToken("wrong token type")
    try:
        return AccessClaims(
            staff_id=uuid.UUID(payload["sub"]),
            role=StaffRole(payload["role"]),
            token_version=int(payload["ver"]),
            jti=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (ValueError, TypeError):
        raise InvalidToken("malformed claims") from None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
