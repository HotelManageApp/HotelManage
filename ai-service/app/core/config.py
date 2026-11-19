"""ai-service settings, read from environment variables (and an optional .env file).

Missing or invalid required variables stop the app at startup with a message that names them.
"""

from typing import Any, Literal, Self

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["dev", "test", "prod"]

# Providers are added as their adapters land: "gemini" and "openai" in T39.
LLMProvider = Literal["fake"]


class ConfigError(RuntimeError):
    """Raised when the environment does not provide a valid configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: AppEnv
    app_version: str = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    llm_provider: LLMProvider = "fake"

    @model_validator(mode="after")
    def _no_fake_llm_in_prod(self) -> Self:
        if self.app_env == "prod" and self.llm_provider == "fake":
            raise ValueError("LLM_PROVIDER=fake is not allowed when APP_ENV=prod")
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
