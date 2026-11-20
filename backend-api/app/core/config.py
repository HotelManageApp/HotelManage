"""Application settings, read from environment variables (and an optional .env file).

Missing or invalid required variables stop the app at startup with a message that names them.
"""

from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["dev", "test", "prod"]


class ConfigError(RuntimeError):
    """Raised when the environment does not provide a valid configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: AppEnv
    database_url: str
    app_version: str = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    db_health_timeout_seconds: float = 2.0
    hotel_timezone: str = "Asia/Ho_Chi_Minh"

    # Staff authentication (spec/SPEC-staff-auth.md). Secret is never shared with guest tokens.
    staff_jwt_secret: SecretStr = Field(min_length=32)
    staff_access_token_minutes: int = Field(default=15, ge=1, le=60)
    staff_refresh_token_hours: int = Field(default=12, ge=1, le=72)
    admin_web_origins: list[str] = ["http://localhost:3000"]

    # Guest access (spec/SPEC-stay-access.md). Never reuse the staff secret.
    stay_jwt_secret: SecretStr = Field(min_length=32)
    room_code_pepper: SecretStr = Field(min_length=32)
    stay_grace_hours: int = Field(default=6, ge=0, le=48)
    max_devices_per_stay: int = Field(default=6, ge=1, le=20)

    # Notifications (spec/SPEC-notifications.md)
    fcm_sender: Literal["log", "fcm"] = "log"
    fcm_project_id: str | None = None
    fcm_credentials_file: str | None = None
    notifications_worker_enabled: bool = True

    @model_validator(mode="after")
    def _fcm_needs_project_and_credentials(self) -> "Settings":
        if self.fcm_sender == "fcm" and not (self.fcm_project_id and self.fcm_credentials_file):
            raise ValueError("FCM_SENDER=fcm needs FCM_PROJECT_ID and FCM_CREDENTIALS_FILE")
        return self

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("must start with postgresql+asyncpg://")
        return value


def load_settings(**overrides: Any) -> Settings:
    """Build Settings, turning pydantic's error into one readable ConfigError."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        missing: list[str] = []
        invalid: list[str] = []
        for error in exc.errors():
            name = ".".join(str(part) for part in error["loc"]).upper()
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
