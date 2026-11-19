"""Deterministic LLM client for tests and local development (no network, no API key).

Responses are scripted in order; every request is recorded so tests can assert on prompts and tools.
With an empty script it answers with a fixed text so the dev server works without a provider.
"""

from collections import deque
from collections.abc import Iterable

from app.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse

DEFAULT_REPLY = "Xin chào, đây là phản hồi thử nghiệm (FakeLLMClient)."


class FakeLLMClient(LLMClient):
    provider = "fake"

    def __init__(self, responses: Iterable[LLMResponse | Exception] = ()) -> None:
        self._script: deque[LLMResponse | Exception] = deque(responses)
        self.requests: list[LLMRequest] = []

    def queue(self, *responses: LLMResponse | Exception) -> None:
        self._script.extend(responses)

    @property
    def remaining(self) -> int:
        return len(self._script)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._script:
            return LLMResponse(text=DEFAULT_REPLY)
        item = self._script.popleft()
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, LLMResponse):
            raise LLMError(f"unexpected scripted item: {type(item).__name__}")
        return item
