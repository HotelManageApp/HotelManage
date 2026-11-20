"""Server-side guards around the model (SPEC-concierge-actions, "Chống prompt injection"; C2.6).

    canary         a random marker put in the system prompt at start-up; a reply that contains
                   it, or any run of more than 40 characters copied from the system prompt, is
                   replaced by a refusal and `prompt_leak_blocked` is logged
    tool budget    at most 4 tool calls per guest message, and at most one write tool actually
                   executed (an order placed, a request created); further calls get an error
                   result instead of running

These do not rely on the model following the prompt.
"""

import re
import secrets
import unicodedata
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_TOOL_CALLS = 4
MAX_WRITES = 1
LEAK_WINDOW = 41  # characters: "more than 40" copied from the system prompt

REFUSAL = {
    "vi": "Xin lỗi, tôi không thể chia sẻ thông tin đó. Tôi có thể giúp gì khác cho Quý khách?",
    "en": "Sorry, I can't share that. Is there anything else I can help you with?",
}


def new_canary() -> str:
    return f"cnry-{secrets.token_hex(8)}"


def _flat(text: str) -> str:
    """Lower case, accents kept, every run of whitespace/punctuation -> one space."""
    text = unicodedata.normalize("NFC", text.lower())
    return re.sub(r"[\W_]+", " ", text).strip()


class LeakGuard:
    """Detects a reply that leaks the system prompt."""

    def __init__(self, canary: str) -> None:
        self.canary = canary

    def leaks(self, reply: str, system_prompt: str) -> bool:
        if not reply:
            return False
        if self.canary.lower() in reply.lower():
            return True
        flat_reply = _flat(reply)
        if len(flat_reply) < LEAK_WINDOW:
            return False
        flat_prompt = _flat(system_prompt)
        windows = {
            flat_prompt[i : i + LEAK_WINDOW] for i in range(len(flat_prompt) - LEAK_WINDOW + 1)
        }
        return any(
            flat_reply[i : i + LEAK_WINDOW] in windows
            for i in range(len(flat_reply) - LEAK_WINDOW + 1)
        )

    def check(self, reply: str, system_prompt: str, lang: str) -> tuple[str, bool]:
        """(reply to send, blocked?)."""
        if not self.leaks(reply, system_prompt):
            return reply, False
        logger.warning("prompt_leak_blocked", reply_length=len(reply))
        return REFUSAL.get(lang.split("-")[0].lower(), REFUSAL["en"]), True


@dataclass
class ToolBudget:
    """Counts one guest message's tool calls and executed writes."""

    calls: int = 0
    writes: int = 0

    def take_call(self) -> bool:
        if self.calls >= MAX_TOOL_CALLS:
            return False
        self.calls += 1
        return True

    def can_write(self) -> bool:
        return self.writes < MAX_WRITES

    def wrote(self) -> None:
        self.writes += 1
