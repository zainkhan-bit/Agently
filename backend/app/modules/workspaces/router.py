"""Workspace and member endpoints under /api/workspaces."""

import uuid

from fastapi import APIRouter, status

from app.modules.identity.dependencies import CurrentUser, Db
from app.modules.workspaces import service
from app.modules.workspaces.dependencies import MemberContext, OwnerContext
from app.modules.workspaces.models import Workspace
from app.modules.workspaces.schemas import MemberOut, RoleInput, WorkspaceInput, WorkspaceOut

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _out(workspace: Workspace, role: str) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id, name=workspace.name, role=role, created_at=workspace.created_at
    )


@router.get("")
def list_workspaces(user: CurrentUser, db: Db) -> list[WorkspaceOut]:
    return [_out(workspace, role) for workspace, role in service.list_workspaces(db, user.id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_workspace(body: WorkspaceInput, user: CurrentUser, db: Db) -> WorkspaceOut:
    return _out(service.create_workspace(db, user.id, body.name), "owner")


@router.get("/{workspace_id}")
def get_workspace(context: MemberContext) -> WorkspaceOut:
    return _out(context.workspace, context.role)


@router.patch("/{workspace_id}")
def rename_workspace(body: WorkspaceInput, context: OwnerContext, db: Db) -> WorkspaceOut:
    return _out(service.rename_workspace(db, context, body.name), "owner")


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(context: OwnerContext, db: Db) -> None:
    service.delete_workspace(db, context)


@router.post("/{workspace_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_workspace(context: MemberContext, db: Db) -> None:
    service.leave_workspace(db, context)


@router.get("/{workspace_id}/members")
def list_members(context: MemberContext, db: Db) -> list[MemberOut]:
    return [
        MemberOut(user_id=user_id, email=email, role=role)
        for user_id, email, role in service.list_members(db, context)
    ]


@router.patch("/{workspace_id}/members/{user_id}")
def change_role(user_id: uuid.UUID, body: RoleInput, context: OwnerContext, db: Db) -> MemberOut:
    user = service.change_role(db, context, user_id, body.role)
    return MemberOut(user_id=user.id, email=user.email, role=body.role)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, context: OwnerContext, db: Db) -> None:
    service.remove_member(db, context, user_id)
