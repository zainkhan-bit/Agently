"""Google Gemini over REST.

The key is only ever in the ``x-goog-api-key`` header: not in a URL, log line or exception. Nothing
Google sends is logged, except the HTTP status and a refusal reason from a fixed list.
"""

import json
import logging
import queue
import threading
import time
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.logs import silence_http_libraries
from app.modules.providers.contract import (
    KNOWN_ERRORS,
    Completion,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusedError,
    ProviderSetupError,
    ProviderTimeoutError,
    Role,
    Stream,
    TextPiece,
)
from app.modules.providers.models import ModelSpec

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com"
MAX_RESPONSE_BYTES = 4_000_000
MAX_ERROR_BYTES = 64_000
# A worker can outlive its call (a stuck name lookup), so it keeps its place until it ends.
_workers = threading.BoundedSemaphore(16)

_REFUSALS = {"SAFETY", "RECITATION", "LANGUAGE", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
_BLOCKS = {"SAFETY", "OTHER", "BLOCKLIST", "PROHIBITED_CONTENT", "IMAGE_SAFETY"}


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        spec: ModelSpec,
        *,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        silence_http_libraries()
        self._api_key = api_key
        self._spec = spec
        self._base_url = base_url
        self._transport = transport

    def __repr__(self) -> str:
        return f"GeminiProvider({self._spec.name})"

    def complete(
        self, messages: Sequence[Message], *, timeout_seconds: float, max_output_tokens: int
    ) -> Completion:
        stream = self.stream(
            messages, timeout_seconds=timeout_seconds, max_output_tokens=max_output_tokens
        )
        try:
            for item in stream:
                if isinstance(item, Completion):
                    return item
        finally:
            stream.close()
        raise ProviderError()

    def stream(
        self, messages: Sequence[Message], *, timeout_seconds: float, max_output_tokens: int
    ) -> Stream:
        deadline = time.monotonic() + timeout_seconds
        url, body = self.request(messages, max_output_tokens)
        if not self._spec.streaming or timeout_seconds <= 0:
            raise ProviderError()
        if not _workers.acquire(blocking=False):
            logger.warning("gemini call refused (no free worker)")
            raise ProviderError()
        call = _Call(self._client, timeout_seconds, deadline, url, body)
        try:
            threading.Thread(target=call.run, name="gemini", daemon=True).start()
        except BaseException:
            _workers.release()
            raise
        try:
            yield from _read(call)
        finally:
            call.cancelled.set()

    def request(
        self, messages: Sequence[Message], max_output_tokens: int
    ) -> tuple[str, dict[str, Any]]:
        """The URL and body. Neither holds the key."""
        if not 0 < max_output_tokens <= self._spec.max_output_tokens:
            raise ProviderError()
        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if m.role == Role.ASSISTANT else "user",
                    "parts": [{"text": m.content}],
                }
                for m in messages
                if m.role != Role.SYSTEM
            ],
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "thinkingConfig": {"thinkingLevel": self._spec.thinking_level},
            },
            # Keeps the call out of the project's own request log in AI Studio.
            "store": False,
        }
        system = [{"text": m.content} for m in messages if m.role == Role.SYSTEM]
        if system:
            body["systemInstruction"] = {"parts": system}
        url = f"{self._base_url}/v1beta/models/{self._spec.name}:streamGenerateContent?alt=sse"
        return url, body

    def _client(self, timeout_seconds: float) -> httpx.Client:
        return httpx.Client(
            headers={"x-goog-api-key": self._api_key, "Accept-Encoding": "identity"},
            timeout=timeout_seconds,  # each step; the deadline covers the whole call
            transport=self._transport,
            follow_redirects=False,  # the key must not follow
            trust_env=False,  # no proxy or credentials from the environment
        )


class _Call:
    """One request, made on a worker thread. Hands over parsed events, then one error or None."""

    def __init__(self, new_client, timeout_seconds: float, deadline: float, url: str, body) -> None:
        self._new_client = new_client
        self._timeout = timeout_seconds
        self._url = url
        self._body = body
        self.deadline = deadline
        self.cancelled = threading.Event()
        self.items: queue.Queue[Any] = queue.Queue(maxsize=64)

    def run(self) -> None:
        try:
            result: type[ProviderError] | None = ProviderError
            try:
                result = self._events()
            except httpx.TimeoutException:
                result = ProviderTimeoutError
            except Exception:  # noqa: BLE001, S110 - may hold the key or private text
                pass
            self._put(result)
        finally:
            _workers.release()

    def _events(self) -> type[ProviderError] | None:
        with (
            self._new_client(self._timeout) as client,
            client.stream("POST", self._url, json=self._body) as response,
        ):
            if response.status_code != 200:
                return self._refused(response)
            received, buffer = 0, b""
            for chunk in response.iter_raw():
                received += len(chunk)
                if self._over():
                    return ProviderTimeoutError
                if received > MAX_RESPONSE_BYTES:
                    return ProviderError
                *lines, buffer = (buffer + chunk).split(b"\n")
                for line in lines:
                    self._event(line)
            self._event(buffer)
        return None

    def _event(self, line: bytes) -> None:
        if line.startswith(b"data:"):
            self._put(json.loads(line[5:]))

    def _refused(self, response: httpx.Response) -> type[ProviderError]:
        body = b""
        for chunk in response.iter_raw():
            body += chunk
            if len(body) > MAX_ERROR_BYTES or self._over():
                break
        logger.warning("gemini call failed (http %d)", response.status_code)
        return _error_for(response.status_code, body)

    def _over(self) -> bool:
        return self.cancelled.is_set() or time.monotonic() >= self.deadline

    def _put(self, item: Any) -> None:
        while not self._over():
            try:
                self.items.put(item, timeout=0.1)
                return
            except queue.Full:
                continue


def _read(call: _Call) -> Stream:
    text: list[str] = []
    usage: Any = None
    finished = False
    while True:
        # Raised outside the except blocks: there, the error would keep private text as context.
        failure: type[ProviderError] | None = None
        event: Any = None
        piece = ""
        try:
            event = call.items.get(timeout=max(0.0, call.deadline - time.monotonic()))
        except queue.Empty:
            failure = ProviderTimeoutError
        if failure is None and time.monotonic() >= call.deadline:
            failure = ProviderTimeoutError  # also when the caller took too long to come back
        if failure is None and event is None:
            break
        if failure is None and isinstance(event, type):
            failure = event
        elif failure is None:
            try:
                piece, done, counts = _parse(event)
                finished = finished or done
                usage = counts or usage
            except Exception as error:  # noqa: BLE001 - includes any undocumented shape
                failure = type(error) if type(error) in KNOWN_ERRORS else ProviderError
        if failure is not None:
            raise failure()
        if piece:
            text.append(piece)
            yield TextPiece(piece)
    tokens = _tokens(usage)
    if not finished or tokens is None:
        raise ProviderError()  # cut off, or of unknown cost
    yield Completion("".join(text), *tokens)


def _parse(event: dict[str, Any]) -> tuple[str, bool, Any]:
    if "error" in event:
        raise _error_for(int(event["error"].get("code", 500)), json.dumps(event).encode())()
    block = event.get("promptFeedback", {}).get("blockReason")
    if block:
        # The set's own word, never text from outside.
        logger.warning("gemini refused (prompt: %s)", block if block in _BLOCKS else "unknown")
        raise ProviderRefusedError()
    usage = event.get("usageMetadata")
    candidates = event.get("candidates")
    if not candidates:
        return "", False, usage
    candidate = candidates[0]
    piece = ""
    for part in candidate.get("content", {}).get("parts", []):
        if "functionCall" in part or "toolCall" in part:
            raise ProviderError()  # no tools were offered
        if not part.get("thought"):
            piece += part.get("text", "")
    reason = candidate.get("finishReason")
    if reason in _REFUSALS:
        logger.warning("gemini refused (answer: %s)", reason)
        raise ProviderRefusedError()
    if reason not in (None, "STOP", "MAX_TOKENS"):
        raise ProviderError()
    return piece, reason is not None, usage


def _tokens(usage: Any) -> tuple[int, int] | None:
    """Input and output tokens, or None when the cost cannot be known."""
    if not isinstance(usage, dict):
        return None
    names = ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount")
    counts = [usage.get(name, 0) for name in names]
    if not all(type(count) is int and 0 <= count < 10**9 for count in counts):
        return None
    prompt, candidates, thoughts, total = counts
    if prompt == 0 or total == 0:
        return None
    return prompt, max(candidates + thoughts, total - prompt)


def _error_for(status: int, body: bytes) -> type[ProviderError]:
    if status == 429:
        return ProviderRateLimitError
    if status in (408, 504):
        return ProviderTimeoutError
    if status in (401, 402, 403, 404) or (status == 400 and b"API_KEY_INVALID" in body):
        return ProviderSetupError
    return ProviderError
