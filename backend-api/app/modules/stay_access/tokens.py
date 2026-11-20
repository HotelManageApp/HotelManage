"""Guest (stay) tokens: JWT HS256 with STAY_JWT_SECRET and `typ="stay"`.

Separate secret and type from staff tokens, so neither kind can pass for the other.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt

STAY_TYP = "stay"
_ALGORITHM = "HS256"
_REQUIRED = ["typ", "jti", "stay_id", "room_id", "iat", "exp"]


class InvalidStayToken(Exception):
    pass


@dataclass(frozen=True)
class StayClaims:
    session_id: uuid.UUID
    stay_id: uuid.UUID
    room_id: uuid.UUID
    expires_at: datetime


def encode_stay_token(
    *,
    session_id: uuid.UUID,
    stay_id: uuid.UUID,
    room_id: uuid.UUID,
    expires_at: datetime,
    secret: str,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        "typ": STAY_TYP,
        "jti": str(session_id),
        "stay_id": str(stay_id),
        "room_id": str(room_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_stay_token(token: str, *, secret: str) -> StayClaims:
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM], options={"require": _REQUIRED})
    except jwt.PyJWTError as exc:
        raise InvalidStayToken(type(exc).__name__) from None
    if payload.get("typ") != STAY_TYP:
        raise InvalidStayToken("wrong token type")
    try:
        return StayClaims(
            session_id=uuid.UUID(payload["jti"]),
            stay_id=uuid.UUID(payload["stay_id"]),
            room_id=uuid.UUID(payload["room_id"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (ValueError, TypeError):
        raise InvalidStayToken("malformed claims") from None
