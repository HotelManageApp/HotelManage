"""Push senders. `PushSender.send` never raises; it reports what happened."""

import enum
from dataclasses import dataclass, field
from typing import Protocol

from app.core.logging import get_logger

logger = get_logger(__name__)


class SendOutcome(enum.StrEnum):
    OK = "OK"
    UNREGISTERED = "UNREGISTERED"  # app uninstalled / token rotated: forget it
    RETRY = "RETRY"  # 429, 5xx, network: try again later
    FATAL = "FATAL"  # bad credentials or request: retrying will not help


@dataclass(frozen=True)
class PushMessage:
    token: str
    title: str
    body: str
    data: dict[str, str]


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    error: str | None = None


class PushSender(Protocol):
    async def send(self, message: PushMessage) -> SendResult: ...


def _token_tail(token: str) -> str:
    return f"…{token[-6:]}"


class LogSender:
    """Development sender: writes the message to the log instead of calling Google."""

    async def send(self, message: PushMessage) -> SendResult:
        logger.info(
            "push_logged",
            device=_token_tail(message.token),
            title=message.title,
            push_body=message.body,
            data=message.data,
        )
        return SendResult(SendOutcome.OK)


@dataclass
class FakePushSender:
    """Test sender: records messages; scripted outcomes are consumed in order (default OK)."""

    outcomes: list[SendOutcome] = field(default_factory=list)
    sent: list[PushMessage] = field(default_factory=list)

    async def send(self, message: PushMessage) -> SendResult:
        self.sent.append(message)
        outcome = self.outcomes.pop(0) if self.outcomes else SendOutcome.OK
        return SendResult(outcome, None if outcome is SendOutcome.OK else outcome.value)
