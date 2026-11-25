"""A provider for development and tests. Deterministic, offline, and not an AI.

It repeats the user's answers inside a draft, so hostile answers come back as hostile output.
"""

import html
import json
import re
from collections.abc import Sequence

from app.modules.providers.contract import (
    Completion,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    Stream,
    TextPiece,
)

CHARACTERS_PER_TOKEN = 4
CHARACTERS_PER_PIECE = 20
_ANSWER = re.compile(r'<user_answer field="(\w+)">\n(.*?)\n</user_answer>', re.DOTALL)
_FAILURES = {
    "timeout": ProviderTimeoutError,
    "rate_limited": ProviderRateLimitError,
    "unavailable": ProviderError,
}


class MockProvider:
    def __init__(self, scenario: str = "ok") -> None:
        self._scenario = scenario

    def complete(
        self, messages: Sequence[Message], *, timeout_seconds: float, max_output_tokens: int
    ) -> Completion:
        if self._scenario in _FAILURES:
            raise _FAILURES[self._scenario]()
        text = self._text(messages)[: max_output_tokens * CHARACTERS_PER_TOKEN]
        return Completion(
            text=text,
            input_tokens=_fake_tokens("".join(message.content for message in messages)),
            output_tokens=_fake_tokens(text),
        )

    def stream(
        self, messages: Sequence[Message], *, timeout_seconds: float, max_output_tokens: int
    ) -> Stream:
        completion = self.complete(
            messages, timeout_seconds=timeout_seconds, max_output_tokens=max_output_tokens
        )
        for start in range(0, len(completion.text), CHARACTERS_PER_PIECE):
            yield TextPiece(completion.text[start : start + CHARACTERS_PER_PIECE])
        yield completion

    def _text(self, messages: Sequence[Message]) -> str:
        if self._scenario == "malformed":
            return "Sure! Here is your agent: {"
        prompt = messages[-1].content
        answers = {field: html.unescape(text) for field, text in _ANSWER.findall(prompt)}
        draft: dict[str, object] = {
            "name": "Sample agent",
            "purpose": answers.get("purpose", "")[:500],
            "description": "A sample draft made without AI.",
            "instructions": "\n\n".join(
                f"{field.capitalize()}:\n{text}" for field, text in answers.items() if text
            ),
        }
        if self._scenario == "extra_field":
            draft["tools"] = ["shell"]
        return json.dumps(draft, ensure_ascii=False)


def _fake_tokens(text: str) -> int:
    return -(-len(text) // CHARACTERS_PER_TOKEN)
