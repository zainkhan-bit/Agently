"""What every model provider must do. Knows nothing about what the text is used for."""

from collections.abc import Sequence
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
class Completion:
    """The text is untrusted: whoever called decides what may be done with it."""

    text: str = field(repr=False)
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    def complete(
        self, messages: Sequence[Message], *, timeout_seconds: float, max_output_tokens: int
    ) -> Completion:
        """Answer within the timeout and the token limit, or raise a ProviderError.

        Must not retry by itself, and must not log messages or text.
        """
        ...


class ProviderError(AppError):
    """Messages are fixed, so nothing a provider says reaches people or logs."""

    status_code = 503
    code = "provider_unavailable"
    message = "The AI provider is not available right now. Please try again later."

    def __init__(self) -> None:
        super().__init__()


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
