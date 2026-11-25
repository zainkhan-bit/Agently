"""Response shapes for conversations. No provider data and nothing about other people."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.agents.schemas import UtcDatetime


class ConversationOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    message_count: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ConversationPage(BaseModel):
    items: list[ConversationOut]
    total: int


class MessageOut(BaseModel):
    id: uuid.UUID
    sequence: int
    role: Literal["user", "assistant"]
    content: str = Field(repr=False)
    agent_version: int | None
    request_id: uuid.UUID | None  # to repeat the request of a message that was never answered
    created_at: UtcDatetime


class MessagePage(BaseModel):
    items: list[MessageOut]  # in order
    next_before: int | None  # pass as `before` for the messages before these; None at the start
