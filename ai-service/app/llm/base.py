"""Provider-neutral LLM interface.

The concierge orchestrator (T40) only talks to `LLMClient`; provider adapters (T39) translate these
types to and from Gemini / OpenAI payloads.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
ToolChoice = Literal["auto", "required", "none"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # set when role == "tool"


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    structured: dict[str, Any] | None = None  # parsed JSON when a response_schema was requested
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMRequest:
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: ToolChoice = "auto"
    response_schema: dict[str, Any] | None = None
    temperature: float = 0.2


class LLMError(RuntimeError):
    """The provider failed or returned something unusable."""


class LLMTimeout(LLMError):
    """The provider did not answer in time."""


class LLMClient(ABC):
    provider: str

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Run one model turn. Raises LLMTimeout / LLMError on failure."""
