"""Request and response shapes for workspaces and members."""

import unicodedata
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel
from pydantic_core import PydanticCustomError

# Text-direction controls could make a name disguise the text shown next to it.
_BIDI_CONTROLS = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)
_INVISIBLE = frozenset({"Cc", "Cf", "Cn", "Mn", "Me", "Zl", "Zp", "Zs"})

Role = Literal["owner", "member"]


def _check_name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100:
        raise PydanticCustomError("name_length", "Name must be 1 to 100 characters.")
    categories = {unicodedata.category(char) for char in value}
    if categories & {"Cc", "Cs", "Zl", "Zp"} or _BIDI_CONTROLS & set(value):
        raise PydanticCustomError("name_invalid", "Name contains invalid characters.")
    if categories <= _INVISIBLE:
        raise PydanticCustomError("name_invalid", "Name needs at least one visible character.")
    return value


class WorkspaceInput(BaseModel):
    name: Annotated[str, AfterValidator(_check_name)]


class RoleInput(BaseModel):
    role: Role


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role  # the caller's own role
    created_at: datetime


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    role: Role
