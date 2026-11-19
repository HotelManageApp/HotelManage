import json
import re

import pytest

from app.core.logging import (
    REDACTED,
    configure_logging,
    get_logger,
    is_sensitive_key,
    redact_sensitive,
)
from app.core.request_context import new_ulid, resolve_request_id

ULID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")


@pytest.mark.parametrize(
    "key",
    [
        "authorization",
        "Authorization",
        "password",
        "room_code",
        "access_token",
        "fcm_token",
        "refresh_token",
        "api_key",
        "llm_api_key",
        "cookie",
        "token",
    ],
)
def test_sensitive_keys(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", ["code", "status", "path", "request_id", "token_version", "event"])
def test_non_sensitive_keys(key: str) -> None:
    assert not is_sensitive_key(key)


def test_redacts_nested_values_and_keeps_others() -> None:
    event = {
        "event": "login",
        "headers": {"Authorization": "Bearer abc", "accept": "json"},
        "items": [{"room_code": "ABCD-EFGH"}, {"name": "x"}],
        "status": 200,
    }
    out = redact_sensitive(None, "info", event)
    assert out["headers"] == {"Authorization": REDACTED, "accept": "json"}
    assert out["items"] == [{"room_code": REDACTED}, {"name": "x"}]
    assert out["status"] == 200
    assert event["headers"]["Authorization"] == "Bearer abc"  # input not mutated


def test_log_output_is_json_and_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger("test").info("something", password="hunter2", fcm_token="tok-123", status=1)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "something"
    assert record["level"] == "info"
    assert "timestamp" in record
    assert "hunter2" not in line and "tok-123" not in line
    assert record["password"] == REDACTED


def test_debug_is_filtered_at_info_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger("test").debug("hidden")
    assert "hidden" not in capsys.readouterr().out


def test_new_ulid_format_and_uniqueness() -> None:
    ids = {new_ulid() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(ULID.fullmatch(i) for i in ids)


@pytest.mark.parametrize("incoming", ["abc-12345", "01JD0000000000000000000000", "A" * 64])
def test_accepts_safe_client_request_id(incoming: str) -> None:
    assert resolve_request_id(incoming) == incoming


@pytest.mark.parametrize(
    "incoming", [None, "", "short", "has space here", "x" * 65, "bad\nnewline", "<script>"]
)
def test_replaces_unsafe_client_request_id(incoming: str | None) -> None:
    assert ULID.fullmatch(resolve_request_id(incoming))
