"""Sending a message to an agent, under its conversation."""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import RateLimitError
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
