"""Sending messages: answers, retries, failures, limits, records, races. The mock only."""

# The imported fixtures are used as arguments.
# ruff: noqa: F401, F811

import json
import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core import clock
from app.core.config import Settings
from app.models import AuthThrottleEvent, Conversation, Execution, Membership, StoredMessage
from app.modules.identity import throttle
from app.modules.providers import selection
from app.modules.providers.contract import (
    Completion,
    Message,
    ProviderBudgetError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusedError,
    ProviderSetupError,
    ProviderTimeoutError,
    Role,
    TextPiece,
    ToolCall,
)
from app.modules.runtime import service
from tests.test_agent_concurrency import lock_workspace
from tests.test_agents_api import code, count, create, s
from tests.test_conversations import c, context, start, store
from tests.test_workspace_concurrency import factory, race, two_owners

pytestmark = pytest.mark.db


class Recorder:
    """A provider that records its calls and answers as told."""

    def __init__(self, session=None) -> None:
        self.calls, self.reply, self.during, self.closed = [], "Fine.", None, 0
        self.session = session

    def stream(self, messages, *, timeout_seconds, max_output_tokens):
        self.calls.append((list(messages), timeout_seconds, max_output_tokens))
        try:
            if self.session is not None:
                assert not self.session.in_transaction()  # the connection went back to the pool
            if self.during:
                self.during()
            yield from self.reply if isinstance(self.reply, list) else self._items()
        finally:
            self.closed += 1

    def _items(self):
        if isinstance(self.reply, BaseException):
            raise self.reply
        yield TextPiece(self.reply)
        yield Completion(self.reply, 7, 3)


@pytest.fixture
def r(c, auth_app, db_session):
    c.provider = Recorder(db_session)
    auth_app.dependency_overrides[selection.get_provider] = lambda: c.provider
    return c


def send(c, content="Hello", request_id=None, client=None, query="", one=None):
    body = {"request_id": str(request_id or uuid.uuid4()), "content": content}
    return (client or c.member).post(f"{one or c.one}/messages{query}", json=body)


def stored(session) -> list[tuple]:
    session.rollback()
    rows = session.scalars(
        select(StoredMessage)
        .order_by(StoredMessage.sequence)
        .execution_options(populate_existing=True)
    )
    return [(m.role, m.content, m.agent_version) for m in rows]


def records(session) -> list[tuple]:
    session.rollback()
    rows = session.scalars(
        select(Execution).order_by(Execution.started_at).execution_options(populate_existing=True)
    )
    return [(e.status, e.error_code, e.message_sequence, e.answer_sequence) for e in rows]


def test_a_message_gets_the_mocks_answer_and_both_are_stored(c, db_session) -> None:
    request = uuid.uuid4()
    response = send(c, "Hello <b>", request)
    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    body = response.json()
    assert (body["message"]["role"], body["message"]["content"]) == ("user", "Hello <b>")
    assert (body["message"]["request_id"], body["message"]["agent_version"]) == (str(request), None)
    answer = body["answer"]
    assert (answer["role"], answer["agent_version"], answer["sequence"]) == ("assistant", 1, 2)
    assert answer["content"].startswith("Sample answer, made without AI.")
    assert answer["content"].endswith("Hello <b>") and answer["request_id"] is None
    listed = c.member.get(f"{c.one}/messages").json()["items"]
    assert listed == [body["message"], answer]
    record = db_session.scalars(select(Execution)).one()
    assert (record.status, record.error_code, record.model) == ("succeeded", None, "mock")
    assert (record.agent_version, record.message_sequence, record.answer_sequence) == (1, 1, 2)
    assert record.input_tokens > 0 and record.output_tokens > 0
    assert record.duration_ms >= 0 and record.finished_at >= record.started_at


def test_the_provider_gets_the_agents_prompt_the_history_and_the_limits(r, configure) -> None:
    configure(runtime_max_output_tokens=123, provider_timeout_seconds=9)
    send(r, "First")
    send(r, "Second")
    messages, timeout, tokens = r.provider.calls[1]
    assert (timeout, tokens) == (9, 123)
    assert [m.role.value for m in messages] == ["system", "user", "assistant", "user"]
    assert "Be kind." in messages[0].content
    assert "First" in messages[1].content and messages[2].content == "Fine."
    assert "Second" in messages[3].content
    assert r.provider.closed == 2


def test_history_is_limited_in_number(r, configure) -> None:
    configure(runtime_history_messages=2)
    for number in range(3):
        send(r, f"m{number}")
    assert len(r.provider.calls[2][0]) == 4
    assert "m0" not in str([m.content for m in r.provider.calls[2][0]])


def test_unanswered_messages_are_left_out_and_take_no_room(r, configure) -> None:
    configure(runtime_history_messages=4)
    send(r, "kept")
    r.provider.reply = ProviderError()
    for number in range(5):
        send(r, f"lost {number}")
    r.provider.reply = "Fine."
    send(r, "now")
    texts = str([m.content for m in r.provider.calls[-1][0]])
    assert "kept" in texts and "lost" not in texts


def test_history_typed_under_another_notice_is_not_sent(r, configure) -> None:
    send(r, "typed under none")
    configure(model_provider="gemini", gemini_tier="paid")
    send(r, "typed under paid", query="?disclosure=gemini_paid")
    configure(model_provider="gemini", gemini_tier="free")
    send(r, "typed under free", query="?disclosure=gemini_free")
    configure(model_provider="gemini", gemini_tier="paid")
    send(r, "paid again", query="?disclosure=gemini_paid")
    second, third, fourth = (str([m.content for m in call[0]]) for call in r.provider.calls[1:])
    assert "under none" not in second
    assert "under none" not in third and "under paid" not in third
    assert "under paid" in fourth and "under free" not in fourth


def test_two_agents_stay_apart(r) -> None:
    other = f"{r.url}/{create(r.owner, r.url, name='Other', instructions='OTHER RULES')['id']}"
    other_chat = f"{other}/conversations/{start(r.member, f'{other}/conversations')['id']}"
    send(r, "mine")
    send(r, "theirs", one=other_chat)
    first, second = (str([m.content for m in call[0]]) for call in r.provider.calls)
    assert "OTHER RULES" not in first and "theirs" not in first
    assert "Be kind." not in second and "mine" not in second


def test_another_conversation_with_the_same_agent_is_not_history(r) -> None:
    second = f"{r.chats}/{start(r.member, r.chats)['id']}"
    send(r, "private one")
    send(r, "two", one=second)
    send(r, "three", one=second)  # its own history, at numbers the other one also has
    for call in r.provider.calls[1:]:
        assert "private one" not in str([m.content for m in call[0]])
    assert "two" in str([m.content for m in r.provider.calls[2][0]])


def test_an_edit_during_the_call_does_not_change_the_recorded_version(r, db_session) -> None:
    r.provider.session = None
    r.provider.during = lambda: r.owner.patch(
        r.agent_url, json={"version": 1, "instructions": "Changed."}
    )
    assert send(r).json()["answer"]["agent_version"] == 1
    assert "Changed." not in r.provider.calls[0][0][0].content
    r.provider.during = None
    assert send(r).json()["answer"]["agent_version"] == 2
    assert "Changed." in r.provider.calls[1][0][0].content


# Streaming


def stream(c, content="Hello", request_id=None, query=""):
    body = {"request_id": str(request_id or uuid.uuid4()), "content": content}
    response = c.member.post(f"{c.one}/messages/stream{query}", json=body)
    return response, _parse(response.text) if response.status_code == 200 else []


def _parse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        if block:
            name, data = block.split("\n")
            events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def test_a_stream_sends_the_message_the_pieces_in_order_and_the_stored_answer(
    r, db_session
) -> None:
    r.provider.reply = [TextPiece("Hel"), TextPiece("lo\n"), Completion("Hello\n", 1, 1)]
    response, events = stream(r)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["Cache-Control"] == "private, no-store, no-transform"
    assert [name for name, _ in events] == ["message", "piece", "piece", "done"]
    assert events[0][1]["content"] == "Hello" and events[0][1]["role"] == "user"
    assert "".join(data["text"] for name, data in events if name == "piece") == "Hello\n"
    assert events[-1][1]["answer"]["content"] == "Hello\n"
    assert stored(db_session)[-1] == ("assistant", "Hello\n", 1)


def test_a_failure_during_the_stream_is_an_error_event(r, db_session) -> None:
    r.provider.reply = [TextPiece("half"), ProviderTimeoutError()]
    r.provider.reply = [TextPiece("half")]
    _, events = stream(r)
    assert [name for name, _ in events] == ["message", "piece", "error"]
    assert events[-1][1] == {
        "code": "provider_unavailable",
        "message": ProviderError.message,
    }
    assert records(db_session) == [("failed", "provider_unavailable", 1, None)]


def test_refusals_before_the_call_are_ordinary_errors(r, db_session) -> None:
    r.owner.post(f"{r.agent_url}/pause")
    response, _ = stream(r)
    assert (response.status_code, code(response)) == (409, "agent_paused")


def test_a_streamed_repeat_returns_the_stored_answer(r, db_session) -> None:
    request = uuid.uuid4()
    _, first = stream(r, request_id=request)
    _, again = stream(r, request_id=request)
    assert [name for name, _ in again] == ["message", "done"]
    assert again[-1][1] == first[-1][1] and len(r.provider.calls) == 1


def test_a_stream_that_is_not_read_to_the_end_is_cancelled(r, db_session, auth_app) -> None:
    r.provider.reply = [TextPiece("a"), TextPiece("b"), Completion("ab", 1, 1)]
    body = {"request_id": str(uuid.uuid4()), "content": "Hello"}
    with r.member.stream("POST", f"{r.one}/messages/stream", json=body) as response:
        lines = response.iter_lines()
        assert next(lines) == "event: message"
    assert stored(db_session) == [("user", "Hello", None)]
    assert records(db_session) == [("cancelled", "cancelled", 1, None)]
    assert r.provider.closed == 1


def test_stopping_cancels_the_running_answer_and_its_call(r, db_session, monkeypatch) -> None:
    monkeypatch.setattr(service, "STOP_CHECK_SECONDS", 0)
    stopped = []

    def pieces():
        yield TextPiece("a")
        stopped.append(r.member.post(f"{r.one}/messages/stop").status_code)
        yield TextPiece("b")
        yield Completion("ab", 1, 1)

    r.provider.reply = None
    r.provider._items = pieces
    response, events = stream(r)
    assert stopped == [204]
    assert [name for name, _ in events] == ["message", "piece", "error"]
    assert events[-1][1]["code"] == "answer_stopped"
    assert records(db_session) == [("cancelled", "stopped", 1, None)]
    assert stored(db_session) == [("user", "Hello", None)]
    assert r.provider.closed == 1
    r.provider._items = Recorder._items.__get__(r.provider)
    r.provider.reply = "Fine."
    assert send(r, "next").status_code == 201


def test_stopping_with_nothing_running_changes_nothing(r, db_session) -> None:
    send(r)
    assert r.member.post(f"{r.one}/messages/stop").status_code == 204
    assert records(db_session) == [("succeeded", None, 1, 2)]


def test_stopping_touches_no_other_conversation(r, db_session) -> None:
    other = accept(r, db_session)  # running in the member's conversation
    owners = f"{r.chats}/{start(r.owner, r.chats)['id']}"
    assert r.owner.post(f"{owners}/messages/stop").status_code == 204
    second = f"{r.chats}/{start(r.member, r.chats)['id']}"
    assert r.member.post(f"{second}/messages/stop").status_code == 204
    assert records(db_session) == [("running", None, 1, None)]
    other.close()


def test_the_stop_check_is_not_made_after_every_piece(r, db_session, monkeypatch) -> None:
    checks = []
    monkeypatch.setattr(service.Run, "_stopped", lambda self: checks.append(1) or False)
    r.provider.reply = [TextPiece("a"), TextPiece("b"), Completion("ab", 1, 1)]
    assert send(r).status_code == 201
    assert checks == []


def test_the_slow_mock_takes_its_time(configure, monkeypatch) -> None:
    from app.modules.providers import mock

    slept = []
    monkeypatch.setattr(mock.time, "sleep", slept.append)
    messages = [Message(Role.USER, "<user_message>\nHi\n</user_message>")]
    pieces = list(
        mock.MockProvider("slow").stream(messages, timeout_seconds=5, max_output_tokens=99)
    )
    assert len(slept) == len(pieces) - 1 and set(slept) == {mock.SLOW_PIECE_SECONDS}


# Repeats


def test_repeating_a_finished_request_returns_the_stored_answer_without_a_call(
    r, db_session
) -> None:
    request = uuid.uuid4()
    first = send(r, "Hello", request)
    send(r, "Later")
    r.owner.post(f"{r.agent_url}/pause")  # nothing runs, so this is no obstacle
    again = send(r, "Hello", request)
    assert (again.status_code, again.json()) == (201, first.json())
    assert len(r.provider.calls) == 2
    assert len(stored(db_session)) == 4


def test_an_answer_can_be_fetched_again_whatever_would_stop_a_call(
    r, configure, monkeypatch
) -> None:
    request = uuid.uuid4()
    first = send(r, "Hello", request).json()
    monkeypatch.setattr(service, "_slots", service.threading.BoundedSemaphore(1))
    service._slots.acquire()
    configure(model_provider="gemini", gemini_tier="free", message_limit_per_conversation=1)
    assert send(r, "Hello", request).json() == first
    configure(model_provider="")
    r.provider = None
    assert send(r, "Hello", request).json() == first


def test_repeating_with_other_text_is_refused(r, db_session) -> None:
    request = uuid.uuid4()
    send(r, "Hello", request)
    refused = send(r, "Other", request)
    assert (refused.status_code, code(refused)) == (409, "request_reused")
    assert len(stored(db_session)) == 2


def test_a_request_id_belongs_to_one_conversation(r) -> None:
    request = uuid.uuid4()
    second = f"{r.chats}/{start(r.member, r.chats)['id']}"
    assert send(r, "one", request).status_code == 201
    assert send(r, "two", request, one=second).status_code == 201


def test_a_failed_message_is_answered_by_its_repeat_and_stored_once(r, db_session) -> None:
    request = uuid.uuid4()
    r.provider.reply = ProviderTimeoutError()
    assert send(r, "Hello", request).status_code == 504
    assert stored(db_session) == [("user", "Hello", None)]
    r.provider.reply = "Fine."
    assert send(r, "Hello", request).status_code == 201
    assert stored(db_session) == [("user", "Hello", None), ("assistant", "Fine.", 1)]
    assert records(db_session) == [
        ("timed_out", "provider_timeout", 1, None),
        ("succeeded", None, 1, 2),
    ]
    prompt = r.provider.calls[1][0]
    assert len(prompt) == 2 and "Hello" in prompt[1].content  # not twice


def test_a_failed_message_cannot_be_repeated_after_a_newer_one(r, db_session) -> None:
    request = uuid.uuid4()
    r.provider.reply = ProviderRefusedError()
    send(r, "refuse me", request)
    r.provider.reply = "Fine."
    assert send(r, "next").status_code == 201
    assert "refuse me" not in str([m.content for m in r.provider.calls[1][0]])
    late = send(r, "refuse me", request)
    assert (late.status_code, code(late)) == (409, "retry_outdated")
    assert len(stored(db_session)) == 3


# Failures


@pytest.mark.parametrize(
    ("scenario", "status", "error", "recorded"),
    [
        ("timeout", 504, "provider_timeout", "timed_out"),
        ("rate_limited", 503, "provider_rate_limited", "failed"),
        ("unavailable", 503, "provider_unavailable", "failed"),
        ("refused", 502, "provider_refused", "failed"),
        ("malformed", 502, "answer_invalid", "failed"),
    ],
)
def test_mock_failures_are_recorded_and_store_no_answer(
    c, db_session, configure, scenario, status, error, recorded
) -> None:
    configure(mock_provider_scenario=scenario)
    response = send(c)
    assert (response.status_code, code(response)) == (status, error)
    assert stored(db_session) == [("user", "Hello", None)]
    assert records(db_session) == [(recorded, error, 1, None)]
    record = db_session.scalars(select(Execution)).one()
    assert (record.input_tokens is None) == (scenario != "malformed")  # never guessed
    configure(mock_provider_scenario="ok")
    assert send(c, "Again").status_code == 201


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (ProviderBudgetError(), 503, "provider_budget"),
        (ProviderSetupError(), 503, "provider_setup"),
        (ValueError("SECRET"), 503, "provider_unavailable"),
    ],
)
def test_other_failures_are_distinct(r, db_session, failure, status, error) -> None:
    r.provider.reply = failure
    response = send(r)
    assert (response.status_code, code(response)) == (status, error)
    assert records(db_session) == [("failed", error, 1, None)]


CALL = ToolCall("1", "shell", "{}")


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ([], "provider_unavailable"),
        ([TextPiece("half")], "provider_unavailable"),
        ([TextPiece("a"), "b"], "provider_unavailable"),
        ([TextPiece(5)], "provider_unavailable"),
        ([Completion(None, 1, 1)], "provider_unavailable"),
        ([Completion("x", "1", 1)], "provider_unavailable"),
        ([Completion("x", 1, -1)], "provider_unavailable"),
        ([Completion("x", 1, 1, (CALL,))], "provider_unavailable"),
        ([Completion("", 1, 1)], "answer_invalid"),
        ([Completion("a\x00b", 1, 1)], "answer_invalid"),
        ([Completion("x" * 32_001, 1, 1)], "answer_invalid"),
        ([TextPiece("x" * 32_001), Completion("x", 1, 1)], "answer_invalid"),
    ],
)
def test_malformed_output_is_a_failure(r, db_session, reply, error) -> None:
    r.provider.reply = reply
    response = send(r)
    assert code(response) == error
    assert stored(db_session) == [("user", "Hello", None)]
    assert [row[:2] for row in records(db_session)] == [("failed", error)]
    assert r.provider.closed == 1


def test_a_provider_that_fails_before_streaming_is_a_failure(r, db_session, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise ValueError("SECRET")

    monkeypatch.setattr(r.provider, "stream", broken)
    assert code(send(r)) == "provider_unavailable"


def test_a_crash_while_storing_is_recorded_as_a_failure(r, db_session, monkeypatch) -> None:
    real = service.store_message

    def crash(db, *args, **values):
        if values["role"] == "assistant":
            raise RuntimeError("bug")
        return real(db, *args, **values)

    monkeypatch.setattr(service, "store_message", crash)
    with pytest.raises(RuntimeError):
        send(r)
    assert records(db_session) == [("failed", "internal_error", 1, None)]


@pytest.mark.parametrize(
    "reply", ["SECRET-OUT\x00", ValueError("SECRET-OUT"), ProviderError(), "SECRET-OUT"]
)
def test_no_private_text_in_logs_or_errors(r, caplog, reply) -> None:
    r.owner.patch(r.agent_url, json={"version": 1, "instructions": "SECRET-RULES"})
    r.provider.reply = reply
    with caplog.at_level(logging.DEBUG):
        response = send(r, "SECRET-IN")
    logged = caplog.text + "".join(str(record.__dict__) for record in caplog.records)
    assert "SECRET" not in logged
    if response.status_code != 201:
        assert "answer not stored" in logged and "SECRET" not in response.text


def test_errors_keep_no_trace_of_the_adapters_error() -> None:
    def failing():
        raise ValueError("SECRET")
        yield

    failure = service._next(failing())
    assert type(failure) is ProviderError
    assert failure.__context__ is None and failure.__cause__ is None


def test_a_run_shows_no_text_in_its_representation(r, db_session) -> None:
    run = accept(r, db_session, "SECRET")
    assert "SECRET" not in repr(run) and "Be kind" not in repr(run)
    run.close()


# Refused before the call


@pytest.mark.parametrize(
    ("action", "error"), [("pause", "agent_paused"), ("archive", "agent_archived")]
)
def test_stopped_agents_do_not_run(r, db_session, action, error) -> None:
    assert r.owner.post(f"{r.agent_url}/{action}").status_code == 200
    refused = send(r)
    assert (refused.status_code, code(refused)) == (409, error)
    assert r.provider.calls == [] and stored(db_session) == records(db_session) == []


def test_without_a_provider_nothing_is_stored(c, db_session, configure) -> None:
    configure(model_provider="")
    assert code(send(c)) == "provider_not_configured"
    assert stored(db_session) == []


def test_messages_are_sent_only_under_the_notice_that_was_shown(r, db_session, configure) -> None:
    configure(model_provider="gemini", gemini_tier="free")
    for query in ("", "?disclosure=none", "?disclosure=gemini_paid"):
        refused = send(r, query=query)
        assert (refused.status_code, code(refused)) == (409, "disclosure_changed")
    assert r.provider.calls == [] and stored(db_session) == []
    assert send(r, query="?disclosure=gemini_free").status_code == 201
    assert db_session.scalars(select(Execution.model)).one().startswith("gemini")


@pytest.mark.parametrize("content", ["", " \n", "x" * 8_001, "a\x00"])
def test_invalid_messages_are_refused(r, db_session, content) -> None:
    refused = send(r, content)
    assert (refused.status_code, code(refused)) == (422, "message_invalid")
    assert r.provider.calls == [] and stored(db_session) == []


@pytest.mark.parametrize(
    "extra", [{"role": "system"}, {"agent_version": 9}, {"model": "x"}, {"provider": "gemini"}]
)
def test_a_request_cannot_choose_anything_else(r, db_session, extra) -> None:
    body = {"request_id": str(uuid.uuid4()), "content": "Hi"} | extra
    assert r.member.post(f"{r.one}/messages", json=body).status_code == 422
    assert stored(db_session) == []


def test_a_message_that_cannot_fit_is_refused_before_it_is_stored(r, db_session, configure) -> None:
    configure(runtime_input_token_budget=50)
    refused = send(r)
    assert (refused.status_code, code(refused)) == (422, "context_too_large")
    assert stored(db_session) == []


def test_a_conversation_without_room_for_the_answer_is_full(r, db_session, configure) -> None:
    request = uuid.uuid4()
    r.provider.reply = ProviderError()
    configure(message_limit_per_conversation=3)
    send(r, "one", request)
    r.provider.reply = "Fine."
    assert send(r, "one", request).status_code == 201  # only the answer needs room
    refused = send(r, "two")
    assert (refused.status_code, code(refused)) == (409, "message_limit")
    assert len(stored(db_session)) == 2


def test_user_and_workspace_limits(r, db_session, configure, advance) -> None:
    configure(message_send_limit_per_user=2, message_send_limit_per_workspace=3)
    assert [send(r).status_code for _ in range(3)] == [201, 201, 429]
    owners = f"{r.chats}/{start(r.owner, r.chats)['id']}"
    sent = [send(r, client=r.owner, one=owners).status_code for _ in range(2)]
    assert sent == [201, 429]
    advance(minutes=61)
    assert send(r).status_code == 201


def test_refused_and_foreign_requests_do_not_use_up_the_limits(r, db_session, configure) -> None:
    configure(message_send_limit_per_user=1, message_send_limit_per_workspace=1)
    for client in (r.outsider, r.owner):
        assert send(r, client=client).status_code == 404
    assert send(r).status_code == 201


def test_default_limits() -> None:
    fields = Settings.model_fields
    names = ("message_send_limit_per_user", "message_send_limit_per_workspace")
    names += ("runtime_history_messages", "runtime_input_token_budget", "runtime_max_output_tokens")
    assert [fields[name].default for name in names] == [60, 200, 20, 32_000, 4_000]


def test_parallel_calls_are_capped_and_slots_come_back(r, db_session, monkeypatch) -> None:
    slots = service.threading.BoundedSemaphore(1)
    monkeypatch.setattr(service, "_slots", slots)
    slots.acquire()
    assert code(send(r)) == "provider_unavailable"
    assert stored(db_session) == []
    slots.release()
    r.provider.reply = ProviderError()
    request = uuid.uuid4()
    send(r, "x", request)
    r.provider.reply = "Fine."
    for response in (send(r, "x", request), send(r, "x", request), send(r, "other", request)):
        assert response.status_code in (201, 409)
    assert send(r, "y").status_code == 201


# The run itself: cancelling, and what may change during the call.


def accept(r, session, content="Hello", request_id=None, provider=None):
    return service.accept(
        session,
        context(session, r.workspace, r.member_id),
        r.agent,
        r.chat_id,
        provider or r.provider,
        request_id=request_id or uuid.uuid4(),
        content=content,
    )


def test_closing_the_pieces_cancels_and_stores_no_answer(r, db_session) -> None:
    r.provider.reply = [TextPiece("a"), TextPiece("b"), Completion("ab", 1, 1)]
    run = accept(r, db_session)
    pieces = run.pieces()
    assert next(pieces) == "a"
    pieces.close()
    run.close()
    run.close()
    assert r.provider.closed == 1
    assert stored(db_session) == [("user", "Hello", None)]
    assert records(db_session) == [("cancelled", "cancelled", 1, None)]
    assert send(r, "next").status_code == 201


def test_a_run_that_never_started_is_cancelled(r, db_session) -> None:
    accept(r, db_session).close()
    assert records(db_session) == [("cancelled", "cancelled", 1, None)]
    assert r.provider.calls == []


def test_pieces_come_in_order_and_a_repeat_comes_as_one(r, db_session) -> None:
    r.provider.reply = [TextPiece("a"), TextPiece("b"), Completion("ab", 1, 1)]
    request = uuid.uuid4()
    run = accept(r, db_session, request_id=request)
    assert list(run.pieces()) == ["a", "b"] and run.answer.content == "ab"
    run.close()
    again = accept(r, db_session, request_id=request)
    assert list(again.pieces()) == ["ab"] and again.answer.id == run.answer.id
    again.close()
    assert [row[0] for row in records(db_session)] == ["succeeded"]


def test_one_answer_at_a_time_per_conversation(r, db_session) -> None:
    request = uuid.uuid4()
    run = accept(r, db_session, request_id=request)
    for again in (send(r, "Hello", request), send(r, "other")):
        assert (again.status_code, code(again)) == (409, "answer_in_progress")
    second = f"{r.chats}/{start(r.member, r.chats)['id']}"
    assert send(r, one=second).status_code == 201
    run.close()
    assert send(r, "Hello", request).status_code == 201


def test_an_abandoned_run_stops_blocking_and_its_late_answer_is_dropped(
    r, db_session, advance
) -> None:
    request = uuid.uuid4()
    late = accept(r, db_session, request_id=request)
    advance(seconds=79)
    assert code(send(r, "Hello", request)) == "answer_in_progress"
    advance(seconds=81)
    assert send(r, "Hello", request).status_code == 201
    with pytest.raises(service.AnswerDiscardedError):
        list(late.pieces())
    late.close()
    assert len(stored(db_session)) == 2
    assert sorted(row[:2] for row in records(db_session)) == [
        ("failed", "abandoned"),
        ("succeeded", None),
    ]


@pytest.mark.parametrize("what", ["conversation", "agent", "membership"])
def test_nothing_is_stored_when_it_is_gone_after_the_call(r, db_session, what) -> None:
    r.provider.session = None

    def remove():
        workspace = f"/api/workspaces/{r.workspace}"
        response = {
            "conversation": lambda: r.member.delete(r.one),
            "agent": lambda: r.owner.delete(r.agent_url),
            "membership": lambda: r.owner.delete(f"{workspace}/members/{r.member_id}"),
        }[what]()
        assert response.status_code == 204

    r.provider.during = remove
    assert send(r).status_code == 404
    assert count(db_session, StoredMessage) == count(db_session, Execution) == 0


def test_a_pause_during_the_call_keeps_the_answer(r, db_session) -> None:
    r.provider.session = None
    r.provider.during = lambda: r.owner.post(f"{r.agent_url}/pause")
    assert send(r).status_code == 201
    r.provider.during = None
    assert code(send(r)) == "agent_paused"


# Records


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"status": "done"}, "ck_executions_status_valid"),
        ({"status": "succeeded"}, "ck_executions_success_has_answer"),
        ({"answer_sequence": 1}, "ck_executions_success_has_answer"),
        ({"finished_at": None}, "ck_executions_finished_unless_running"),
        ({"status": "running"}, "ck_executions_finished_unless_running"),
        ({"agent_version": 2}, "fk_executions_agent_id_agent_versions"),
        ({"message_sequence": 9}, "fk_executions_message"),
        ({"disclosure": None}, "disclosure"),
        (
            {"status": "succeeded", "message_sequence": 2, "answer_sequence": 9},
            "fk_executions_answer",
        ),
        ({"agent_id": uuid.uuid4()}, "fk_executions_"),
        ({"status": "running", "finished_at": None}, "uq_executions_running"),
        ({"status": "succeeded", "answer_sequence": 2}, "uq_executions_succeeded"),
    ],
)
def test_the_database_refuses_false_records(r, db_session, values, constraint) -> None:
    send(r)
    base = {"conversation_id": r.chat_id, "agent_id": r.agent, "agent_version": 1, "model": "m"}
    base |= {"message_sequence": 1, "started_at": clock.now(), "disclosure": "none"}
    db_session.add(Execution(**base, status="running"))
    db_session.flush()
    db_session.add(Execution(**base | {"status": "failed", "finished_at": clock.now()} | values))
    with pytest.raises(IntegrityError, match=constraint):
        db_session.flush()


def test_two_messages_cannot_share_a_request(r, db_session) -> None:
    request = uuid.uuid4()
    send(r, "Hello", request)
    db_session.add(
        StoredMessage(
            conversation_id=r.chat_id,
            agent_id=r.agent,
            sequence=9,
            role="user",
            content="x",
            request_id=request,
        )
    )
    with pytest.raises(IntegrityError, match="uq_messages_conversation_id_request_id"):
        db_session.flush()


@pytest.mark.parametrize("what", ["conversation", "agent", "workspace"])
def test_records_are_deleted_with_what_they_belong_to(r, db_session, what) -> None:
    send(r)
    r.owner.post("/api/workspaces", json={"name": "Other"})
    target = {
        "conversation": r.one,
        "agent": r.agent_url,
        "workspace": f"/api/workspaces/{r.workspace}",
    }[what]
    client = r.member if what == "conversation" else r.owner
    assert client.delete(target).status_code == 204
    assert count(db_session, Execution) == count(db_session, StoredMessage) == 0


def test_records_hold_no_text() -> None:
    """Every text column is a status, a code or a model name."""
    texts = {c.name for c in Execution.__table__.columns if "VARCHAR" in str(c.type).upper()}
    assert texts == {"status", "error_code", "model", "disclosure"}


# Races, on separate connections.


@pytest.fixture
def racing(factory, two_owners, auth_app):
    clients, _, workspace_id = two_owners
    url = f"/api/workspaces/{workspace_id}/agents"
    chats = f"{url}/{create(clients[0], url)['id']}/conversations"
    one = f"{chats}/{start(clients[0], chats)['id']}"
    provider = Recorder()
    auth_app.dependency_overrides[selection.get_provider] = lambda: provider

    def post(request_id, content="Hello"):
        body = {"request_id": str(request_id), "content": content}
        return clients[0].post(f"{one}/messages", json=body)

    return provider, post, workspace_id


def test_a_repeat_during_the_call_is_refused(factory, racing) -> None:
    provider, post, _ = racing
    request, during = uuid.uuid4(), []
    provider.during = lambda: during.append(post(request))
    assert post(request).status_code == 201
    assert [(x.status_code, code(x)) for x in during] == [(409, "answer_in_progress")]
    assert len(provider.calls) == 1
    with factory() as session:
        assert count(session, StoredMessage) == 2 and count(session, Execution) == 1


@pytest.mark.parametrize("same", [True, False])
def test_requests_that_meet_before_the_call_take_turns(factory, racing, same) -> None:
    """Both wait for the same lock. Nothing is stored twice and neither is a server error."""
    provider, post, workspace_id = racing
    first = uuid.uuid4()
    second = first if same else uuid.uuid4()
    responses = race(
        factory, lock_workspace(workspace_id), [lambda: post(first), lambda: post(second)]
    )
    statuses = sorted(x.status_code for x in responses)
    with factory() as session:
        questions = count(session, StoredMessage, StoredMessage.role == "user")
        answers = count(session, StoredMessage, StoredMessage.role == "assistant")
        done = count(session, Execution, Execution.status == "succeeded")
    # Whether the second finds the first running or finished depends on who gets the lock next.
    assert statuses in ([201, 201], [201, 409])
    assert len(provider.calls) == answers == done
    if same:
        assert (questions, answers) == (1, 1)
    else:
        assert questions == answers == statuses.count(201)


def test_a_lock_timeout_after_the_call_is_recorded_and_can_be_repeated(
    factory, racing, configure
) -> None:
    provider, post, workspace_id = racing
    configure(write_lock_timeout_seconds=1)
    request = uuid.uuid4()
    holder = factory()
    provider.during = lambda: holder.execute(lock_workspace(workspace_id))
    try:
        response = post(request)
    finally:
        holder.rollback()
        holder.close()
    assert (response.status_code, code(response)) == (503, "answer_not_saved")
    assert "Nothing was changed" not in response.text
    with factory() as session:
        record = session.scalars(select(Execution)).one()
        assert (record.status, record.error_code) == ("failed", "answer_not_saved")
        assert (record.input_tokens, record.output_tokens) == (7, 3)
    provider.during = None
    assert post(request).status_code == 201
    with factory() as session:
        assert count(session, StoredMessage) == 2


def test_a_record_that_cannot_be_settled_hides_no_error_and_frees_its_slot(
    r, db_session, monkeypatch
) -> None:
    slots = service.threading.BoundedSemaphore(1)
    monkeypatch.setattr(service, "_slots", slots)

    def broken(_):
        raise RuntimeError("no database")

    monkeypatch.setattr(service, "limit_write_time", broken)
    r.provider.reply = ProviderRefusedError()
    assert code(send(r)) == "provider_refused"
    assert records(db_session) == [("running", None, 1, None)]
    assert slots.acquire(blocking=False)
