"""Sending a message to an agent, under its conversation."""

import json
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError, RateLimitError
from app.modules.agents.dependencies import AgentInWorkspace
from app.modules.conversations.dependencies import OwnConversation, never_cached
from app.modules.conversations.models import StoredMessage
from app.modules.conversations.schemas import MessageOut
from app.modules.identity import throttle
from app.modules.identity.dependencies import CurrentUser, Db
from app.modules.providers.selection import CurrentProvider, check_disclosure
from app.modules.runtime import service
from app.modules.workspaces.dependencies import MemberContext

router = APIRouter(
    prefix="/workspaces/{workspace_id}/agents/{agent_id}/conversations/{conversation_id}",
    tags=["runtime"],
    dependencies=[Depends(never_cached)],
)


class MessageLimitReachedError(RateLimitError):
    message = "You or your workspace sent too many messages. Please try again later."


class SendMessage(BaseModel):
    """A person's words. The role, version, model and provider are never theirs to choose."""

    model_config = ConfigDict(extra="forbid")

    # A new random id for each message; the same one again when a request is repeated.
    request_id: uuid.UUID
    content: str = Field(repr=False)


class AnswerOut(BaseModel):
    message: MessageOut
    answer: MessageOut


def _out(message: StoredMessage, answer: StoredMessage) -> AnswerOut:
    return AnswerOut(
        message=MessageOut.model_validate(message, from_attributes=True),
        answer=MessageOut.model_validate(answer, from_attributes=True),
    )


def count_message(_: OwnConversation, context: MemberContext, user: CurrentUser, db: Db) -> None:
    """After the creator check, so that nobody else's requests count. Commits."""
    limits = throttle.message_limits(user.id, context.workspace.id)
    if throttle.record_attempt(db, limits) is None:
        raise MessageLimitReachedError()


@router.post(
    "/messages", status_code=status.HTTP_201_CREATED, dependencies=[Depends(count_message)]
)
def send_message(
    body: SendMessage,
    conversation: OwnConversation,
    agent: AgentInWorkspace,
    context: MemberContext,
    db: Db,
    provider: CurrentProvider,
    disclosure: str = "none",
) -> AnswerOut:
    """``disclosure`` is the notice the person saw. A message sent under another is not sent on."""
    found = service.find_answer(db, conversation, request_id=body.request_id, content=body.content)
    if found is not None:
        return _out(*found)
    check_disclosure(disclosure)
    run = service.accept(
        db,
        context,
        agent.id,
        conversation.id,
        provider,
        request_id=body.request_id,
        content=body.content,
    )
    try:
        for _ in run.pieces():
            pass
        return _out(run.question, run.answer)
    finally:
        run.close()


@router.post("/messages/stream", dependencies=[Depends(count_message)])
def stream_message(
    body: SendMessage,
    conversation: OwnConversation,
    agent: AgentInWorkspace,
    context: MemberContext,
    db: Db,
    provider: CurrentProvider,
    disclosure: str = "none",
) -> StreamingResponse:
    """Like ``send_message``, as server-sent events: ``message``, then ``piece`` events with
    text, then ``done`` with both messages, or ``error``. Everything refused before the call is an
    ordinary error response. Closing the connection cancels the answer.
    """
    found = service.find_answer(db, conversation, request_id=body.request_id, content=body.content)
    if found is not None:
        return _events(None, *found)
    check_disclosure(disclosure)
    run = service.accept(
        db,
        context,
        agent.id,
        conversation.id,
        provider,
        request_id=body.request_id,
        content=body.content,
    )
    return _events(run, run.question, None)


@router.post("/messages/stop", status_code=status.HTTP_204_NO_CONTENT)
def stop_answer(
    conversation: OwnConversation, agent: AgentInWorkspace, context: MemberContext, db: Db
) -> None:
    """Stop the answer being made, also when its connection is still open somewhere."""
    service.stop(db, context, agent.id, conversation.id)


def _events(
    run: service.Run | None, question: StoredMessage, answer: StoredMessage | None
) -> StreamingResponse:
    def events() -> Iterator[str]:
        try:
            yield _event("message", _message(question))
            if run is None:
                yield _event("done", _out(question, answer).model_dump(mode="json"))
                return
            failure: AppError | None = None
            try:
                for piece in run.pieces():
                    yield _event("piece", {"text": piece})
            except AppError as error:  # fixed texts only, so they may be shown
                failure = error
            if failure is not None:
                yield _event("error", {"code": failure.code, "message": failure.message})
            else:
                yield _event("done", _out(run.question, run.answer).model_dump(mode="json"))
        finally:
            if run is not None:
                run.close()

    headers = {
        # no-transform: a compressing proxy would hold the pieces back.
        "Cache-Control": "private, no-store, no-transform",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


def _message(message: StoredMessage) -> dict:
    return MessageOut.model_validate(message, from_attributes=True).model_dump(mode="json")


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
