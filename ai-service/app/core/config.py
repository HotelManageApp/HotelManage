"""ai-service settings, read from environment variables (and an optional .env file).

Missing or invalid required variables stop the app at startup with a message that names them.
"""

from typing import Any, Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["dev", "test", "prod"]

LLMProvider = Literal["fake", "gemini", "openai"]


class ConfigError(RuntimeError):
    """Raised when the environment does not provide a valid configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: AppEnv
    app_version: str = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    llm_provider: LLMProvider = "fake"

    # LLM providers (only the key of the chosen provider is required). Keys are never logged.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"
    # One model call; the chat answer must stay under 8 s at p95 (CONSTRAINTS C6).
    llm_timeout_seconds: float = Field(default=7.0, gt=0, le=60)

    # backend-api on the internal network; called with the guest's own token only.
    backend_internal_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    backend_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    # Local time put into the concierge prompt ("now=...").
    hotel_timezone: str = "Asia/Ho_Chi_Minh"

    @model_validator(mode="after")
    def _no_fake_llm_in_prod(self) -> Self:
        if self.app_env == "prod" and self.llm_provider == "fake":
            raise ValueError("LLM_PROVIDER=fake is not allowed when APP_ENV=prod")
        return self

    @model_validator(mode="after")
    def _provider_key_present(self) -> Self:
        key = {"gemini": self.gemini_api_key, "openai": self.openai_api_key}.get(self.llm_provider)
        if self.llm_provider != "fake" and (key is None or not key.get_secret_value()):
            raise ValueError(
                f"{self.llm_provider.upper()}_API_KEY is required when "
                f"LLM_PROVIDER={self.llm_provider}"
            )
        return self


def load_settings(**overrides: Any) -> Settings:
    """Build Settings, turning pydantic's error into one readable ConfigError."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        missing: list[str] = []
        invalid: list[str] = []
        for error in exc.errors():
            name = ".".join(str(part) for part in error["loc"]).upper() or "SETTINGS"
            if error["type"] == "missing":
                missing.append(name)
            else:
                invalid.append(f"{name} ({error['msg']})")
        parts = []
        if missing:
            parts.append("missing required environment variable(s): " + ", ".join(missing))
        if invalid:
            parts.append("invalid environment variable(s): " + ", ".join(invalid))
        raise ConfigError("; ".join(parts)) from None
