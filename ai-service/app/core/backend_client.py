"""Calls to backend-api on behalf of a guest (SPEC-concierge-guide, "Kiến trúc").

ai-service has no database and no backend secret: every call carries the guest's own
`stay_session_token`, so the backend checks the session (and its revocation) exactly as for the
app. Errors are mapped to a few exceptions the orchestrator turns into HTTP answers:

    401 from backend         -> BackendUnauthorized   (the chat answers 401)
    429 from backend         -> BackendRateLimited    (429 with the same Retry-After)
    timeout / network / 5xx  -> BackendUnavailable    (503)
    other 4xx                -> BackendError          (outside a tool: 502; a tool maps it to
                                                       its error code, see concierge/tools/base)

The token is never logged and never put in an exception message.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)


class BackendError(RuntimeError):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(f"backend answered {status} {code}")
        self.status, self.code, self.message = status, code, message


class BackendUnauthorized(BackendError):
    pass


class BackendRateLimited(BackendError):
    def __init__(self, retry_after_seconds: int, message: str = "") -> None:
        super().__init__(429, "RATE_LIMITED", message)
        self.retry_after_seconds = retry_after_seconds


class BackendUnavailable(BackendError):
    pass


@dataclass(frozen=True)
class GuestContext:
    """What the backend says about the token's stay (`GET /guest/me`). No ids: the backend
    resolves the stay from the token on every call (C4.1)."""

    room_number: str
    guest_name: str | None
    status: str
    lang: str

    @property
    def checkout_pending(self) -> bool:
        return self.status == "CHECKOUT_PENDING"


@dataclass(frozen=True)
class HotelInfo:
    hotel_name: str
    reception_phone: str
    default_lang: str
    chat_enabled: bool


@dataclass(frozen=True)
class ChatLine:
    role: str  # GUEST | ASSISTANT
    content: str


class BackendClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        try:
            response = await self._http.request(
                method,
                path,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException:
            logger.warning("backend_timeout", path=path)
            raise BackendUnavailable(0, "TIMEOUT") from None
        except httpx.HTTPError as exc:
            logger.warning("backend_unreachable", path=path, error_type=type(exc).__name__)
            raise BackendUnavailable(0, "NETWORK_ERROR") from None

        if response.status_code < 400:
            return response.json() if response.content else None
        error = _envelope(response)
        code, message = error.get("code", "HTTP_ERROR"), error.get("message", "")
        if response.status_code == 401:
            raise BackendUnauthorized(401, code, message)
        if response.status_code == 429:
            retry = response.headers.get("Retry-After", "")
            raise BackendRateLimited(int(retry) if retry.isdigit() else 60, message)
        if response.status_code >= 500:
            logger.warning("backend_error", path=path, status=response.status_code)
            raise BackendUnavailable(response.status_code, code, message)
        # 404/409 are business answers a tool passes on (no request yet, dish sold out…);
        # any other 4xx means ai-service sent something wrong.
        log = logger.info if response.status_code in (404, 409) else logger.error
        log("backend_rejected", path=path, status=response.status_code, code=code)
        raise BackendError(response.status_code, code, message)

    # ---------- guest endpoints ----------

    async def me(self, token: str) -> GuestContext:
        data = await self._call("GET", "/api/v1/guest/me", token)
        return GuestContext(
            room_number=data["room_number"],
            guest_name=data.get("guest_name"),
            status=data["status"],
            lang=data.get("lang", "vi"),
        )

    async def hotel_info(self, token: str) -> HotelInfo:
        data = await self._call("GET", "/api/v1/guest/hotel-info", token)
        return HotelInfo(
            hotel_name=data["hotel_name"],
            reception_phone=data["reception_phone"],
            default_lang=data["default_lang"],
            chat_enabled=bool(data["chat_enabled"]),
        )

    async def take_quota(self, token: str) -> None:
        await self._call("POST", "/api/v1/guest/chat/quota", token)

    async def history(self, token: str, *, limit: int = 10) -> list[ChatLine]:
        data = await self._call(
            "GET", "/api/v1/guest/chat/messages", token, params={"limit": limit}
        )
        return [ChatLine(role=m["role"], content=m["content"]) for m in data]

    async def save_exchange(
        self,
        token: str,
        *,
        guest_message: str,
        assistant_message: str,
        tool_trace: Any,
        grounded: bool | None,
        client_message_id: uuid.UUID | None,
    ) -> str:
        data = await self._call(
            "POST",
            "/api/v1/guest/chat/messages",
            token,
            json={
                "guest_message": guest_message,
                "assistant_message": assistant_message,
                "tool_trace": tool_trace,
                "grounded": grounded,
                "client_message_id": str(client_message_id) if client_message_id else None,
            },
        )
        return str(data["message_id"])

    async def kb_search(self, token: str, *, topic: str, query: str, lang: str) -> dict[str, Any]:
        """`data` of the get_hotel_info_and_guide tool (chatbot-tools-spec §4.1)."""
        return await self._call(
            "GET",
            "/api/v1/guest/kb/search",
            token,
            params={"topic": topic, "q": query, "lang": lang},
        )

    async def menu(
        self, token: str, *, category: str | None = None, search: str | None = None
    ) -> dict[str, Any]:
        params = {k: v for k, v in (("category", category), ("search", search)) if v}
        return await self._call("GET", "/api/v1/guest/menu", token, params=params or None)

    async def my_orders(self, token: str) -> list[dict[str, Any]]:
        return await self._call("GET", "/api/v1/guest/orders", token)

    async def my_housekeeping(self, token: str) -> list[dict[str, Any]]:
        return await self._call("GET", "/api/v1/guest/housekeeping-requests", token)

    async def current_checkout(self, token: str) -> dict[str, Any] | None:
        """The stay's latest checkout request, or None when there is none (404)."""
        try:
            return await self._call("GET", "/api/v1/guest/checkout-requests/current", token)
        except BackendError as exc:
            if exc.status == 404:
                return None
            raise


def _envelope(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    error = body.get("error") if isinstance(body, dict) else None
    return error if isinstance(error, dict) else {}
