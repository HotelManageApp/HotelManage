"""Firebase Cloud Messaging HTTP v1 sender (spec/SPEC-notifications.md).

Auth: OAuth2 access token from a service-account JSON file (google-auth), cached until shortly
before it expires. Sending: one POST per device with httpx.

Devices are addressed by their Firebase Installation ID (FID) in `message.fid`; the app registers
with firebase_messaging's register()/onRegistered. `message.token` is deprecated in HTTP v1 and
accepts an FID only for a transition period.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.logging import get_logger
from app.modules.notifications.senders import PushMessage, SendOutcome, SendResult

logger = get_logger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
ANDROID_CHANNEL_ID = "requests"

AccessTokenProvider = Callable[[], Awaitable[str]]


class ServiceAccountTokens:
    """Access tokens for FCM from a service-account file, refreshed off the event loop."""

    def __init__(self, credentials_file: str) -> None:
        from google.oauth2 import service_account

        self._credentials = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=[FCM_SCOPE]
        )
        self._lock = asyncio.Lock()

    async def __call__(self) -> str:
        async with self._lock:
            if not self._credentials.valid:
                from google.auth.transport.requests import Request

                await asyncio.to_thread(self._credentials.refresh, Request())
            return str(self._credentials.token)


def build_payload(message: PushMessage) -> dict[str, Any]:
    return {
        "message": {
            "fid": message.token,
            "notification": {"title": message.title, "body": message.body},
            "data": message.data,
            "android": {
                "priority": "HIGH",
                "notification": {"channel_id": ANDROID_CHANNEL_ID},
            },
        }
    }


def _error_code(response: httpx.Response) -> str | None:
    """FCM puts the precise reason in error.details[].errorCode."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return None
    for detail in error.get("details", []):
        code = detail.get("errorCode")
        if code:
            return str(code)
    return str(error.get("status")) if error.get("status") else None


def classify(response: httpx.Response) -> SendResult:
    status = response.status_code
    if status == 200:
        return SendResult(SendOutcome.OK)
    code = _error_code(response)
    if status == 404 or code == "UNREGISTERED":
        return SendResult(SendOutcome.UNREGISTERED, code or "NOT_FOUND")
    if status == 400 and code == "INVALID_ARGUMENT":
        # A malformed/expired device token is reported this way as well.
        return SendResult(SendOutcome.UNREGISTERED, code)
    if status == 429 or status >= 500 or code in {"UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED"}:
        return SendResult(SendOutcome.RETRY, code or f"HTTP {status}")
    return SendResult(SendOutcome.FATAL, code or f"HTTP {status}")


class FcmSender:
    def __init__(
        self,
        *,
        project_id: str,
        access_token: AccessTokenProvider,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        self._access_token = access_token
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def send(self, message: PushMessage) -> SendResult:
        started = time.perf_counter()
        try:
            token = await self._access_token()
        except Exception as exc:
            logger.error("fcm_auth_failed", error_type=type(exc).__name__)
            return SendResult(SendOutcome.FATAL, "AUTH_FAILED")
        try:
            response = await self._client.post(
                self._url,
                json=build_payload(message),
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            return SendResult(SendOutcome.RETRY, type(exc).__name__)
        result = classify(response)
        logger.info(
            "fcm_send",
            outcome=result.outcome.value,
            error=result.error,
            device=f"…{message.token[-6:]}",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return result

    async def aclose(self) -> None:
        await self._client.aclose()
