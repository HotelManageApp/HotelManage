import pytest

from app.core.config import ConfigError, load_settings
from app.main import create_app


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> pytest.MonkeyPatch:
    """No .env file in cwd and no relevant variables in the environment."""
    monkeypatch.chdir(tmp_path)
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "APP_VERSION",
        "LOG_LEVEL",
        "STAFF_JWT_SECRET",
        "STAY_JWT_SECRET",
        "ROOM_CODE_PEPPER",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_missing_required_variables_are_named(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings()
    message = str(exc_info.value)
    assert "DATABASE_URL" in message
    assert "APP_ENV" in message
    assert "STAFF_JWT_SECRET" in message


def test_app_does_not_start_without_database_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "dev")
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        create_app()


def test_database_url_must_use_asyncpg(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "dev")
    clean_env.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    with pytest.raises(ConfigError, match="invalid environment variable.*DATABASE_URL"):
        load_settings()


def test_reads_valid_environment(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "prod")
    clean_env.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/hotel")
    clean_env.setenv("APP_VERSION", "abc123")
    clean_env.setenv("STAFF_JWT_SECRET", "s" * 40)
    clean_env.setenv("STAY_JWT_SECRET", "t" * 40)
    clean_env.setenv("ROOM_CODE_PEPPER", "p" * 40)
    settings = load_settings()
    assert settings.app_env == "prod"
    assert settings.app_version == "abc123"
    assert settings.log_level == "INFO"


def test_lazy_module_app_is_built_from_environment(clean_env: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    clean_env.setenv("APP_ENV", "prod")
    clean_env.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/hotel")
    clean_env.setenv("STAFF_JWT_SECRET", "s" * 40)
    clean_env.setenv("STAY_JWT_SECRET", "t" * 40)
    clean_env.setenv("ROOM_CODE_PEPPER", "p" * 40)
    clean_env.setattr(main_module, "_app", None)
    built = main_module.app
    assert built is main_module.app
    assert built.docs_url is None  # API docs are hidden in prod
    assert not hasattr(main_module, "not_an_attribute")


def test_short_staff_secret_is_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "dev")
    clean_env.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/hotel")
    clean_env.setenv("STAFF_JWT_SECRET", "too-short")
    with pytest.raises(ConfigError, match="STAFF_JWT_SECRET"):
        load_settings()


def test_secret_is_not_printed(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "dev")
    clean_env.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/hotel")
    clean_env.setenv("STAFF_JWT_SECRET", "s" * 40)
    clean_env.setenv("STAY_JWT_SECRET", "t" * 40)
    clean_env.setenv("ROOM_CODE_PEPPER", "p" * 40)
    assert "s" * 40 not in repr(load_settings())
