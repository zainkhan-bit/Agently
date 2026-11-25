"""A provider for development and tests. Deterministic, offline, and not an AI.

It repeats what people typed, so hostile text comes back as hostile output.
"""

import html
import json
import re
import time
from collections.abc import Sequence

from app.modules.providers.contract import (
    Completion,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusedError,
    ProviderTimeoutError,
    Stream,
    TextPiece,
)

CHARACTERS_PER_TOKEN = 4
CHARACTERS_PER_PIECE = 20
SLOW_PIECE_SECONDS = 0.4
_ANSWER = re.compile(r'<user_answer field="(\w+)">\n(.*?)\n</user_answer>', re.DOTALL)
_CHAT = re.compile(r"<user_message>\n(.*)\n</user_message>", re.DOTALL)
_FAILURES = {
    "timeout": ProviderTimeoutError,
    "rate_limited": ProviderRateLimitError,
    "unavailable": ProviderError,
    "refused": ProviderRefusedError,
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
            if self._scenario == "slow":  # time to watch it arrive, or to stop it
                time.sleep(min(SLOW_PIECE_SECONDS, timeout_seconds))
            yield TextPiece(completion.text[start : start + CHARACTERS_PER_PIECE])
        yield completion

    def _text(self, messages: Sequence[Message]) -> str:
        chat = _CHAT.fullmatch(messages[-1].content)
        if chat:
            if self._scenario == "malformed":
                return " \n "
            return f"Sample answer, made without AI. You wrote:\n\n{html.unescape(chat[1])}"
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
