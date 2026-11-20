import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.modules.stay_access.codes import (
    ALPHABET,
    CODE_LENGTH,
    code_lookup,
    format_code,
    generate_code,
    normalize_code,
    qr_payload,
)
from app.modules.stay_access.tokens import InvalidStayToken, decode_stay_token, encode_stay_token

SECRET = "stay-unit-secret-" + "q" * 32
PEPPER = "pepper-" + "p" * 40


class TestCodes:
    def test_alphabet_has_no_look_alikes(self) -> None:
        assert len(ALPHABET) == 31
        assert not set("01OIL") & set(ALPHABET)

    def test_generated_codes_use_only_the_alphabet(self) -> None:
        codes = [generate_code() for _ in range(2000)]
        assert all(len(c) == CODE_LENGTH and set(c) <= set(ALPHABET) for c in codes)
        assert len(set(codes)) == len(codes)
        # Every symbol shows up: the generator is not stuck on a subset.
        assert set(Counter("".join(codes))) == set(ALPHABET)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ABCD-EFGH", "ABCDEFGH"),
            ("abcd efgh", "ABCDEFGH"),
            ("  k7m2-9xpq ", "K7M29XPQ"),
            ("K7M2\t9XPQ", "K7M29XPQ"),
        ],
    )
    def test_normalize_accepts_friendly_input(self, raw: str, expected: str) -> None:
        assert normalize_code(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["", "ABCDEFG", "ABCDEFGHJ", "ABCD-EFG0", "ABCDEFGI", "ÀBCDEFGH", "ABCD_EFGH"]
    )
    def test_normalize_rejects_impossible_codes(self, raw: str) -> None:
        assert normalize_code(raw) is None

    def test_format_and_qr(self) -> None:
        assert format_code("K7M29XPQ") == "K7M2-9XPQ"
        assert qr_payload("K7M29XPQ") == "hotelapp://login?code=K7M29XPQ"

    def test_lookup_is_stable_keyed_and_not_the_code(self) -> None:
        a = code_lookup("K7M29XPQ", PEPPER)
        assert a == code_lookup("K7M29XPQ", PEPPER)
        assert a != code_lookup("K7M29XPQ", PEPPER + "x")
        assert a != code_lookup("K7M29XPR", PEPPER)
        assert "K7M29XPQ" not in a and len(a) == 64


class TestStayToken:
    ids = {"session_id": uuid.uuid4(), "stay_id": uuid.uuid4(), "room_id": uuid.uuid4()}

    def _encode(self, **overrides: object) -> str:
        args: dict = {
            **self.ids,
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "secret": SECRET,
        }
        args.update(overrides)
        return encode_stay_token(**args)

    def test_roundtrip(self) -> None:
        claims = decode_stay_token(self._encode(), secret=SECRET)
        assert claims.session_id == self.ids["session_id"]
        assert claims.stay_id == self.ids["stay_id"]
        assert claims.room_id == self.ids["room_id"]

    def test_expired(self) -> None:
        token = self._encode(expires_at=datetime.now(UTC) - timedelta(seconds=5))
        with pytest.raises(InvalidStayToken):
            decode_stay_token(token, secret=SECRET)

    def test_wrong_secret(self) -> None:
        with pytest.raises(InvalidStayToken):
            decode_stay_token(self._encode(), secret="other-" + "o" * 40)

    def test_staff_typed_token_is_rejected(self) -> None:
        payload = jwt.decode(self._encode(), SECRET, algorithms=["HS256"])
        payload["typ"] = "staff"
        with pytest.raises(InvalidStayToken, match="wrong token type"):
            decode_stay_token(jwt.encode(payload, SECRET, algorithm="HS256"), secret=SECRET)

    @pytest.mark.parametrize("claim", ["stay_id", "room_id", "jti"])
    def test_missing_or_bad_ids(self, claim: str) -> None:
        payload = jwt.decode(self._encode(), SECRET, algorithms=["HS256"])
        payload[claim] = "not-a-uuid"
        with pytest.raises(InvalidStayToken):
            decode_stay_token(jwt.encode(payload, SECRET, algorithm="HS256"), secret=SECRET)
        del payload[claim]
        with pytest.raises(InvalidStayToken):
            decode_stay_token(jwt.encode(payload, SECRET, algorithm="HS256"), secret=SECRET)
