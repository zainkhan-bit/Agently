"""Request and response shapes for agents."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field
from pydantic_core import PydanticCustomError

from app.core.text import Name, check_text, is_blank

Status = Literal["active", "paused", "archived"]
INSTRUCTIONS_MAX, PURPOSE_MAX, DESCRIPTION_MAX = 10_000, 500, 1_000


def _check_instructions(value: str) -> str:
    check_text(value, INSTRUCTIONS_MAX)
    if is_blank(value):
        raise PydanticCustomError("instructions_blank", "Instructions are required.")
    return value


def _optional(maximum: int) -> AfterValidator:
    def check(value: str | None) -> str | None:
        if value is None:
            return None
        return check_text(value.strip(), maximum) or None

    return AfterValidator(check)


def _no_model(value: Any) -> None:
    if value is not None:
        raise PydanticCustomError("model_unavailable", "No models are available yet.")


Instructions = Annotated[str, AfterValidator(_check_instructions)]
Purpose = Annotated[str | None, _optional(PURPOSE_MAX)]
Description = Annotated[str | None, _optional(DESCRIPTION_MAX)]
Model = Annotated[None, BeforeValidator(_no_model)]
# The database driver answers in the server's time zone, the application writes UTC.
UtcDatetime = Annotated[datetime, AfterValidator(lambda value: value.astimezone(UTC))]


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    purpose: Purpose = None
    description: Description = None
    instructions: Instructions
    model: Model = None


class AgentUpdate(BaseModel):
    """Fields left out stay unchanged, so the defaults below are never used."""

    model_config = ConfigDict(extra="forbid")

    version: Annotated[int, Field(strict=True, ge=1)]  # the version this edit started from
    name: Name = ""
    purpose: Purpose = None
    description: Description = None
    instructions: Instructions = ""
    model: Model = None

    def changes(self) -> dict[str, str | None]:
        return self.model_dump(exclude_unset=True, exclude={"version"})


class AgentSummary(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    status: Status
    version: int
    name: str
    purpose: str | None
    description: str | None
    model: str | None
    created_by: uuid.UUID | None
    version_created_by: uuid.UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class AgentOut(AgentSummary):
    instructions: str


class Rollback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Annotated[int, Field(strict=True, ge=1)]  # the current version the person saw


class VersionBase(BaseModel):
    id: uuid.UUID
    number: int
    name: str
    restored_from: int | None
    saved_by: str | None  # email, only while they are a member of the workspace
    created_at: UtcDatetime


class VersionSummary(VersionBase):
    is_current: bool
    changed: list[str] | None  # compared with the version before; None for the first


class VersionOut(VersionBase):
    purpose: str | None
    description: str | None
    instructions: str
    model: str | None


class VersionPage(BaseModel):
    items: list[VersionSummary]
    next_before: int | None  # pass as `before` for the next page; None on the last


class AgentPage(BaseModel):
    items: list[AgentSummary]
    total: int
