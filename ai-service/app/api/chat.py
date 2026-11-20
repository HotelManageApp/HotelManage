"""POST /api/v1/chat — the guest app's concierge endpoint (SPEC-concierge-guide)."""

import asyncio
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app.concierge.orchestrator import Orchestrator
from app.core.backend_client import (
    BackendClient,
    BackendError,
    BackendRateLimited,
    BackendUnauthorized,
    BackendUnavailable,
)
from app.core.errors import AppError, RateLimited, Unauthorized
from app.core.logging import get_logger
from app.llm.base import LLMError, LLMTimeout

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])

TOTAL_TIMEOUT_SECONDS = 12.0
HISTORY_TURNS = 10


class ChatDisabled(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "CHAT_DISABLED"
    message = "Trợ lý ảo đang tạm tắt, Quý khách vui lòng liên hệ Lễ tân"


class LlmTimedOut(AppError):
    status_code = HTTPStatus.GATEWAY_TIMEOUT
    code = "LLM_TIMEOUT"
    message = "Hệ thống đang bận, Quý khách vui lòng thử lại hoặc gọi Lễ tân"


class LlmUnavailable(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "LLM_UNAVAILABLE"
    message = "Hệ thống đang bận, Quý khách vui lòng thử lại hoặc gọi Lễ tân"


class BackendDown(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "BACKEND_UNAVAILABLE"
    message = "Hệ thống đang bận, Quý khách vui lòng thử lại sau"


class ChatRequest(BaseModel):
    """Unknown fields (room_id included) are refused: the room comes from the token (C4.1)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=1000)
    client_message_id: uuid.UUID | None = None
    # The app's "Xác nhận" button on a summary card (SPEC-concierge-actions).
    confirm_action_id: uuid.UUID | None = None


class SuggestedAction(BaseModel):
    type: str  # OPEN_SCREEN | CALL | OPEN_ENTITY
    target: str
    entity_id: str | None = None  # OPEN_ENTITY: the order / request just created


class PendingConfirmation(BaseModel):
    id: str
    kind: str  # FOOD_ORDER | CHECKOUT
    summary: dict[str, Any]


class ChatResponse(BaseModel):
    message_id: str
    reply: str
    lang: str
    suggested_actions: list[SuggestedAction]
    pending_confirmation: PendingConfirmation | None = None
    debug: dict[str, Any] | None = None


def _token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized()
    return token.strip()


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
async def chat(
    body: ChatRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> ChatResponse:
    token = _token(authorization)
    settings = request.app.state.settings
    backend: BackendClient = request.app.state.backend
    orchestrator: Orchestrator = request.app.state.orchestrator
    started = time.perf_counter()

    try:
        guest = await backend.me(token)
        info = await backend.hotel_info(token)
        if not info.chat_enabled:
            raise ChatDisabled()
        await backend.take_quota(token)
        history = await backend.history(token, limit=HISTORY_TURNS)
        try:
            async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
                turn = await orchestrator.answer(
                    token=token,
                    message=body.message,
                    guest=guest,
                    info=info,
                    history=history,
                    now=datetime.now(ZoneInfo(settings.hotel_timezone)),
                    confirm_action_id=(
                        body.confirm_action_id.hex if body.confirm_action_id else None
                    ),
                )
        except (TimeoutError, LLMTimeout):
            raise LlmTimedOut() from None
        except LLMError as exc:
            logger.warning("llm_failed", error=str(exc))
            raise LlmUnavailable() from None
        message_id = await backend.save_exchange(
            token,
            guest_message=body.message,
            assistant_message=turn.reply,
            tool_trace=turn.trace() or None,
            grounded=turn.grounded,
            client_message_id=body.client_message_id,
        )
    except BackendUnauthorized as exc:
        raise Unauthorized(exc.message or None) from None
    except BackendRateLimited as exc:
        raise RateLimited(
            exc.message or None, retry_after_seconds=exc.retry_after_seconds
        ) from None
    except (BackendUnavailable, BackendError):
        raise BackendDown() from None

    logger.info(
        "chat_answered",
        message_id=message_id,
        message_length=len(body.message),
        reply_length=len(turn.reply),
        tools=[r.name for r in turn.tool_runs],
        grounded=turn.grounded,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    debug = None
    if settings.app_env in ("dev", "test"):
        debug = {
            "tool_calls": [{"name": r.name, "args": r.args} for r in turn.tool_runs],
            "grounded": turn.grounded,
            "forced_tool": turn.forced_tool,
            **({"gate": turn.gate.events} if turn.gate and turn.gate.events else {}),
        }
    return ChatResponse(
        message_id=message_id,
        reply=turn.reply,
        lang=guest.lang,
        suggested_actions=[SuggestedAction(**a) for a in turn.suggested_actions],
        pending_confirmation=(
            PendingConfirmation(**turn.pending_confirmation) if turn.pending_confirmation else None
        ),
        debug=debug,
    )
