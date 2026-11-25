"""The Gemini adapter against fake servers. Nothing here can reach Google."""

import json
import logging
import socket
import threading
import time

import httpx
import pytest

from app.modules.providers import gemini
from app.modules.providers.contract import (
    Completion,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusedError,
    ProviderSetupError,
    ProviderTimeoutError,
    Role,
    TextPiece,
)
from app.modules.providers.gemini import GeminiProvider
from app.modules.providers.models import GEMINI_MODELS
from tests.conftest import NetworkRefusedError

KEY = "AIza-SECRET-KEY-123"
LITE = GEMINI_MODELS["gemini-3.5-flash-lite"]
MESSAGES = [Message(Role.SYSTEM, "SECRET-SYSTEM"), Message(Role.USER, "SECRET-IN")]
USAGE = {"promptTokenCount": 7, "candidatesTokenCount": 3, "totalTokenCount": 15}
USAGE["thoughtsTokenCount"] = 5


def event(text: str | None = None, reason: str | None = None, usage=USAGE, parts=None) -> dict:
    parts = parts if parts is not None else [{"text": text or ""}]
    candidate: dict = {"content": {"role": "model", "parts": parts}}
    if reason:
        candidate["finishReason"] = reason
    return {"candidates": [candidate], "usageMetadata": usage}


def sse(*events) -> bytes:
    return "".join(f"data: {json.dumps(e, ensure_ascii=False)}\r\n\r\n" for e in events).encode()


GOOD = sse(event("Hel"), event("lo اردو 😀", "STOP"))


@pytest.fixture(autouse=True)
def workers_come_back(monkeypatch):
    """Every test must give all its workers back."""
    workers = threading.BoundedSemaphore(16)
    monkeypatch.setattr(gemini, "_workers", workers)
    yield
    end = time.monotonic() + 5
    while workers._value != 16 and time.monotonic() < end:
        time.sleep(0.02)
    assert workers._value == 16


class Server(httpx.BaseTransport):
    def __init__(self, body=GOOD, status: int = 200, headers=None) -> None:
        self.body, self.status, self.headers = body, status, headers
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if isinstance(self.body, Exception):
            raise self.body
        return httpx.Response(self.status, stream=Body(self.body), headers=self.headers)


class Body(httpx.SyncByteStream):
    def __init__(self, body) -> None:
        self.body = body

    def __iter__(self):
        yield from [self.body] if isinstance(self.body, bytes) else self.body


def provider(server: Server, spec=LITE) -> GeminiProvider:
    return GeminiProvider(KEY, spec, transport=server)


def complete(server: Server, messages=MESSAGES, timeout=5.0, tokens=500, spec=LITE) -> Completion:
    return provider(server, spec).complete(
        messages, timeout_seconds=timeout, max_output_tokens=tokens
    )


def test_the_exact_request() -> None:
    server = Server()
    chat = [*MESSAGES, Message(Role.ASSISTANT, "Hi"), Message(Role.USER, "Bye")]
    complete(server, chat)
    (request,) = server.requests
    assert request.method == "POST"
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite"
        ":streamGenerateContent?alt=sse"
    )
    assert json.loads(request.content) == {
        "systemInstruction": {"parts": [{"text": "SECRET-SYSTEM"}]},
        "contents": [
            {"role": "user", "parts": [{"text": "SECRET-IN"}]},
            {"role": "model", "parts": [{"text": "Hi"}]},
            {"role": "user", "parts": [{"text": "Bye"}]},
        ],
        "generationConfig": {
            "maxOutputTokens": 500,
            "thinkingConfig": {"thinkingLevel": "MINIMAL"},
        },
        "store": False,
    }


@pytest.mark.parametrize("spec", GEMINI_MODELS.values(), ids=GEMINI_MODELS)
@pytest.mark.parametrize("stream", [False, True])
def test_the_key_is_only_in_its_header(spec, stream) -> None:
    server = Server()
    if stream:
        list(provider(server, spec).stream(MESSAGES, timeout_seconds=5, max_output_tokens=5))
    else:
        complete(server, spec=spec)
    (request,) = server.requests
    assert request.headers["x-goog-api-key"] == KEY
    assert [name for name, value in request.headers.items() if KEY in value] == ["x-goog-api-key"]
    assert KEY not in str(request.url) and "key=" not in str(request.url)
    assert dict(request.url.params) == {"alt": "sse"}
    assert KEY.encode() not in request.content
    url, body = provider(server, spec).request(MESSAGES, 5)
    assert KEY not in url + json.dumps(body)
    assert KEY not in repr(provider(server, spec))


def test_an_answer_with_its_tokens() -> None:
    # Thinking is billed as output.
    assert complete(Server()) == Completion("Hello اردو 😀", 7, 8)


def test_the_stream_gives_pieces_and_then_the_whole() -> None:
    items = list(provider(Server()).stream(MESSAGES, timeout_seconds=5, max_output_tokens=5))
    assert items == [TextPiece("Hel"), TextPiece("lo اردو 😀"), Completion("Hello اردو 😀", 7, 8)]


def test_events_may_be_split_anywhere() -> None:
    server = Server(body=(GOOD[i : i + 1] for i in range(len(GOOD))))
    assert complete(server).text == "Hello اردو 😀"
    assert complete(Server(body=GOOD.rstrip())).text == "Hello اردو 😀"


def test_thoughts_are_not_part_of_the_answer() -> None:
    parts = [{"text": "thinking", "thought": True}, {"text": "answer", "thoughtSignature": "x"}]
    assert complete(Server(sse(event(parts=parts, reason="STOP")))).text == "answer"


def test_an_answer_stopped_at_the_token_limit_is_returned() -> None:
    assert complete(Server(sse(event("half", "MAX_TOKENS")))).text == "half"


@pytest.mark.parametrize("tokens", [0, -1, LITE.max_output_tokens + 1])
def test_calls_above_the_models_limits_are_not_sent(tokens) -> None:
    server = Server()
    with pytest.raises(ProviderError):
        complete(server, tokens=tokens)
    assert server.requests == []


@pytest.mark.parametrize("timeout", [0, -1])
def test_calls_without_time_are_not_sent(timeout) -> None:
    server = Server()
    with pytest.raises(ProviderError):
        complete(server, timeout=timeout)
    assert server.requests == []


REFUSED = ["SAFETY", "RECITATION", "LANGUAGE", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"]
INVALID_KEY = json.dumps({"error": {"details": [{"reason": "API_KEY_INVALID"}]}}).encode()


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (400, b"{}", ProviderError),
        (400, INVALID_KEY, ProviderSetupError),
        (401, b"", ProviderSetupError),
        (402, b"", ProviderSetupError),
        (403, b"", ProviderSetupError),
        (404, b"", ProviderSetupError),
        (408, b"", ProviderTimeoutError),
        (429, b"", ProviderRateLimitError),
        (500, b"", ProviderError),
        (503, b"x" * 1_000_000, ProviderError),
        (504, b"", ProviderTimeoutError),
    ],
)
def test_error_statuses(status, body, error) -> None:
    server = Server(body, status)
    with pytest.raises(ProviderError) as caught:
        complete(server)
    assert type(caught.value) is error
    assert len(server.requests) == 1  # no retry


@pytest.mark.parametrize(
    ("body", "logged"),
    [
        *((sse(event("SECRET", reason)), f"answer: {reason}") for reason in REFUSED),
        (sse({"promptFeedback": {"blockReason": "SAFETY"}}), "prompt: SAFETY"),
        (sse({"promptFeedback": {"blockReason": "SECRET"}}), "prompt: unknown"),
    ],
)
def test_the_reason_for_a_refusal_is_logged_and_nothing_else(body, logged, caplog) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderRefusedError):
        complete(Server(body))
    messages = [r.getMessage() for r in caplog.records if r.name.startswith("app.")]
    assert messages == [f"gemini refused ({logged})"]
    assert "SECRET" not in caplog.text


def test_a_long_answer_is_refused_even_when_its_end_is_good() -> None:
    comments = b": x" + b"x" * 997 + b"\n"
    body = [comments] * (gemini.MAX_RESPONSE_BYTES // len(comments)) + [GOOD]
    with pytest.raises(ProviderError):
        complete(Server(iter(body)))
    assert complete(Server(iter(body[1000:]))).text == "Hello اردو 😀"


def test_a_long_error_is_not_read_to_its_end() -> None:
    read = []

    def body():
        for number in range(1000):
            read.append(number)
            yield b"x" * 1000

    with pytest.raises(ProviderError):
        complete(Server(body(), 500))
    assert len(read) < 100


def test_redirects_are_not_followed() -> None:
    server = Server(b"", 307, {"Location": "https://evil.example/"})
    with pytest.raises(ProviderError):
        complete(server)
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    ("body", "error"),
    [
        *((sse(event("x", reason)), ProviderRefusedError) for reason in REFUSED),
        (sse({"promptFeedback": {"blockReason": "SAFETY"}}), ProviderRefusedError),
        (sse(event("x", "UNEXPECTED_TOOL_CALL")), ProviderError),
        (sse(event("x", "SOMETHING_NEW")), ProviderError),
        (sse(event(parts=[{"functionCall": {"name": "x"}}], reason="STOP")), ProviderError),
        (sse(event(parts=[{"toolCall": {}}], reason="STOP")), ProviderError),
        (sse(event("cut off")), ProviderError),
        (b"", ProviderError),
        (sse(event("x", "STOP", usage=None)), ProviderError),
        (sse(event("x", "STOP", usage={})), ProviderError),
        (sse(event("x", "STOP", usage={"promptTokenCount": 5})), ProviderError),
        (sse(event("x", "STOP", usage=USAGE | {"promptTokenCount": -1})), ProviderError),
        (sse(event("x", "STOP", usage=USAGE | {"promptTokenCount": "7"})), ProviderError),
        (sse(event("x", "STOP", usage=USAGE | {"totalTokenCount": True})), ProviderError),
        (sse(event("x", "STOP", usage=USAGE | {"totalTokenCount": 10**12})), ProviderError),
        (sse(event("x"), {"error": {"code": 429, "message": "x"}}), ProviderRateLimitError),
        (sse(event("x"), {"error": {"code": 503, "message": "x"}}), ProviderError),
        (b"data: {not json\n", ProviderError),
        (b"data: " + b"[" * 100_000 + b"\n", ProviderError),
        (b"data: null\n" + GOOD, ProviderError),
        (b"data: [1]\n", ProviderError),
        (b"data: 5\n", ProviderError),
        (b'data: {"candidates": 5}\n', ProviderError),
        (sse(event(parts=[{"text": 5}], reason="STOP")), ProviderError),
        (b"x" * (gemini.MAX_RESPONSE_BYTES + 1), ProviderError),
        (httpx.ConnectError("SECRET"), ProviderError),
        (httpx.ReadTimeout("SECRET"), ProviderTimeoutError),
        (ValueError(KEY), ProviderError),
    ],
)
def test_bad_answers_are_errors_that_carry_nothing(body, error, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ProviderError) as caught:
        complete(Server(body))
    assert type(caught.value) is error
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "SECRET" not in str(caught.value.__dict__) + caplog.text


def test_nothing_private_is_logged_at_debug(caplog) -> None:
    """Over a real connection, with the real HTTP library at its most talkative."""
    for name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logging.getLogger(name).setLevel(logging.NOTSET)
    try:
        with caplog.at_level(logging.DEBUG), tcp_server(respond(GOOD)) as url:
            answer = GeminiProvider(KEY, LITE, base_url=url).complete(
                MESSAGES, timeout_seconds=5, max_output_tokens=5
            )
            with pytest.raises(ProviderError):
                complete(Server(b"SECRET-OUT", 500))
    finally:
        gemini.silence_http_libraries()
    assert answer.text == "Hello اردو 😀"
    everything = caplog.text + "".join(str(record.__dict__) for record in caplog.records)
    assert "SECRET" not in everything and "Hello" not in everything
    assert [r.getMessage() for r in caplog.records if r.name.startswith(("http", "app"))] == [
        "gemini call failed (http 500)"
    ]


HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
END = HEAD[-4:]


def read_request(connection) -> None:
    """All of it: closing with unread data would reset the connection."""
    data = b""
    while END not in data:
        data += connection.recv(65536)
    head, _, body = data.partition(END)
    length = int(head.lower().split(b"content-length: ")[1].split()[0])
    while len(body) < length:
        body += connection.recv(65536)


class tcp_server:  # noqa: N801
    """One connection at a time, handled by ``handle(socket)``."""

    def __init__(self, handle) -> None:
        self.handle = handle
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.stop = threading.Event()

    def __enter__(self) -> str:
        threading.Thread(target=self._serve, daemon=True).start()
        return f"http://127.0.0.1:{self.listener.getsockname()[1]}"

    def _serve(self) -> None:
        try:
            connection, _ = self.listener.accept()
            with connection:
                read_request(connection)
                self.handle(connection, self.stop)
        except OSError:
            pass

    def __exit__(self, *_) -> None:
        self.stop.set()
        self.listener.close()


def respond(body: bytes):
    return lambda connection, _: connection.sendall(HEAD + body)


def trickle(chunk: bytes, head: bytes = HEAD):
    def handle(connection, stop) -> None:
        connection.sendall(head)
        while not stop.wait(0.05):
            connection.sendall(chunk)

    return handle


def silent(connection, stop) -> None:
    stop.wait(10)


@pytest.mark.parametrize(
    "handle",
    [
        silent,
        trickle(b" "),
        trickle(b": ping\n\n"),
        trickle(sse(event("a"))),
        trickle(b"x", b"HTTP/1.1 500 E\r\nConnection: close\r\n\r\n"),
        trickle(b"X-A: b\r\n", b"HTTP/1.1 200 OK\r\n"),
    ],
    ids=["silent", "bytes", "comments", "text", "error body", "headers"],
)
def test_the_deadline_is_hard(handle) -> None:
    with tcp_server(handle) as url:
        started = time.monotonic()
        with pytest.raises(ProviderTimeoutError):
            GeminiProvider(KEY, LITE, base_url=url).complete(
                MESSAGES, timeout_seconds=0.6, max_output_tokens=5
            )
        assert 0.5 < time.monotonic() - started < 1.5


def test_a_stuck_name_lookup_does_not_pass_the_deadline(monkeypatch) -> None:
    release = threading.Event()

    def stuck(*_args, **_kwargs):
        release.wait(10)
        raise OSError

    monkeypatch.setattr(socket, "getaddrinfo", stuck)
    started = time.monotonic()
    with pytest.raises(ProviderTimeoutError):
        GeminiProvider(KEY, LITE, base_url="http://stuck.example").complete(
            MESSAGES, timeout_seconds=0.4, max_output_tokens=5
        )
    assert time.monotonic() - started < 1.5
    assert gemini._workers._value == 15  # still counted while it is stuck
    release.set()


def test_the_number_of_workers_is_limited(monkeypatch) -> None:
    server = Server()
    for _ in range(16):
        gemini._workers.acquire()
    with pytest.raises(ProviderError):
        complete(server)
    assert server.requests == []
    gemini._workers.release(16)
    assert complete(server).text


def test_closing_a_stream_cancels_it() -> None:
    with tcp_server(trickle(sse(event("a")))) as url:
        stream = GeminiProvider(KEY, LITE, base_url=url).stream(
            MESSAGES, timeout_seconds=30, max_output_tokens=5
        )
        assert next(stream) == TextPiece("a")
        stream.close()
        end = time.monotonic() + 3
        while gemini._workers._value != 16 and time.monotonic() < end:
            time.sleep(0.02)
        assert gemini._workers._value == 16  # long before the timeout


def test_a_reader_that_comes_back_too_late_gets_a_timeout() -> None:
    stream = provider(Server()).stream(MESSAGES, timeout_seconds=0.3, max_output_tokens=5)
    next(stream)
    time.sleep(0.4)
    with pytest.raises(ProviderTimeoutError):
        next(stream)


def test_a_forgotten_stream_ends_at_its_deadline() -> None:
    body = sse(*[event("a")] * 500)  # more than the queue holds
    stream = provider(Server(body)).stream(MESSAGES, timeout_seconds=0.4, max_output_tokens=5)
    next(stream)
    end = time.monotonic() + 3
    while gemini._workers._value != 16 and time.monotonic() < end:
        time.sleep(0.02)
    assert gemini._workers._value == 16
    stream.close()


def test_nothing_is_sent_before_the_first_piece_is_asked_for() -> None:
    server = Server()
    stream = provider(server).stream(MESSAGES, timeout_seconds=5, max_output_tokens=5)
    time.sleep(0.05)
    assert server.requests == []
    stream.close()


def test_the_environment_cannot_redirect_the_key(monkeypatch) -> None:
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://proxy.example:1")
    with tcp_server(respond(GOOD)) as url:
        answer = GeminiProvider(KEY, LITE, base_url=url).complete(
            MESSAGES, timeout_seconds=5, max_output_tokens=5
        )
    assert answer.text


def test_tests_cannot_reach_the_network() -> None:
    with pytest.raises(NetworkRefusedError):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)
    with socket.socket() as s, pytest.raises(NetworkRefusedError):
        s.connect(("203.0.113.1", 443))
