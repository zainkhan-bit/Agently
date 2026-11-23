"""The only way for a request to reach a workspace: the caller's own membership."""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.identity.dependencies import CurrentUser, Db
from app.modules.workspaces.models import Membership, Workspace
from app.modules.workspaces.service import WorkspaceContext


def get_workspace_context(workspace_id: uuid.UUID, user: CurrentUser, db: Db) -> WorkspaceContext:
    """Resolve the workspace for a member, or 404 exactly as if it did not exist.

    Every route with ``workspace_id`` in its path must depend on this;
    tests/test_tenant_isolation.py enforces it.
    """
    row = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Workspace.id == workspace_id, Membership.user_id == user.id)
    ).one_or_none()
    if row is None:
        raise NotFoundError()
    return WorkspaceContext(workspace=row[0], user_id=user.id, role=row[1])


MemberContext = Annotated[WorkspaceContext, Depends(get_workspace_context)]


def require_owner(context: MemberContext) -> WorkspaceContext:
    """403 for members: they already know the workspace exists.

    This is the early answer. The service re-checks under a lock before changing anything.
    """
    if context.role != "owner":
        raise PermissionDeniedError()
    return context


OwnerContext = Annotated[WorkspaceContext, Depends(require_owner)]
