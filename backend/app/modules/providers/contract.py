"""What every model provider must do. Knows nothing about what the text is used for."""

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.core.errors import AppError


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = field(repr=False)  # private text must not reach logs

    def __post_init__(self) -> None:
        Role(self.role)  # raises for anything else


@dataclass(frozen=True)
class ToolCall:
    """A model's wish to use a tool. Untrusted: asking for something permits nothing.

    Nothing sends tools yet, so adapters must treat a tool call as an error.
    """

    id: str
    name: str = field(repr=False)
    arguments: str = field(repr=False)  # JSON text, unchecked


@dataclass(frozen=True)
class Completion:
    """The text is untrusted: whoever called decides what may be done with it."""

    text: str = field(repr=False)
    input_tokens: int
    output_tokens: int  # thinking included
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class TextPiece:
    """Part of an answer. Untrusted, and the rest may still fail."""

    text: str = field(repr=False)


Stream = Generator[TextPiece | Completion, None, None]


class Provider(Protocol):
    def complete(
        self, messages: Sequence[Message], *, timeout_seconds: float, max_output_tokens: int
    ) -> Completion:
        """Answer within the timeout and the token limit, or raise a ProviderError.

        Must not retry by itself, and must not log messages or text.
        """
        ...

    def stream(
        self, messages: Sequence[Message], *, timeout_seconds: float, max_output_tokens: int
    ) -> Stream:
        """Like ``complete``, in pieces. The last item is a Completion with the whole text.

        Nothing is sent before the first ``next()``, which starts the timeout for the whole
        stream. ``close()`` cancels; the provider may still charge for a cancelled call.
        """
        ...


class ProviderError(AppError):
    """Messages are fixed, so nothing a provider says reaches people or logs."""

    status_code = 503
    code = "provider_unavailable"
    message = "The AI provider is not available right now. Please try again later."
    # True only when nothing was sent, or the provider refused it before doing any work.
    uncharged = False

    def __init__(self, *, uncharged: bool = False) -> None:
        super().__init__()
        self.uncharged = uncharged


class ProviderTimeoutError(ProviderError):
    status_code = 504
    code = "provider_timeout"
    message = "The AI provider took too long to answer. Please try again."


class ProviderRateLimitError(ProviderError):
    code = "provider_rate_limited"
    message = "The AI provider is receiving too many requests. Please wait and try again."


class ProviderNotConfiguredError(ProviderError):
    code = "provider_not_configured"
    message = "No AI provider is set up."


class ProviderSetupError(ProviderError):
    """The provider refused the key, the account or the model: only the operator can help."""

    code = "provider_setup"
    message = "The AI provider refused this server's setup. Its operator must check the settings."


class ProviderRefusedError(ProviderError):
    status_code = 502
    code = "provider_refused"
    message = "The AI provider declined to answer. Please change your text and try again."


class ProviderBudgetError(ProviderError):
    code = "provider_budget"
    message = "This server has reached its AI spending limit. Please try again later."


# What callers may pass on. Anything else may carry private text and becomes a ProviderError.
KNOWN_ERRORS: tuple[type[ProviderError], ...] = (
    ProviderError,
    ProviderTimeoutError,
    ProviderRateLimitError,
    ProviderNotConfiguredError,
    ProviderSetupError,
    ProviderRefusedError,
    ProviderBudgetError,
)
