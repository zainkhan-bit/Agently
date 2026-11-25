"""Answers a message with the agent's own version.

Two short transactions around one model call. The first stores the person's message and a running
record, the second stores the answer and the result. In between nothing is locked and no database
connection is held, so everything is checked again afterwards.

Messages, instructions and answers are private: never logged and never part of an error.
"""

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, aliased

from app.core import clock
from app.core.config import get_settings
from app.core.database import limit_write_time
from app.core.errors import AppError, BusyError, ConflictError
from app.modules.agents.models import AgentVersion
from app.modules.agents.service import ensure_can_run, lock_agent
from app.modules.conversations.models import ASSISTANT, USER, Conversation, StoredMessage
from app.modules.conversations.service import (
    MessageInvalidError,
    MessageLimitError,
    check_message,
    lock_conversation,
    store_message,
)
from app.modules.providers.contract import (
    KNOWN_ERRORS,
    Completion,
    Message,
    Provider,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    TextPiece,
)
from app.modules.providers.selection import current_disclosure, current_model
from app.modules.runtime.models import (
    CANCELLED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    TIMED_OUT,
    Execution,
)
from app.modules.runtime.prompt import build_messages
from app.modules.workspaces.service import WorkspaceContext

logger = logging.getLogger(__name__)

ABANDONED_AFTER = timedelta(seconds=60)  # on top of the provider's timeout
# How often a running answer looks whether it was stopped: a proxy may keep its connection open
# after the person left, so closing the connection is not enough.
STOP_CHECK_SECONDS = 1.0
# A call holds one of the server's 40 worker threads, which every request needs.
_slots = threading.BoundedSemaphore(8)


class AnswerInProgressError(ConflictError):
    code = "answer_in_progress"
    message = "The agent is still answering in this conversation. Wait for it to finish."


class RequestReusedError(ConflictError):
    code = "request_reused"
    message = "This request was already used for a different message."


class RetryOutdatedError(ConflictError):
    code = "retry_outdated"
    message = "The conversation has moved on. Send the message again as a new one."


class AnswerDiscardedError(ConflictError):
    code = "answer_discarded"
    message = "The answer took too long and was not kept. Please try again."


class AnswerStoppedError(ConflictError):
    code = "answer_stopped"
    message = "The answer was stopped. Nothing was saved."


class AnswerInvalidError(AppError):
    status_code = 502
    code = "answer_invalid"
    message = "The AI returned an answer that cannot be used. Please try again."


class AnswerNotSavedError(BusyError):
    """Not its parent: by now the message is stored and the call was made."""

    code = "answer_not_saved"
    message = "The answer could not be saved. Please try again."


@dataclass
class Run:
    """One accepted message. Must be closed, which frees its slot and settles its record."""

    db: Session
    context: WorkspaceContext
    agent_id: uuid.UUID
    conversation_id: uuid.UUID
    question: StoredMessage
    answer: StoredMessage | None = None  # set at once when it had already been answered
    execution_id: uuid.UUID | None = None
    version: int = 0
    prompt: list[Message] = field(default_factory=list, repr=False)
    provider: Provider | None = None
    _started: float = field(default_factory=time.monotonic)
    _settled: bool = False
    _ending: tuple[str, str] = (CANCELLED, "cancelled")  # unless something else is recorded
    _closed: bool = False

    def pieces(self) -> Iterator[str]:
        """The answer in pieces; afterwards ``answer`` is the stored one. Closing it cancels."""
        if self.answer is not None:
            yield self.answer.content
            return
        maximum = get_settings().assistant_message_max_characters
        length = 0
        completion: Completion | None = None
        failure: AppError | None = None
        stream = None
        checked = time.monotonic()
        try:
            stream = _start(self.provider, self.prompt)
            while completion is None and failure is None:
                item = _next(stream)
                if time.monotonic() - checked >= STOP_CHECK_SECONDS:
                    checked = time.monotonic()
                    if self._stopped():
                        self._settled = True  # by whoever stopped it
                        failure = AnswerStoppedError()
                        break
                if isinstance(item, TextPiece):
                    length += len(item.text)
                    if length > maximum:
                        failure = AnswerInvalidError()
                    else:
                        yield item.text
                elif isinstance(item, Completion):
                    completion = item
                else:
                    failure = item
        finally:
            _close(stream)
        if failure is not None:
            self._settle(_status_of(failure), failure.code)
            raise failure
        self._store(completion)

    def _stopped(self) -> bool:
        """Whether someone stopped this run. Gives the connection back at once."""
        try:
            status = self.db.scalar(
                select(Execution.status).where(Execution.id == self.execution_id)
            )
            self.db.commit()
        except Exception as error:  # noqa: BLE001 - the answer goes on; storing checks again
            self.db.rollback()
            logger.warning("stop not checked (%s)", type(error).__name__)
            return False
        return status != RUNNING

    def _store(self, completion: Completion) -> None:
        self._ending = (FAILED, "internal_error")
        failure: AppError | None = None
        tokens = (completion.input_tokens, completion.output_tokens)
        try:
            self._store_answer(completion)
        except MessageInvalidError:
            failure = AnswerInvalidError()
        except BusyError:
            failure = AnswerNotSavedError()
        except AppError as error:
            failure = error
        if failure is not None:
            self._settle(FAILED, failure.code, *tokens)
            raise failure

    def _store_answer(self, completion: Completion) -> None:
        # 404 if the conversation, the agent or the membership is gone by now.
        lock_conversation(self.db, self.context, self.agent_id, self.conversation_id)
        execution = self.db.scalar(
            select(Execution)
            .where(Execution.id == self.execution_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if execution is None or execution.status != RUNNING:
            raise AnswerDiscardedError()
        answer = store_message(
            self.db,
            self.context,
            self.agent_id,
            self.conversation_id,
            role=ASSISTANT,
            content=completion.text,
            agent_version=self.version,
        )
        execution.status = SUCCEEDED
        execution.answer_sequence = answer.sequence
        execution.input_tokens = completion.input_tokens
        execution.output_tokens = completion.output_tokens
        execution.finished_at = clock.now()
        execution.duration_ms = self._duration()
        self.db.commit()
        self._settled = True
        self.answer = answer

    def _settle(
        self,
        status: str,
        code: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Record how it ended. If that fails, the record is abandoned later."""
        self._settled = True
        logger.warning("answer not stored (%s)", code)
        try:
            self.db.rollback()
            limit_write_time(self.db)
            self.db.execute(
                update(Execution)
                .where(Execution.id == self.execution_id, Execution.status == RUNNING)
                .values(
                    status=status,
                    error_code=code,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finished_at=clock.now(),
                    duration_ms=self._duration(),
                )
                .execution_options(synchronize_session=False)
            )
            self.db.commit()
        except Exception as error:  # noqa: BLE001 - the person gets the first error
            self.db.rollback()
            logger.warning("execution not settled (%s)", type(error).__name__)

    def _duration(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.execution_id is not None and not self._settled:
                self._settle(*self._ending)
        finally:
            _slots.release()


def stop(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """Stop the answer being made in this conversation, if any. Nothing of it will be stored."""
    lock_conversation(db, context, agent_id, conversation_id)
    db.execute(
        update(Execution)
        .where(Execution.conversation_id == conversation_id, Execution.status == RUNNING)
        .values(status=CANCELLED, error_code="stopped", finished_at=clock.now())
        .execution_options(synchronize_session=False)
    )
    db.commit()


def find_answer(
    db: Session, conversation: Conversation, *, request_id: uuid.UUID, content: str
) -> tuple[StoredMessage, StoredMessage] | None:
    """What a repeated request was already answered with. Needs no call, so nothing refuses it."""
    question = _question(db, conversation.id, request_id)
    if question is None:
        return None
    if question.content != content:
        raise RequestReusedError()
    answer = _answer_to(db, question)
    return (question, answer) if answer is not None else None


def accept(
    db: Session,
    context: WorkspaceContext,
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    provider: Provider | None,
    *,
    request_id: uuid.UUID,
    content: str,
) -> Run:
    """Check everything that can be checked and store the message. Commits. Close the result."""
    if provider is None:
        raise ProviderNotConfiguredError()
    check_message(USER, content, None)
    if not _slots.acquire(blocking=False):
        logger.warning("message refused (no free slot)")
        raise ProviderError()
    try:
        return _accept(db, context, agent_id, conversation_id, provider, request_id, content)
    except BaseException:
        _slots.release()
        raise


def _accept(
    db: Session,
    context: WorkspaceContext,
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    provider: Provider,
    request_id: uuid.UUID,
    content: str,
) -> Run:
    agent = lock_agent(db, context, agent_id)
    conversation = lock_conversation(db, context, agent_id, conversation_id)
    question = _question(db, conversation_id, request_id)
    if question is not None and question.content != content:
        raise RequestReusedError()
    if question is not None:
        answer = _answer_to(db, question)
        if answer is not None:
            db.commit()
            return Run(db, context, agent_id, conversation_id, question, answer)
    ensure_can_run(agent)
    _ensure_not_running(db, conversation)
    if question is not None and question.sequence != conversation.message_count:
        raise RetryOutdatedError()
    settings = get_settings()
    needed = 1 if question is not None else 2  # the answer must have room too
    if conversation.message_count + needed > settings.message_limit_per_conversation:
        raise MessageLimitError()
    version = db.scalars(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.number == agent.current_version
        )
    ).one()
    end = question.sequence if question is not None else conversation.message_count + 1
    prompt = build_messages(
        version,
        _history(db, conversation, end, settings.runtime_history_messages),
        content,
        token_budget=settings.runtime_input_token_budget,
    )
    if question is None:
        question = store_message(
            db,
            context,
            agent_id,
            conversation_id,
            role=USER,
            content=content,
            request_id=request_id,
        )
    execution = Execution(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        agent_id=agent_id,
        agent_version=version.number,
        message_sequence=question.sequence,
        status=RUNNING,
        model=current_model(),
        disclosure=current_disclosure(),
        started_at=clock.now(),
    )
    db.add(execution)
    # Also gives the connection back: the call can take long.
    db.commit()
    return Run(
        db,
        context,
        agent_id,
        conversation_id,
        question,
        execution_id=execution.id,
        version=version.number,
        prompt=prompt,
        provider=provider,
    )


def _question(
    db: Session, conversation_id: uuid.UUID, request_id: uuid.UUID
) -> StoredMessage | None:
    return db.scalar(
        select(StoredMessage).where(
            StoredMessage.conversation_id == conversation_id,
            StoredMessage.request_id == request_id,
        )
    )


def _answer_to(db: Session, question: StoredMessage) -> StoredMessage | None:
    return db.scalar(
        select(StoredMessage)
        .join(
            Execution,
            (Execution.conversation_id == StoredMessage.conversation_id)
            & (Execution.answer_sequence == StoredMessage.sequence),
        )
        .where(
            StoredMessage.conversation_id == question.conversation_id,
            Execution.message_sequence == question.sequence,
            Execution.status == SUCCEEDED,
        )
    )


def _ensure_not_running(db: Session, conversation: Conversation) -> None:
    """The conversation must be locked. A run that its server never finished is given up."""
    running = db.scalar(
        select(Execution)
        .where(Execution.conversation_id == conversation.id, Execution.status == RUNNING)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if running is None:
        return
    timeout = timedelta(seconds=get_settings().provider_timeout_seconds) + ABANDONED_AFTER
    now = clock.now()
    if running.started_at > now - timeout:
        raise AnswerInProgressError()
    running.status = FAILED
    running.error_code = "abandoned"
    running.finished_at = now
    db.flush()


def _history(
    db: Session, conversation: Conversation, end: int, maximum: int
) -> list[tuple[str, str]]:
    """The newest answered exchanges before ``end``, oldest first.

    Only those sent under the notice in force now: text typed under another one must not go to
    someone the person was not told about then.
    """
    question, answer = aliased(StoredMessage), aliased(StoredMessage)
    rows = db.execute(
        select(question.content, answer.content)
        .select_from(Execution)
        .join(
            question,
            (question.conversation_id == Execution.conversation_id)
            & (question.sequence == Execution.message_sequence),
        )
        .join(
            answer,
            (answer.conversation_id == Execution.conversation_id)
            & (answer.sequence == Execution.answer_sequence),
        )
        .where(
            Execution.conversation_id == conversation.id,
            Execution.status == SUCCEEDED,
            Execution.disclosure == current_disclosure(),
            Execution.message_sequence < end,
        )
        .order_by(Execution.message_sequence.desc())
        .limit(maximum // 2)
    ).all()
    return [(first, second) for first, second in reversed(rows)]


# Errors are returned, not raised, where they happen: raised there, they would keep the adapter's
# error, which may hold private text, as their context. Only known classes survive.


def _known(error: Exception) -> ProviderError:
    return type(error)() if type(error) in KNOWN_ERRORS else ProviderError()


def _start(provider: Provider | None, prompt: list[Message]):
    settings = get_settings()
    try:
        return provider.stream(
            prompt,
            timeout_seconds=settings.provider_timeout_seconds,
            max_output_tokens=settings.runtime_max_output_tokens,
        )
    except Exception:  # noqa: BLE001
        return None


def _next(stream) -> TextPiece | Completion | ProviderError:
    try:
        item = next(stream)
    except StopIteration:
        return ProviderError()
    except Exception as error:  # noqa: BLE001
        return _known(error)
    if isinstance(item, TextPiece) and isinstance(item.text, str):
        return item
    if isinstance(item, Completion) and isinstance(item.text, str) and not item.tool_calls:
        counts = (item.input_tokens, item.output_tokens)
        if all(type(count) is int and 0 <= count < 10**9 for count in counts):
            return item
    return ProviderError()


def _close(stream) -> None:
    try:
        if stream is not None:
            stream.close()
    except Exception as error:  # noqa: BLE001
        logger.warning("model stream not closed (%s)", type(error).__name__)


def _status_of(failure: AppError) -> str:
    return TIMED_OUT if isinstance(failure, ProviderTimeoutError) else FAILED
