"""HTTP plumbing shared by the provider adapters (plain httpx, no provider SDK)."""

import time
from typing import Any

import httpx

from app.core.logging import get_logger
from app.llm.base import LLMError, LLMTimeout

logger = get_logger(__name__)


class LLMHttpError(LLMError):
    """The provider answered with an HTTP error. `retryable` for 429/5xx."""

    def __init__(self, provider: str, status: int, reason: str) -> None:
        super().__init__(f"{provider} answered {status}: {reason}")
        self.status = status
        self.retryable = status == 429 or status >= 500


async def post_json(
    http: httpx.AsyncClient,
    provider: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
) -> dict[str, Any]:
    """POST and return the JSON body. Never puts the API key or the prompt in errors or logs."""
    started = time.perf_counter()
    try:
        response = await http.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        raise LLMTimeout(f"{provider} did not answer in time") from None
    except httpx.HTTPError as exc:
        raise LLMError(f"{provider} unreachable: {type(exc).__name__}") from None
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        reason = _reason(response)
        logger.warning(
            "llm_http_error",
            provider=provider,
            status=response.status_code,
            reason=reason,
            duration_ms=elapsed_ms,
        )
        raise LLMHttpError(provider, response.status_code, reason)
    logger.info("llm_call", provider=provider, duration_ms=elapsed_ms)
    try:
        data = response.json()
    except ValueError:
        raise LLMError(f"{provider} returned a body that is not JSON") from None
    if not isinstance(data, dict):
        raise LLMError(f"{provider} returned an unexpected body")
    return data


def _reason(response: httpx.Response) -> str:
    """The provider's short error status/type, e.g. RESOURCE_EXHAUSTED or invalid_request_error."""
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return "unreadable error body"
    if isinstance(error, dict):
        return str(error.get("status") or error.get("type") or error.get("code") or "error")[:80]
    return "error"
