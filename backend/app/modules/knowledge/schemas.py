"""Request and response shapes for knowledge sources and search.

A source never shows its stored name, its hash or its content. Search returns excerpts of
content to members of the workspace, and its questions are never echoed back in errors.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.core.config import get_settings
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


class SearchRequest(BaseModel):
    """The question goes in the body, never the URL, because access logs print URLs."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=1, repr=False)
    limit: int | None = None

    # The limits come from the settings, so a lower configured cap is enforced here. Messages
    # name the limit and never repeat the question.
    @field_validator("question")
    @classmethod
    def _question_not_too_long(cls, value: str) -> str:
        maximum = get_settings().knowledge_search_question_max_chars
        if len(value) > maximum:
            raise ValueError(f"at most {maximum} characters")
        return value

    @field_validator("limit")
    @classmethod
    def _limit_in_range(cls, value: int | None) -> int | None:
        maximum = get_settings().knowledge_search_max_results
        if value is not None and not 1 <= value <= maximum:
            raise ValueError(f"between 1 and {maximum}")
        return value


class ExcerptOut(BaseModel):
    source_id: uuid.UUID
    source_name: str = Field(repr=False)
    page: int | None
    sequence: int
    text: str = Field(repr=False)


class SearchResults(BaseModel):
    items: list[ExcerptOut]  # best first; there is deliberately no score
