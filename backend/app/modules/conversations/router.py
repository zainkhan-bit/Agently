"""Conversations under /api/workspaces/{workspace_id}/agents/{agent_id}/conversations.

Nothing here accepts a message: the runtime does, and only a person's own words.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.modules.agents.dependencies import AgentInWorkspace
from app.modules.conversations import service
from app.modules.conversations.dependencies import (
    OwnConversation,
    count_conversation_create,
    never_cached,
)
from app.modules.conversations.models import Conversation
from app.modules.conversations.schemas import (
    ConversationOut,
    ConversationPage,
    MessageOut,
    MessagePage,
)
from app.modules.identity.dependencies import Db
from app.modules.workspaces.dependencies import MemberContext

router = APIRouter(
    prefix="/workspaces/{workspace_id}/agents/{agent_id}/conversations",
    tags=["conversations"],
    dependencies=[Depends(never_cached)],
)


def _out(conversation: Conversation) -> ConversationOut:
    return ConversationOut.model_validate(conversation, from_attributes=True)


@router.get("")
def list_conversations(
    agent: AgentInWorkspace,
    context: MemberContext,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ConversationPage:
    rows, total = service.list_conversations(db, context, agent.id, limit=limit, offset=offset)
    return ConversationPage(items=[_out(row) for row in rows], total=total)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(count_conversation_create)],
)
def create_conversation(agent: AgentInWorkspace, context: MemberContext, db: Db) -> ConversationOut:
    return _out(service.create_conversation(db, context, agent.id))


@router.get("/{conversation_id}")
def get_conversation(conversation: OwnConversation) -> ConversationOut:
    return _out(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation: OwnConversation, agent: AgentInWorkspace, context: MemberContext, db: Db
) -> None:
    service.delete_conversation(db, context, agent.id, conversation.id)


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation: OwnConversation,
    agent: AgentInWorkspace,
    context: MemberContext,
    db: Db,
    before: Annotated[int | None, Query(ge=1, le=1_000_000)] = None,
) -> MessagePage:
    """The newest page without ``before``; the one before it with the last ``next_before``."""
    rows, next_before = service.list_messages(db, context, agent.id, conversation.id, before)
    items = [MessageOut.model_validate(row, from_attributes=True) for row in rows]
    return MessagePage(items=items, next_before=next_before)
