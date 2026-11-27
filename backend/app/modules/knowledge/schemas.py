"""Response shapes for knowledge sources. Never the stored name, the hash or any content."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from app.modules.agents.schemas import UtcDatetime

ERROR_MESSAGES = {
    "text_empty": "No text was found. Scanned documents need text recognition, which is not "
    "available.",
    "text_unreadable": "The document could not be read. It may be damaged or password-protected.",
    "text_too_long": "The document has too much text.",
    "pages_too_many": "The document has too many pages (at most 500).",
    "processing_timeout": "Reading the document took too long.",
    "processing_failed": "The document could not be processed. Delete it and try again.",
    "file_missing": "The stored file is missing. Delete it and upload it again.",
}


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

    @computed_field
    @property
    def error_message(self) -> str | None:
        """Why processing failed, in words people can act on. Fixed texts only."""
        if self.error_code is None:
            return None
        return ERROR_MESSAGES.get(self.error_code, ERROR_MESSAGES["processing_failed"])


class SourcePage(BaseModel):
    items: list[SourceOut]  # newest first
    total: int
