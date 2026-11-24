"""Request and response shapes for workspaces and members."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.text import Name

Role = Literal["owner", "member"]


class WorkspaceInput(BaseModel):
    name: Name


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
