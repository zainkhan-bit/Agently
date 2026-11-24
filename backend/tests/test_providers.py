"""The provider contract, run against the mock, and the rules for choosing a provider."""

import inspect
import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.main import create_app
from app.modules.providers import selection
from app.modules.providers.contract import (
    Completion,
    Message,
    Provider,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    Role,
)
from app.modules.providers.mock import MockProvider

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
