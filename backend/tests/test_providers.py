"""The provider contract, run against the mock, and the rules for choosing a provider."""

import inspect
import json
import logging

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.logs import configure_logging
from app.main import create_app
from app.modules.providers import selection
from app.modules.providers.contract import (
    KNOWN_ERRORS,
    Completion,
    Message,
    Provider,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    Role,
    TextPiece,
    ToolCall,
)
from app.modules.providers.gemini import GeminiProvider
from app.modules.providers.mock import MockProvider
from app.modules.providers.spending import MeteredProvider

MESSAGES = [Message(Role.SYSTEM, "Rules"), Message(Role.USER, "Hello")]


def complete(provider: Provider, **overrides) -> Completion:
    return provider.complete(
        MESSAGES, **({"timeout_seconds": 5, "max_output_tokens": 500} | overrides)
    )


def test_the_contract_is_what_chat_needs_too() -> None:
    """Slice 3.1 adds an adapter behind this call without changing it."""
    for implementation in (Provider, MockProvider):
        parameters = inspect.signature(implementation.complete).parameters
        assert list(parameters) == ["self", "messages", "timeout_seconds", "max_output_tokens"]
        for name in ("timeout_seconds", "max_output_tokens"):
            assert parameters[name].default is inspect.Parameter.empty
            assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_messages_have_the_roles_chat_needs_and_no_others() -> None:
    assert [role.value for role in Role] == ["system", "user", "assistant"]
    chat = [*MESSAGES, Message(Role.ASSISTANT, "Hi"), Message(Role.USER, "Bye")]
    completion = MockProvider().complete(chat, timeout_seconds=5, max_output_tokens=500)
    assert completion.input_tokens == 4  # "RulesHelloHiBye"
    with pytest.raises(ValueError, match="tool"):
        Message("tool", "x")


def test_the_mock_is_deterministic_and_counts_tokens() -> None:
    first = complete(MockProvider())
    assert first == complete(MockProvider())
    assert json.loads(first.text)["name"] == "Sample agent"
    assert first.input_tokens == 3 and first.output_tokens > 0  # "RulesHello"


def test_the_mock_stops_at_the_token_limit() -> None:
    short = complete(MockProvider(), max_output_tokens=2)
    assert (len(short.text), short.output_tokens) == (8, 2)


@pytest.mark.parametrize(
    ("scenario", "error", "status", "code"),
    [
        ("timeout", ProviderTimeoutError, 504, "provider_timeout"),
        ("rate_limited", ProviderRateLimitError, 503, "provider_rate_limited"),
        ("unavailable", ProviderError, 503, "provider_unavailable"),
    ],
)
def test_the_mock_simulates_failures(scenario, error, status, code) -> None:
    with pytest.raises(error) as caught:
        complete(MockProvider(scenario))
    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_private_text_is_not_in_reprs() -> None:
    assert "secret" not in repr(Message(Role.USER, "secret"))
    assert "secret" not in repr(Completion("secret", 1, 1))


def test_provider_errors_cannot_carry_provider_text() -> None:
    with pytest.raises(TypeError):
        ProviderError("secret")


@pytest.fixture
def env(monkeypatch):
    def apply(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def test_no_provider_by_default() -> None:
    assert Settings(_env_file=None, model_provider="").model_provider is None
    assert Settings.model_fields["model_provider"].default is None


def test_configuration_chooses_the_provider(env) -> None:
    env(MODEL_PROVIDER="mock", MOCK_PROVIDER_SCENARIO="timeout")
    with pytest.raises(ProviderTimeoutError):
        complete(selection.get_provider())
    env(MODEL_PROVIDER="")
    assert selection.get_provider() is None


def test_production_refuses_the_mock(env) -> None:
    env(
        ENVIRONMENT="production",
        TRUSTED_PROXY_HOPS="1",
        SESSION_COOKIE_SECURE="true",
        MODEL_PROVIDER="mock",
    )
    with pytest.raises(RuntimeError, match="MODEL_PROVIDER"):
        create_app()
    env(MODEL_PROVIDER="")
    create_app()


@pytest.mark.parametrize(
    "values",
    [
        {"model_provider": "openai"},
        {"mock_provider_scenario": "x"},
        {"provider_timeout_seconds": 26},
        {"generation_limit_per_user": 0},
        {"generation_limit_per_workspace": 0},
        {"generation_window_minutes": 0},
    ],
)
def test_bad_settings_stop_startup(values) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


# Streaming


def test_every_provider_streams_with_the_same_parameters() -> None:
    for implementation in (Provider, MockProvider, GeminiProvider, MeteredProvider):
        for method in (implementation.complete, implementation.stream):
            parameters = list(inspect.signature(method).parameters)
            assert parameters == ["self", "messages", "timeout_seconds", "max_output_tokens"]


def test_the_mock_streams_what_it_completes() -> None:
    limits = {"timeout_seconds": 5, "max_output_tokens": 500}
    *pieces, last = MockProvider().stream(MESSAGES, **limits)
    assert len(pieces) > 1 and all(isinstance(piece, TextPiece) for piece in pieces)
    assert last == complete(MockProvider())
    assert "".join(piece.text for piece in pieces) == last.text
    cancelled = MockProvider().stream(MESSAGES, **limits)
    next(cancelled)
    cancelled.close()
    with pytest.raises(StopIteration):
        next(cancelled)
    with pytest.raises(ProviderTimeoutError):
        next(MockProvider("timeout").stream(MESSAGES, **limits))


def test_tool_calls_are_private_text_too() -> None:
    call = ToolCall("1", "secret", "secret")
    assert "secret" not in repr(call) + repr(TextPiece("secret"))
    assert "secret" not in repr(Completion("secret", 1, 1, (call,)))


def test_every_known_error_has_its_own_code() -> None:
    codes = {error.code for error in KNOWN_ERRORS}
    assert len(codes) == len(KNOWN_ERRORS)


# Gemini setup


GEMINI = {
    "ENVIRONMENT": "development",
    "MODEL_PROVIDER": "gemini",
    "GEMINI_API_KEY": "AIza-SECRET",
}


@pytest.fixture
def gemini_env(env, monkeypatch):
    monkeypatch.setattr(selection, "get_session_factory", lambda: None)
    selection._gemini.cache_clear()
    yield lambda **values: env(**(GEMINI | values))
    selection._gemini.cache_clear()


def test_gemini_is_always_behind_the_spending_limit(gemini_env) -> None:
    gemini_env()
    provider = selection.get_provider()
    assert type(provider) is MeteredProvider and type(provider._inner) is GeminiProvider
    create_app()


def test_gemini_is_built_once_until_its_setup_changes(gemini_env) -> None:
    gemini_env()
    first = selection.get_provider()
    assert selection.get_provider() is first
    gemini_env(GEMINI_API_KEY="AIza-OTHER")
    second = selection.get_provider()
    assert second is not first and second._inner._api_key == "AIza-OTHER"
    gemini_env(GEMINI_MODEL="gemini-3.8-flash")
    assert selection.get_provider()._spec.name == "gemini-3.8-flash"


def test_the_tests_never_see_a_real_provider_or_key() -> None:
    settings = Settings()
    assert settings.model_provider is None and settings.gemini_api_key is None


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"GEMINI_API_KEY": ""}, "GEMINI_API_KEY must be set"),
        ({"GEMINI_API_KEY": "AIza SECRET"}, "GEMINI_API_KEY holds"),
        ({"GEMINI_API_KEY": "SECRET\r\nX: y"}, "GEMINI_API_KEY holds"),
        ({"GEMINI_API_KEY": "SECRETé"}, "GEMINI_API_KEY holds"),
        ({"GEMINI_MODEL": "gemini-2.5-flash"}, "GEMINI_MODEL"),
        ({"GEMINI_MODEL": "../../x"}, "GEMINI_MODEL"),
    ],
)
def test_an_unusable_gemini_setup_stops_startup(gemini_env, values, message) -> None:
    gemini_env(**values)
    with pytest.raises(RuntimeError, match=message) as caught:
        create_app()
    assert "SECRET" not in str(caught.value)


def test_production_refuses_the_free_tier(gemini_env) -> None:
    production = {
        "ENVIRONMENT": "production",
        "TRUSTED_PROXY_HOPS": "1",
        "SESSION_COOKIE_SECURE": "true",
    }
    gemini_env(**production)
    with pytest.raises(RuntimeError, match="GEMINI_TIER"):
        create_app()
    gemini_env(**production, GEMINI_TIER="paid")
    create_app()


def test_the_tier_is_free_unless_declared() -> None:
    assert Settings.model_fields["gemini_tier"].default == "free"


def test_the_disclosure_follows_the_settings(gemini_env) -> None:
    gemini_env()
    assert selection.current_disclosure() == "gemini_free"
    gemini_env(GEMINI_TIER="paid")
    assert selection.current_disclosure() == "gemini_paid"
    for provider in ("mock", ""):
        gemini_env(MODEL_PROVIDER=provider)
        assert selection.current_disclosure() == "none"


def test_settings_errors_do_not_repeat_values() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, gemini_api_key=["SECRET"], gemini_tier="SECRET")
    assert "SECRET" not in str(caught.value)
    assert "SECRET" not in repr(Settings(_env_file=None, gemini_api_key="SECRET"))


@pytest.mark.parametrize("name", ["provider_spend_limit_daily", "provider_spend_limit_monthly"])
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "x", ""])
def test_bad_spending_limits_stop_startup(name, value) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{name: value})


def test_http_libraries_are_silent_at_debug() -> None:
    configure_logging("DEBUG")
    for name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        assert not logging.getLogger(name).isEnabledFor(logging.CRITICAL)
