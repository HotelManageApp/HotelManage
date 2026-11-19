"""ASGI middleware: request id, access log, and a last-resort 500 envelope.

- Accepts a client `X-Request-ID` if it looks safe, otherwise generates a ULID.
- Echoes the id in the `X-Request-ID` response header and binds it to every log line.
- Unhandled exceptions become `500 INTERNAL_ERROR` without leaking the stack trace.

Written as plain ASGI (not BaseHTTPMiddleware) so streaming responses (SSE, T21)
pass through untouched.
"""

import os
import re
import time

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import INTERNAL_ERROR_MESSAGE, error_response
from app.core.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

logger = get_logger(__name__)


def new_ulid() -> str:
    """26-char ULID: 48-bit millisecond timestamp + 80 random bits, Crockford base32."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def resolve_request_id(incoming: str | None) -> str:
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return new_ulid()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope["headers"]:
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = resolve_request_id(incoming)
        scope.setdefault("state", {})["request_id"] = request_id

        status_code = 500
        response_started = False
        started_at = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                logger.exception("unhandled_error")
                if response_started:
                    raise
                response = error_response(500, "INTERNAL_ERROR", INTERNAL_ERROR_MESSAGE, request_id)
                await response(scope, receive, send_with_request_id)
            finally:
                logger.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
                )
