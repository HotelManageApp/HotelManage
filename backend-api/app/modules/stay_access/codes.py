"""Room codes (spec/SPEC-stay-access.md, "Mã phiên").

8 characters from a 31-symbol alphabet without look-alikes (no 0 O 1 I L): ~8.5e11 values.
Shown as XXXX-XXXX; typed in any case, with or without dashes/spaces.
Only HMAC-SHA256(code, pepper) is stored; the raw code is returned once at issue time.
"""

import hashlib
import hmac
import secrets

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
QR_PREFIX = "hotelapp://login?code="

_ALLOWED = frozenset(ALPHABET)


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str | None:
    """Canonical form of user input, or None when it cannot be a valid code."""
    cleaned = "".join(ch for ch in raw.upper() if ch not in "- \t\r\n")
    if len(cleaned) != CODE_LENGTH or not set(cleaned) <= _ALLOWED:
        return None
    return cleaned


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def code_lookup(code: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), code.encode(), hashlib.sha256).hexdigest()


def qr_payload(code: str) -> str:
    return QR_PREFIX + code
