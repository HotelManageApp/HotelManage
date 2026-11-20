import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.modules.staff_auth.models import StaffRole
from app.modules.staff_auth.security import (
    InvalidToken,
    decode_access_token,
    encode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    tokens_equal,
    verify_password,
)

SECRET = "unit-test-secret-" + "y" * 32
STAFF_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _token(**overrides: object) -> str:
    args: dict = {
        "staff_id": STAFF_ID,
        "role": StaffRole.KITCHEN,
        "token_version": 3,
        "secret": SECRET,
        "ttl": timedelta(minutes=15),
    }
    args.update(overrides)
    token, _ = encode_access_token(**args)
    return token


class TestPasswords:
    def test_hash_is_argon2id_and_verifies(self) -> None:
        hashed = hash_password("correct horse battery")
        assert hashed.startswith("$argon2id$")
        assert verify_password(hashed, "correct horse battery")
        assert not password_needs_rehash(hashed)

    def test_wrong_password_fails(self) -> None:
        assert not verify_password(hash_password("right-password"), "wrong-password")

    def test_unknown_account_never_verifies(self) -> None:
        assert not verify_password(None, "anything")

    def test_garbage_hash_fails_closed(self) -> None:
        assert not verify_password("not-a-hash", "anything")

    def test_hashes_are_salted(self) -> None:
        assert hash_password("same") != hash_password("same")


class TestAccessToken:
    def test_roundtrip(self) -> None:
        token, expires_at = encode_access_token(
            staff_id=STAFF_ID,
            role=StaffRole.RECEPTION,
            token_version=7,
            secret=SECRET,
            ttl=timedelta(minutes=15),
        )
        claims = decode_access_token(token, secret=SECRET)
        assert claims.staff_id == STAFF_ID
        assert claims.role is StaffRole.RECEPTION
        assert claims.token_version == 7
        assert claims.expires_at == expires_at.replace(microsecond=0)

    def test_expired(self) -> None:
        old = datetime.now(UTC) - timedelta(hours=1)
        with pytest.raises(InvalidToken):
            decode_access_token(_token(now=old), secret=SECRET)

    def test_wrong_signature(self) -> None:
        with pytest.raises(InvalidToken):
            decode_access_token(_token(), secret="another-secret-" + "z" * 32)

    def test_guest_token_type_is_rejected(self) -> None:
        payload = jwt.decode(_token(), SECRET, algorithms=["HS256"])
        payload["typ"] = "stay"
        forged = jwt.encode(payload, SECRET, algorithm="HS256")
        with pytest.raises(InvalidToken, match="wrong token type"):
            decode_access_token(forged, secret=SECRET)

    def test_missing_claim(self) -> None:
        payload = jwt.decode(_token(), SECRET, algorithms=["HS256"])
        del payload["ver"]
        with pytest.raises(InvalidToken):
            decode_access_token(jwt.encode(payload, SECRET, algorithm="HS256"), secret=SECRET)

    def test_unknown_role(self) -> None:
        payload = jwt.decode(_token(), SECRET, algorithms=["HS256"])
        payload["role"] = "ADMIN"
        with pytest.raises(InvalidToken, match="malformed"):
            decode_access_token(jwt.encode(payload, SECRET, algorithm="HS256"), secret=SECRET)

    def test_alg_none_is_rejected(self) -> None:
        payload = jwt.decode(_token(), SECRET, algorithms=["HS256"])
        unsigned = jwt.encode(payload, key="", algorithm="none")
        with pytest.raises(InvalidToken):
            decode_access_token(unsigned, secret=SECRET)

    def test_garbage(self) -> None:
        with pytest.raises(InvalidToken):
            decode_access_token("not.a.jwt", secret=SECRET)


class TestRefreshToken:
    def test_random_and_hashed(self) -> None:
        a, b = new_refresh_token(), new_refresh_token()
        assert a != b and len(a) >= 43
        assert hash_refresh_token(a) == hash_refresh_token(a)
        assert hash_refresh_token(a) != a
        assert len(hash_refresh_token(a)) == 64

    def test_tokens_equal(self) -> None:
        assert tokens_equal("abc", "abc")
        assert not tokens_equal("abc", "abd")
