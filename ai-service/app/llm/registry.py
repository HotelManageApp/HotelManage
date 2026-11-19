"""Pick the LLM adapter from settings (LLM_PROVIDER)."""

from collections.abc import Callable

from app.core.config import Settings
from app.llm.base import LLMClient
from app.llm.fake import FakeLLMClient

_FACTORIES: dict[str, Callable[[Settings], LLMClient]] = {
    "fake": lambda _settings: FakeLLMClient(),
}


def create_llm_client(settings: Settings) -> LLMClient:
    try:
        factory = _FACTORIES[settings.llm_provider]
    except KeyError:
        raise ValueError(f"no LLM adapter registered for {settings.llm_provider!r}") from None
    return factory(settings)
