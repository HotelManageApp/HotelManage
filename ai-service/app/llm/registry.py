"""Pick the LLM adapter from settings (LLM_PROVIDER)."""

from collections.abc import Callable

from app.core.config import Settings
from app.llm.base import LLMClient
from app.llm.fake import FakeLLMClient
from app.llm.gemini import GeminiClient
from app.llm.openai import OpenAIClient


def _secret(value: object) -> str:
    # Settings guarantees the chosen provider's key is present.
    return value.get_secret_value() if hasattr(value, "get_secret_value") else ""


_FACTORIES: dict[str, Callable[[Settings], LLMClient]] = {
    "fake": lambda _settings: FakeLLMClient(),
    "gemini": lambda s: GeminiClient(
        api_key=_secret(s.gemini_api_key),
        model=s.gemini_model,
        timeout_seconds=s.llm_timeout_seconds,
    ),
    "openai": lambda s: OpenAIClient(
        api_key=_secret(s.openai_api_key),
        model=s.openai_model,
        timeout_seconds=s.llm_timeout_seconds,
    ),
}


def create_llm_client(settings: Settings) -> LLMClient:
    try:
        factory = _FACTORIES[settings.llm_provider]
    except KeyError:
        raise ValueError(f"no LLM adapter registered for {settings.llm_provider!r}") from None
    return factory(settings)
