"""Auth settings: safe defaults, and production refuses insecure configuration."""

import pytest

from app.core.config import Settings, get_settings
from app.main import create_app


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


@pytest.fixture
def env(monkeypatch):
    def apply(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("environment", "secure"), [("development", False), ("test", True), ("production", True)]
)
def test_cookie_secure_defaults_by_environment(environment: str, secure: bool) -> None:
    assert settings(environment=environment).session_cookie_is_secure is secure


def test_cookie_secure_can_be_enabled_in_development() -> None:
    assert settings(environment="development", session_cookie_secure=True).session_cookie_is_secure


def test_default_allowlist_is_the_local_frontend() -> None:
    assert settings().allowed_origins == ["http://localhost:3000"]


def test_allowlist_is_read_from_the_environment(env) -> None:
    env(ALLOWED_ORIGINS='["https://app.example.com","http://localhost:3000"]')
    assert get_settings().allowed_origins == ["https://app.example.com", "http://localhost:3000"]


def test_production_refuses_an_insecure_cookie(env) -> None:
    env(ENVIRONMENT="production", TRUSTED_PROXY_HOPS="1", SESSION_COOKIE_SECURE="false")
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_SECURE"):
        create_app()


def test_production_requires_an_explicit_proxy_hop_count(env, monkeypatch) -> None:
    env(ENVIRONMENT="production")
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_HOPS"):
        create_app()


def test_production_starts_when_configured(env) -> None:
    env(ENVIRONMENT="production", TRUSTED_PROXY_HOPS="1", SESSION_COOKIE_SECURE="true")
    create_app()


def test_default_throttle_limits() -> None:
    defaults = settings()
    assert defaults.login_window_minutes == 15
    assert defaults.login_limit_per_account_ip == 5
    assert defaults.login_limit_per_account == 50
    assert defaults.login_limit_per_ip == 20
    assert defaults.signup_window_minutes == 60
    assert defaults.signup_limit_per_ip == 5


@pytest.mark.parametrize("name", ["TRUSTED_PROXY_HOPS", "SESSION_COOKIE_SECURE"])
def test_blank_value_means_not_configured(name: str, monkeypatch) -> None:
    monkeypatch.setenv(name, "")
    assert getattr(settings(), name.lower()) is None
