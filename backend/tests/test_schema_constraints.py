"""The database itself enforces identity and tenancy rules."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Membership, User, UserSession, Workspace

pytestmark = pytest.mark.db


def make_user(session: Session, email: str = "alice@example.com") -> User:
    user = User(email=email, password_hash="argon2-hash-placeholder")
    session.add(user)
    session.flush()
    return user


def make_workspace(session: Session, name: str = "Acme") -> Workspace:
    workspace = Workspace(name=name)
    session.add(workspace)
    session.flush()
    return workspace


def make_session(session: Session, user: User, token_hash: str = "a" * 64) -> UserSession:
    row = UserSession(
        user_id=user.id, token_hash=token_hash, expires_at=datetime.now(UTC) + timedelta(days=1)
    )
    session.add(row)
    session.flush()
    return row


def count(session: Session, model, *where) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))


def test_database_generates_uuid_and_timezone_aware_timestamps(db_session: Session) -> None:
    db_session.execute(User.__table__.insert().values(email="raw@example.com", password_hash="h"))
    row = db_session.execute(
        select(User.__table__).where(User.__table__.c.email == "raw@example.com")
    ).one()
    assert isinstance(row.id, uuid.UUID)
    assert row.created_at.tzinfo is not None
    assert row.updated_at.tzinfo is not None


def test_email_unique_regardless_of_case(db_session: Session) -> None:
    make_user(db_session, "alice@example.com")
    with pytest.raises(IntegrityError, match="uq_users_email_lower"):
        make_user(db_session, "Alice@Example.com")


def test_membership_unique_per_user_and_workspace(db_session: Session) -> None:
    user = make_user(db_session)
    first, second = make_workspace(db_session, "One"), make_workspace(db_session, "Two")
    db_session.add(Membership(user_id=user.id, workspace_id=first.id, role="owner"))
    db_session.add(Membership(user_id=user.id, workspace_id=second.id, role="member"))
    db_session.flush()  # one user can belong to many workspaces

    db_session.add(Membership(user_id=user.id, workspace_id=first.id, role="member"))
    with pytest.raises(IntegrityError, match="uq_memberships_user_id_workspace_id"):
        db_session.flush()


@pytest.mark.parametrize("role", ["admin", "", "Owner"])
def test_membership_role_must_be_owner_or_member(db_session: Session, role: str) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    db_session.add(Membership(user_id=user.id, workspace_id=workspace.id, role=role))
    with pytest.raises(IntegrityError, match="ck_memberships_role_valid"):
        db_session.flush()


def test_membership_rejects_unknown_user(db_session: Session) -> None:
    workspace = make_workspace(db_session)
    db_session.add(Membership(user_id=uuid.uuid4(), workspace_id=workspace.id, role="member"))
    with pytest.raises(IntegrityError, match="fk_memberships_user_id_users"):
        db_session.flush()


def test_membership_rejects_unknown_workspace(db_session: Session) -> None:
    user = make_user(db_session)
    db_session.add(Membership(user_id=user.id, workspace_id=uuid.uuid4(), role="member"))
    with pytest.raises(IntegrityError, match="fk_memberships_workspace_id_workspaces"):
        db_session.flush()


def test_session_rejects_unknown_user(db_session: Session) -> None:
    db_session.add(
        UserSession(user_id=uuid.uuid4(), token_hash="b" * 64, expires_at=datetime.now(UTC))
    )
    with pytest.raises(IntegrityError, match="fk_sessions_user_id_users"):
        db_session.flush()


def test_session_token_hash_unique(db_session: Session) -> None:
    user = make_user(db_session)
    make_session(db_session, user, token_hash="c" * 64)
    with pytest.raises(IntegrityError, match="uq_sessions_token_hash"):
        make_session(db_session, user, token_hash="c" * 64)


def test_session_requires_expiry_and_allows_null_revocation(db_session: Session) -> None:
    user = make_user(db_session)
    row = make_session(db_session, user)
    assert row.revoked_at is None

    db_session.add(UserSession(user_id=user.id, token_hash="d" * 64, expires_at=None))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_workspace_removes_memberships_keeps_users(db_session: Session) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    db_session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    db_session.flush()

    db_session.execute(delete(Workspace).where(Workspace.id == workspace.id))

    assert count(db_session, Membership, Membership.workspace_id == workspace.id) == 0
    assert count(db_session, User, User.id == user.id) == 1


def test_deleting_user_removes_sessions_and_memberships_keeps_workspace(
    db_session: Session,
) -> None:
    user, workspace = make_user(db_session), make_workspace(db_session)
    db_session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    make_session(db_session, user)

    db_session.execute(delete(User).where(User.id == user.id))

    assert count(db_session, UserSession, UserSession.user_id == user.id) == 0
    assert count(db_session, Membership, Membership.user_id == user.id) == 0
    assert count(db_session, Workspace, Workspace.id == workspace.id) == 1
