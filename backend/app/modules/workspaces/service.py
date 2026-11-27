"""Workspace and membership rules.

Changes that depend on who the owners are start with ``_lock_owners``, which makes them take
turns, and then decide from the locked rows. The role seen when the request started is not
trusted: the caller may have been demoted or removed while waiting.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Row, delete, func, select, update
from sqlalchemy.orm import Session

from app.core.database import limit_write_time
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.identity.models import User
from app.modules.knowledge import storage as knowledge_storage
from app.modules.workspaces.models import Membership, Workspace

MAX_OWNED_WORKSPACES = 20
PERSONAL_WORKSPACE_NAME = "Personal workspace"


@dataclass(frozen=True)
class WorkspaceContext:
    """A workspace the caller is a member of. Built only by get_workspace_context."""

    workspace: Workspace
    user_id: uuid.UUID
    role: str


class LastOwnerError(ConflictError):
    code = "last_owner"
    message = "A workspace must keep at least one owner. Make someone else an owner first."


class WorkspaceLimitError(ConflictError):
    code = "workspace_limit"
    message = f"A person can own at most {MAX_OWNED_WORKSPACES} workspaces."


def list_workspaces(db: Session, user_id: uuid.UUID) -> Sequence[Row[tuple[Workspace, str]]]:
    return db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user_id)
        .order_by(Workspace.created_at, Workspace.id)
    ).all()


def add_workspace(db: Session, user_id: uuid.UUID, name: str) -> Workspace:
    """Add a workspace owned by the user. Does not commit."""
    _check_ownership_limit(db, user_id)
    workspace = Workspace(name=name)
    db.add(workspace)
    db.flush()
    db.add(Membership(user_id=user_id, workspace_id=workspace.id, role="owner"))
    db.flush()
    return workspace


def create_workspace(db: Session, user_id: uuid.UUID, name: str) -> Workspace:
    limit_write_time(db)
    workspace = add_workspace(db, user_id, name)
    db.commit()
    return workspace


def rename_workspace(db: Session, context: WorkspaceContext, name: str) -> Workspace:
    lock_owners_as_owner(db, context)
    db.execute(
        update(Workspace)
        .where(Workspace.id == context.workspace.id)
        .values(name=name)
        .execution_options(synchronize_session=False)
    )
    db.refresh(context.workspace)  # before commit: afterwards a waiting delete may win
    db.commit()
    return context.workspace


def delete_workspace(db: Session, context: WorkspaceContext) -> None:
    """Delete permanently. The database cascades to everything in the workspace."""
    lock_owners_as_owner(db, context)
    files = knowledge_storage.files_of(db, workspace_id=context.workspace.id)
    db.execute(delete(Workspace).where(Workspace.id == context.workspace.id))
    db.commit()
    knowledge_storage.remove(files)  # after the commit: a file can outlive its record, not reverse


def list_members(
    db: Session, context: WorkspaceContext
) -> Sequence[Row[tuple[uuid.UUID, str, str]]]:
    return db.execute(
        select(User.id, User.email, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == context.workspace.id)
        .order_by(func.lower(User.email))
    ).all()


def change_role(db: Session, context: WorkspaceContext, user_id: uuid.UUID, role: str) -> User:
    owners = lock_owners_as_owner(db, context)
    membership = _lock_membership(db, context, user_id)
    if membership.role != role:
        if role == "owner":
            _check_ownership_limit(db, user_id)
        else:
            _check_not_last_owner(owners, membership)
        membership.role = role
    user = membership.user
    db.commit()
    return user


def remove_member(db: Session, context: WorkspaceContext, user_id: uuid.UUID) -> None:
    owners = lock_owners_as_owner(db, context)
    membership = _lock_membership(db, context, user_id)
    _check_not_last_owner(owners, membership)
    db.delete(membership)
    db.commit()


def leave_workspace(db: Session, context: WorkspaceContext) -> None:
    owners = _lock_owners(db, context)
    membership = _lock_membership(db, context, context.user_id)
    _check_not_last_owner(owners, membership)
    db.delete(membership)
    db.commit()


def lock_for_member_write(db: Session, context: WorkspaceContext) -> None:
    """Make the workspace's writes take turns, and 404 unless the caller is still a member.

    Starts with the same lock as _lock_owners, so the two cannot deadlock. The share lock keeps
    a removal waiting until this transaction ends.
    """
    _lock_workspace(db, context)
    member = db.scalar(
        select(Membership.id)
        .where(
            Membership.workspace_id == context.workspace.id,
            Membership.user_id == context.user_id,
        )
        .with_for_update(read=True)
    )
    if member is None:
        raise NotFoundError()


def _lock_workspace(db: Session, context: WorkspaceContext) -> None:
    """Every write in an existing workspace starts here."""
    limit_write_time(db)
    db.execute(
        select(Workspace.id)
        .where(Workspace.id == context.workspace.id)
        .with_for_update(key_share=True)
    )


def _lock_owners(db: Session, context: WorkspaceContext) -> set[uuid.UUID]:
    """Lock the workspace's owner memberships until commit. Returns the owners' user ids.

    The workspace row is locked first, in its own statement. The owner query then starts after
    any earlier change has committed, so it sees everyone promoted meanwhile and cannot lock
    owners in a different order from another request (a deadlock).
    """
    _lock_workspace(db, context)
    return set(
        db.scalars(
            select(Membership.user_id)
            .where(Membership.workspace_id == context.workspace.id, Membership.role == "owner")
            .order_by(Membership.id)
            .with_for_update()
        )
    )


def lock_owners_as_owner(db: Session, context: WorkspaceContext) -> set[uuid.UUID]:
    owners = _lock_owners(db, context)
    if context.user_id not in owners:
        _lock_membership(db, context, context.user_id)  # 404 if no longer a member at all
        raise PermissionDeniedError()
    return owners


def _lock_membership(db: Session, context: WorkspaceContext, user_id: uuid.UUID) -> Membership:
    membership = db.scalar(
        select(Membership)
        .where(Membership.workspace_id == context.workspace.id, Membership.user_id == user_id)
        .with_for_update()
    )
    if membership is None:
        raise NotFoundError()
    return membership


def _check_not_last_owner(owners: set[uuid.UUID], membership: Membership) -> None:
    if membership.role == "owner" and not owners - {membership.user_id}:
        raise LastOwnerError()


def _check_ownership_limit(db: Session, user_id: uuid.UUID) -> None:
    """Make this user's ownership changes take turns, then count.

    The lock is on the user because a lock on existing memberships would not stop a new one.
    NO KEY UPDATE does not block inserts that reference the user, such as signing in.
    """
    db.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    owned = db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.user_id == user_id, Membership.role == "owner")
    )
    if (owned or 0) >= MAX_OWNED_WORKSPACES:
        raise WorkspaceLimitError()
