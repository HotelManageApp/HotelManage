"""What every concierge tool shares (SPEC-concierge-actions, "Bộ tool" and "Code Style").

A tool declares its schema, a Pydantic model with `extra="forbid"`, and two flags the
orchestrator relies on — never per-tool conditions:

    write                  creates or changes something for the guest; left out of the tool list
                           sent to the model while the stay is CHECKOUT_PENDING
    requires_confirmation  (a `gate` is set) goes through the server-side confirmation gate,
                           see concierge/confirmation.py

`execute` is the only way a tool runs:

    unknown argument (room_id, stay_id, price_vnd…) -> VALIDATION_ERROR, backend not called,
                                                       `tool_arg_rejected` logged (names only)
    invalid value                                   -> VALIDATION_ERROR, backend not called
    backend 401                                     -> BackendUnauthorized (the chat answers 401)
    backend 400 / 403 / 404                         -> VALIDATION_ERROR / FORBIDDEN / NOT_FOUND
    backend 409                                     -> its own code (ITEM_UNAVAILABLE, CONFLICT…)
    backend 429 / 5xx / timeout                     -> UPSTREAM_ERROR

Every call carries the guest's own token; no tool has a room or stay argument (C4.1).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.backend_client import (
    BackendClient,
    BackendError,
    BackendUnauthorized,
    BackendUnavailable,
)
from app.core.logging import get_logger
from app.llm.base import ToolSpec

logger = get_logger(__name__)

# (backend, token, parsed args, lang, **extra) -> tool `data`; a gated tool's runner gets
# `idempotency_key=` and only runs once the guest confirmed.
Runner = Callable[..., Awaitable[dict[str, Any]]]
Summary = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Gate:
    """How a tool goes through the confirmation gate."""

    kind: str  # FOOD_ORDER | CHECKOUT
    payload: Callable[[Any], dict[str, Any]]  # parsed args -> what the guest confirms (hashed)
    preview: Runner  # (backend, token, parsed args, lang) -> summary shown to the guest


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    args_model: type[BaseModel]
    runner: Runner
    write: bool = False
    gate: Gate | None = None
    # What the stored trace keeps of `data`; called with {} when the call failed.
    summarize: Summary | None = None

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def requires_confirmation(self) -> bool:
        return self.gate is not None


@dataclass
class ToolRun:
    """One executed (or refused) call, kept for grounding and for the stored trace (no token)."""

    name: str
    args: dict[str, Any]
    output: dict[str, Any]
    rejected_args: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.output.get("ok"))

    @property
    def error_code(self) -> str | None:
        error = self.output.get("error")
        return error.get("code") if isinstance(error, dict) else None

    def trace(self) -> dict[str, Any]:
        return {
            "tool": self.name,
            "args": self.args,
            **({"error": self.error_code} if self.error_code else {}),
            **self.summary,
            **({"rejected_args": self.rejected_args} if self.rejected_args else {}),
        }


def error(code: str, message: str = "") -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def backend_error_code(exc: BackendError) -> str:
    if isinstance(exc, BackendUnavailable) or exc.status in (0, 429) or exc.status >= 500:
        return "UPSTREAM_ERROR"
    if exc.status == 400 or exc.status == 422:
        return "VALIDATION_ERROR"
    if exc.status == 403:
        return "FORBIDDEN"
    if exc.status == 404:
        return "NOT_FOUND"
    if exc.status == 409:
        return exc.code or "CONFLICT"
    return "UPSTREAM_ERROR"


def _failed(
    tool: Tool, args: dict[str, Any], output: dict[str, Any], rejected: list[str] | None = None
) -> ToolRun:
    summary = tool.summarize({}) if tool.summarize else {}
    return ToolRun(tool.name, args, output, rejected or [], summary)


def validate(tool: Tool, raw_args: Any) -> BaseModel | ToolRun:
    """The parsed arguments, or the refused run (the backend is not called)."""
    raw = raw_args if isinstance(raw_args, dict) else {}
    known = set(tool.spec.input_schema.get("properties", {}))
    rejected = sorted(str(k) for k in raw if k not in known)
    if rejected:
        logger.warning("tool_arg_rejected", tool=tool.name, args=rejected)
        kept = {k: v for k, v in raw.items() if k in known}
        message = "unknown arguments: " + ", ".join(rejected)
        return _failed(tool, kept, error("VALIDATION_ERROR", message), rejected)
    try:
        return tool.args_model.model_validate(raw)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "arguments" for e in exc.errors()})
        return _failed(tool, raw, error("VALIDATION_ERROR", ", ".join(fields)))


def args_of(parsed: BaseModel) -> dict[str, Any]:
    return parsed.model_dump(exclude_none=True, mode="json")


async def call(
    tool: Tool,
    runner: Runner,
    backend: BackendClient,
    token: str,
    parsed: BaseModel,
    lang: str,
    **extra: Any,
) -> ToolRun:
    """Run `runner` and map backend errors to tool error codes."""
    args = args_of(parsed)
    try:
        data = await runner(backend, token, parsed, lang, **extra)
    except BackendUnauthorized:
        raise  # the session ended mid-chat: the whole request answers 401
    except BackendError as exc:
        return _failed(tool, args, error(backend_error_code(exc), exc.code))
    summary = tool.summarize(data) if tool.summarize else {}
    return ToolRun(tool.name, args, {"ok": True, "data": data}, summary=summary)


async def execute(
    tool: Tool, backend: BackendClient, token: str, raw_args: Any, lang: str
) -> ToolRun:
    """Run an ungated tool. Gated tools go through `confirmation.Gatekeeper` instead."""
    if tool.gate is not None:
        raise ValueError(f"{tool.name} must go through the confirmation gate")
    parsed = validate(tool, raw_args)
    if isinstance(parsed, ToolRun):
        return parsed
    return await call(tool, tool.runner, backend, token, parsed, lang)
