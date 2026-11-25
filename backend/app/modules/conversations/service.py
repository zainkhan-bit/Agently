"""Conversation rules.

A conversation is private to its creator: every query here names them. Writes lock like every
other write (workspace, membership, agent), then the conversation. Message text is private: it is
never logged and never part of an error.
"""

import uuid
from collections.abc import Sequence

from pydantic_core import PydanticCustomError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.text import check_text, is_blank
from app.modules.agents.service import ensure_can_run, lock_agent
from app.modules.conversations.models import ASSISTANT, ROLES, USER, Conversation, StoredMessage
from app.modules.workspaces.service import WorkspaceContext

MESSAGE_PAGE = 50


class ConversationLimitError(ConflictError):
    code = "conversation_limit"
    message = "You have too many conversations with this agent. Delete one first."


class MessageLimitError(ConflictError):
    code = "message_limit"
    message = "This conversation is full. Start a new one."


class MessageInvalidError(AppError):
    status_code = 422
    code = "message_invalid"
    message = "This message is empty, too long or contains invalid characters."


def list_conversations(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[Sequence[Conversation], int]:
    where = _own(context, agent_id)
    rows = db.scalars(
        select(Conversation)
        .where(*where)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count()).select_from(Conversation).where(*where)) or 0
    return rows, total


def create_conversation(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID
) -> Conversation:
    ensure_can_run(lock_agent(db, context, agent_id))
    count = db.scalar(
        select(func.count()).select_from(Conversation).where(*_own(context, agent_id))
    )
    if (count or 0) >= get_settings().conversation_limit_per_agent:
        raise ConversationLimitError()
    now = clock.now()
    conversation = Conversation(
        workspace_id=context.workspace.id,
        agent_id=agent_id,
        user_id=context.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    db.commit()
    return conversation


def delete_conversation(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """Delete permanently, also when the agent is paused or archived."""
    lock_agent(db, context, agent_id)
    deleted = db.execute(
        delete(Conversation)
        .where(Conversation.id == conversation_id, *_own(context, agent_id))
        .execution_options(synchronize_session=False)
    )
    if deleted.rowcount == 0:
        raise NotFoundError()
    db.commit()


def list_messages(
    db: Session,
    context: WorkspaceContext,
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    before: int | None,
) -> tuple[list[StoredMessage], int | None]:
    """One page in order, ending just before ``before``, and where the page before it ends."""
    query = (
        select(StoredMessage)
        .join(Conversation, Conversation.id == StoredMessage.conversation_id)
        .where(Conversation.id == conversation_id, *_own(context, agent_id))
        .order_by(StoredMessage.sequence.desc())
        .limit(MESSAGE_PAGE + 1)
    )
    if before is not None:
        query = query.where(StoredMessage.sequence < before)
    rows = db.scalars(query).all()
    page = list(reversed(rows[:MESSAGE_PAGE]))
    return page, page[0].sequence if len(rows) > MESSAGE_PAGE else None


def store_message(
    db: Session,
    context: WorkspaceContext,
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    role: str,
    content: str,
    agent_version: int | None = None,
    request_id: uuid.UUID | None = None,
) -> StoredMessage:
    """Add the next message. Does not commit. The role must never come from a request."""
    check_message(role, content, agent_version)
    conversation = lock_conversation(db, context, agent_id, conversation_id)
    if conversation.message_count >= get_settings().message_limit_per_conversation:
        raise MessageLimitError()
    now = clock.now()
    conversation.message_count += 1
    conversation.updated_at = now
    stored = StoredMessage(
        conversation_id=conversation.id,
        agent_id=agent_id,
        sequence=conversation.message_count,
        role=role,
        agent_version=agent_version,
        content=content,
        request_id=request_id,
        created_at=now,
    )
    db.add(stored)
    db.flush()
    return stored


def lock_conversation(
    db: Session, context: WorkspaceContext, agent_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    lock_agent(db, context, agent_id)
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, *_own(context, agent_id))
        .with_for_update()
        # The request already loaded it; without this it would keep the old count.
        .execution_options(populate_existing=True)
    )
    if conversation is None:
        raise NotFoundError()
    return conversation


def _own(context: WorkspaceContext, agent_id: uuid.UUID):
    return (
        Conversation.workspace_id == context.workspace.id,
        Conversation.agent_id == agent_id,
        Conversation.user_id == context.user_id,
    )


def check_message(role: str, content: str, agent_version: int | None) -> None:
    if role not in ROLES or (role == ASSISTANT) != (agent_version is not None):
        raise ValueError("invalid role, or a version that does not fit it")  # a mistake in our code
    settings = get_settings()
    maximum = (
        settings.user_message_max_characters
        if role == USER
        else settings.assistant_message_max_characters
    )
    try:
        valid = not is_blank(check_text(content, maximum))
    except PydanticCustomError:
        valid = False
    if not valid:
        raise MessageInvalidError()
