"""The only way for a request to reach a conversation: as its creator."""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.core.errors import NotFoundError, RateLimitError
from app.modules.agents.dependencies import AgentInWorkspace
from app.modules.conversations.models import Conversation
from app.modules.identity import throttle
from app.modules.identity.dependencies import CurrentUser, Db
from app.modules.workspaces.dependencies import MemberContext


def get_conversation(
    conversation_id: uuid.UUID, agent: AgentInWorkspace, context: MemberContext, db: Db
) -> Conversation:
    """404 unless the caller created it with the agent in the path, whatever their role.

    Every route with ``conversation_id`` in its path must depend on this;
    tests/test_tenant_isolation.py enforces it.
    """
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.agent_id == agent.id,
            Conversation.user_id == context.user_id,
        )
    )
    if conversation is None:
        raise NotFoundError()
    return conversation


OwnConversation = Annotated[Conversation, Depends(get_conversation)]


def count_conversation_create(_: AgentInWorkspace, user: CurrentUser, db: Db) -> None:
    """Commits, so nothing may be locked yet."""
    if throttle.record_attempt(db, throttle.conversation_create_limits(user.id)) is None:
        raise RateLimitError()
