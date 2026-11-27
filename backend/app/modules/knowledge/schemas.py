"""Response shapes for knowledge sources. Never the stored name, the hash or any content."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.agents.schemas import UtcDatetime


class SourceOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    name: str = Field(repr=False)
    kind: Literal["pdf", "docx", "txt", "md"]
    size_bytes: int
    status: Literal["pending", "processing", "ready", "failed"]
    error_code: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class SourcePage(BaseModel):
    items: list[SourceOut]  # newest first
    total: int
