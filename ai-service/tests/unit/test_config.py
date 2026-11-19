import pytest

from app.core.config import ConfigError, load_settings
from app.main import create_app


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> pytest.MonkeyPatch:
    """No .env file in cwd and no relevant variables in the environment."""
    monkeypatch.chdir(tmp_path)
    for name in ("APP_ENV", "APP_VERSION", "LOG_LEVEL", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_missing_app_env_is_named(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="missing required environment variable.*APP_ENV"):
        load_settings()


def test_app_does_not_start_without_app_env(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="APP_ENV"):
        create_app()


def test_unknown_llm_provider_is_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "dev")
    clean_env.setenv("LLM_PROVIDER", "skynet")
    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        load_settings()


def test_fake_llm_is_refused_in_prod(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "prod")
    clean_env.setenv("LLM_PROVIDER", "fake")
    with pytest.raises(ConfigError, match="not allowed when APP_ENV=prod"):
        load_settings()


def test_dev_defaults(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "dev")
    settings = load_settings()
    assert settings.llm_provider == "fake"
    assert settings.log_level == "INFO"


def test_lazy_module_app_is_built_from_environment(clean_env: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    clean_env.setenv("APP_ENV", "dev")
    clean_env.setattr(main_module, "_app", None)
    built = main_module.app
    assert built is main_module.app
    assert built.docs_url == "/docs"
    assert not hasattr(main_module, "not_an_attribute")
